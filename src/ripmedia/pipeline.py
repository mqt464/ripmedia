from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Callable
import subprocess
import tempfile

from .downloader import download_with_ytdlp
from .errors import DownloadError, MetadataError, PartialSuccessError, RipmediaError
from .model import Attribution, MediaKind, NormalizedItem, Provider
from .paths import build_collection_item_plan, build_output_plan, collection_directory
from .resolver import resolve_candidates
from .tagger import Artwork, tag_file
from rich.progress import Progress

from .ui import LiveProgress, StepResult, Ui


def run_info(
    url: str,
    *,
    ui: Ui,
    cookies: Path | None = None,
    cookies_from_browser: str | None = None,
) -> NormalizedItem:
    _ = ui
    return _fetch_metadata(url, cookies=cookies, cookies_from_browser=cookies_from_browser)


def _default_extension(item: NormalizedItem, *, audio: bool, prefer_mp3_mp4: bool) -> str:
    if prefer_mp3_mp4:
        return "mp3" if audio else "mp4"
    if audio:
        return "m4a"
    if item.kind == MediaKind.TRACK:
        return "m4a"
    return "mp4"


def _normalize_override(value: str | None) -> str | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v or v in {"false", "none", "null"}:
        return None
    return v.lstrip(".") or None


def _should_download_audio(item: NormalizedItem, *, audio_flag: bool) -> bool:
    if audio_flag:
        return True
    # Audio-first defaults:
    # - SoundCloud is audio-only
    # - Spotify resolves to an audio track by intent
    # - Items detected as TRACK should default to audio
    if item.provider in {Provider.SOUNDCLOUD, Provider.SPOTIFY}:
        return True
    return item.kind == MediaKind.TRACK


def _collection_track_number(item: NormalizedItem) -> int | None:
    extra = item.extra if isinstance(item.extra, dict) else {}
    playlist_index = extra.get("playlist_index") if isinstance(extra, dict) else None
    if isinstance(playlist_index, int):
        return playlist_index
    if isinstance(playlist_index, str):
        try:
            return int(playlist_index)
        except ValueError:
            pass
    return item.track_number


def run_download(
    url: str,
    *,
    output_dir: Path,
    audio: bool,
    override_audio_format: str | None,
    override_video_format: str | None,
    resolver: str,
    interactive: bool,
    cookies: Path | None,
    cookies_from_browser: str | None,
    ui: Ui,
    prefer_mp3_mp4: bool,
    show_file_size: bool = False,
    progress: Progress | None = None,
    progress_task_id: int | None = None,
    live: LiveProgress | None = None,
    show_stage: bool = True,
    metadata_callback: Callable[[NormalizedItem], None] | None = None,
    status_callback: Callable[[str], None] | None = None,
    step_callback: Callable[[StepResult], None] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> list[Path]:
    _tick(live, status_callback, "Metadata")
    meta_start = monotonic()
    try:
        item = _fetch_metadata(url, cookies=cookies, cookies_from_browser=cookies_from_browser)
    except RipmediaError as e:
        _record_step(live, step_callback, "Metadata", False, str(e), meta_start)
        raise
    if metadata_callback is not None:
        metadata_callback(item)
    _record_step(live, step_callback, "Metadata", True, None, meta_start)
    if show_stage:
        ui.stage("Detected", f"{item.provider.value} · {item.kind.value}")

    if item.kind in {MediaKind.PLAYLIST, MediaKind.ALBUM}:
        return _run_collection(
            item,
            output_dir=output_dir,
            audio=audio,
            override_audio_format=override_audio_format,
            override_video_format=override_video_format,
            resolver=resolver,
            interactive=interactive,
            cookies=cookies,
            cookies_from_browser=cookies_from_browser,
            ui=ui,
            prefer_mp3_mp4=prefer_mp3_mp4,
            show_file_size=show_file_size,
            progress=progress,
            progress_task_id=progress_task_id,
            live=live,
            show_stage=show_stage,
            status_callback=status_callback,
            step_callback=step_callback,
            progress_callback=progress_callback,
        )

    path = _run_single(
        item,
        output_dir=output_dir,
        audio=audio,
        override_audio_format=override_audio_format,
        override_video_format=override_video_format,
        resolver=resolver,
        interactive=interactive,
        cookies=cookies,
        cookies_from_browser=cookies_from_browser,
        ui=ui,
        prefer_mp3_mp4=prefer_mp3_mp4,
        show_file_size=show_file_size,
        progress=progress,
        progress_task_id=progress_task_id,
        live=live,
        show_stage=show_stage,
        status_callback=status_callback,
        step_callback=step_callback,
        progress_callback=progress_callback,
    )
    if show_stage:
        ui.stage("Saved", ui.path_link(path))
    return [path]


def _run_collection(
    item: NormalizedItem,
    *,
    output_dir: Path,
    audio: bool,
    override_audio_format: str | None,
    override_video_format: str | None,
    resolver: str,
    interactive: bool,
    cookies: Path | None,
    cookies_from_browser: str | None,
    ui: Ui,
    prefer_mp3_mp4: bool,
    show_file_size: bool,
    progress: Progress | None,
    progress_task_id: int | None,
    live: LiveProgress | None,
    show_stage: bool,
    status_callback: Callable[[str], None] | None,
    step_callback: Callable[[StepResult], None] | None,
    progress_callback: Callable[[dict], None] | None,
) -> list[Path]:
    if not item.entries:
        raise MetadataError("This collection has no entries (or expansion is unsupported).", stage="Metadata")

    folder = collection_directory(item, output_dir=output_dir)
    folder.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    failures: list[tuple[str, str, str | None]] = []

    total = len(item.entries)
    for idx, entry in enumerate(item.entries, start=1):
        working_entry = entry
        parent_album = item.album or item.title
        if parent_album and not working_entry.album:
            working_entry = replace(working_entry, album=parent_album)
        if item.artist and not working_entry.artist:
            working_entry = replace(working_entry, artist=item.artist)
        if item.artwork_url and not working_entry.artwork_url:
            working_entry = replace(working_entry, artwork_url=item.artwork_url)
        title = working_entry.title or working_entry.url
        if ui.level != "quiet" and not ui.print_path_only and live is None:
            ui.info(f"[dim]{idx}/{total}[/dim] {title}")
        collection_index = _collection_track_number(working_entry)
        try:
            saved_path = _run_single(
                working_entry,
                output_dir=folder,
                audio=audio,
                override_audio_format=override_audio_format,
                override_video_format=override_video_format,
                resolver=resolver,
                interactive=interactive,
                cookies=cookies,
                cookies_from_browser=cookies_from_browser,
                ui=ui,
                in_collection=True,
                collection_index=collection_index,
                prefer_mp3_mp4=prefer_mp3_mp4,
                show_file_size=show_file_size,
                progress=progress,
                progress_task_id=progress_task_id,
                live=live,
                show_stage=show_stage,
                status_callback=status_callback,
                step_callback=step_callback,
                progress_callback=progress_callback,
            )
            saved.append(saved_path)
        except RipmediaError as e:
            failures.append((entry.url, str(e), e.stage))
            continue
        except Exception as e:  # noqa: BLE001
            failures.append((entry.url, str(e), None))
            continue

    if failures and saved:
        if show_stage:
            ui.stage("Saved", ui.path_link(folder))
        raise PartialSuccessError(
            f"{len(failures)}/{total} items failed",
            stage="Downloading",
            saved_paths=saved,
            failures=failures,
        )
    if failures and not saved:
        raise MetadataError("All items in the collection failed.", stage="Downloading")
    if saved and show_stage:
        ui.stage("Saved", ui.path_link(folder))
    return saved


def _run_single(
    item: NormalizedItem,
    *,
    output_dir: Path,
    audio: bool,
    override_audio_format: str | None,
    override_video_format: str | None,
    resolver: str,
    interactive: bool,
    cookies: Path | None,
    cookies_from_browser: str | None,
    ui: Ui,
    in_collection: bool = False,
    collection_index: int | None = None,
    prefer_mp3_mp4: bool = True,
    show_file_size: bool = False,
    progress: Progress | None = None,
    progress_task_id: int | None = None,
    live: LiveProgress | None = None,
    show_stage: bool = True,
    status_callback: Callable[[str], None] | None,
    step_callback: Callable[[StepResult], None] | None,
    progress_callback: Callable[[dict], None] | None,
) -> Path:
    download_url = item.url
    working_item = item
    if item.provider == Provider.SPOTIFY and item.kind == MediaKind.TRACK:
        resolve_start = monotonic()
        _tick(live, status_callback, "Resolve")
        resolver_name = resolver.strip().lower()
        preferred = Provider.SOUNDCLOUD if resolver_name == "soundcloud" else Provider.YOUTUBE

        candidates = resolve_candidates(item, preferred=preferred, limit=5)
        if not candidates:
            err = MetadataError("No resolver candidates found.", stage="Resolve")
            _record_step(live, step_callback, "Resolve", False, str(err), resolve_start)
            raise err

        best = candidates[0]
        hint = f" ({best.confidence_hint})" if best.confidence_hint else ""
        if show_stage:
            ui.stage("Resolve", f"spotify → {best.provider.value}…{hint}")

        if best.confidence < 0.6 and not interactive:
            err = MetadataError(
                "Low confidence match. Re-run with `--interactive` to choose a candidate, or "
                "try `--resolver soundcloud`.",
                stage="Resolve",
            )
            _record_step(live, step_callback, "Resolve", False, str(err), resolve_start)
            raise err

        selected = best
        if interactive:
            if ui.level == "quiet" or ui.print_path_only:
                err = MetadataError(
                    "Interactive mode is not available with --quiet/--print-path.",
                    stage="Resolve",
                )
                _record_step(live, step_callback, "Resolve", False, str(err), resolve_start)
                raise err
            ui.info("Candidates:")
            for i, c in enumerate(candidates, start=1):
                h = f" ({c.confidence_hint})" if c.confidence_hint else ""
                title = c.selected_title or c.url
                ui.info(f"[dim]{i}[/dim]. {title} [dim]score={c.confidence:.2f}{h}[/dim]")
            raw = ui.console.input("Select [1]: ").strip()
            if raw:
                try:
                    idx = int(raw)
                except ValueError as e:
                    err = MetadataError("Invalid selection.", stage="Resolve")
                    _record_step(live, step_callback, "Resolve", False, str(err), resolve_start)
                    raise err from e
                if idx < 1 or idx > len(candidates):
                    err = MetadataError("Selection out of range.", stage="Resolve")
                    _record_step(live, step_callback, "Resolve", False, str(err), resolve_start)
                    raise err
                selected = candidates[idx - 1]

        if ui.level in ("verbose", "debug") and selected.selected_title:
            ui.verbose(f"Selected: {selected.selected_title}")
        if ui.level in ("verbose", "debug"):
            ui.verbose(f"URL: {selected.url}")

        download_url = selected.url
        working_item = replace(
            item,
            attribution=Attribution(metadata_source=Provider.SPOTIFY, media_source=selected.provider),
        )
        _record_step(live, step_callback, "Resolve", True, None, resolve_start)

    want_audio = _should_download_audio(working_item, audio_flag=audio)
    audio_override = _normalize_override(override_audio_format) if want_audio else None
    video_override = _normalize_override(override_video_format) if not want_audio else None
    ext = audio_override or video_override or _default_extension(
        working_item, audio=want_audio, prefer_mp3_mp4=prefer_mp3_mp4
    )
    if in_collection:
        track_number = collection_index if collection_index is not None else working_item.track_number
        output_plan = build_collection_item_plan(
            working_item, output_dir=output_dir, extension=ext, track_number=track_number
        )
    else:
        output_plan = build_output_plan(working_item, output_dir=output_dir, extension=ext)

    display_name = (
        f"{working_item.artist} - {working_item.title}"
        if working_item.artist and working_item.title
        else (working_item.title or working_item.url)
    )
    _tick(live, status_callback, f"Download: {display_name[:60]}")
    if show_stage:
        ui.stage("Downloading", display_name)
    external_progress = progress is not None and progress_task_id is not None
    own_progress = progress is None
    if progress is None:
        progress = ui.progress(show_bytes=show_file_size, show_speed=True)
    task_id = (
        progress_task_id
        if progress_task_id is not None
        else progress.add_task(display_name[:80] if display_name else "download", total=1.0)
    )
    if external_progress:
        progress.reset(task_id, total=1.0, completed=0.0, description=display_name[:80])
    if own_progress:
        progress.start()
    postprocess_cm = None
    postprocess_steps_started: dict[str, float] = {}
    postprocess_steps_done: set[str] = set()
    download_steps_started: dict[str, float] = {}
    download_steps_done: set[str] = set()
    last_update = 0.0

    def _hook(d: dict) -> None:
        nonlocal last_update
        status = d.get("status")
        info = d.get("info_dict") or {}
        step_label = _download_step_label(info)
        if status == "downloading":
            filename = d.get("filename")
            if filename:
                try:
                    name = Path(str(filename)).name
                    if name:
                        progress.update(task_id, description=name[:80])
                except Exception:  # noqa: BLE001
                    pass
            if step_label and step_label not in download_steps_started:
                download_steps_started[step_label] = monotonic()
                _tick(live, status_callback, f"{step_label}: {display_name[:40]}")
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes")
            speed = d.get("speed")
            eta = d.get("eta")
            now = monotonic()
            if downloaded is not None and (now - last_update) > 0.2:
                last_update = now
                if total_bytes:
                    progress.update(task_id, total=float(total_bytes), completed=float(downloaded))
                else:
                    progress.update(task_id, completed=float(downloaded))
                if progress_callback is not None:
                    progress_callback(
                        {
                            "downloaded": downloaded,
                            "total": total_bytes,
                            "speed": speed,
                            "eta": eta,
                        }
                    )
                if live is not None:
                    live.tick()
        elif status == "finished":
            if step_label and step_label not in download_steps_done:
                start = download_steps_started.get(step_label, download_start)
                _record_step(live, step_callback, step_label, True, None, start)
                download_steps_done.add(step_label)
            if progress_callback is not None:
                done_bytes = d.get("downloaded_bytes")
                total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or done_bytes
                progress_callback(
                    {
                        "downloaded": done_bytes,
                        "total": total_bytes,
                        "speed": None,
                        "eta": 0,
                    }
                )
            task_index = progress.task_ids.index(task_id)
            total_now = progress.tasks[task_index].total or 1.0
            progress.update(task_id, total=total_now, completed=total_now)

    def _pp_hook(d: dict) -> None:
        nonlocal postprocess_cm
        status = str(d.get("status") or "").lower()
        name = d.get("postprocessor")
        label = _postprocess_label(name)
        if status == "started":
            if label not in postprocess_steps_started:
                postprocess_steps_started[label] = monotonic()
            if live is not None:
                _tick(live, status_callback, label)
            if show_stage:
                ui.stage("Post-process", label)
            if live is None and ui.level == "normal" and not ui.print_path_only:
                postprocess_cm = ui.spinner("Post-processing…")
                postprocess_cm.__enter__()
        elif status in {"finished", "done"}:
            if postprocess_cm is not None:
                postprocess_cm.__exit__(None, None, None)
                postprocess_cm = None
            if label not in postprocess_steps_done:
                start = postprocess_steps_started.get(label, monotonic())
                _record_step(live, step_callback, label, True, None, start)
                postprocess_steps_done.add(label)

    download_start = monotonic()
    try:
        result = download_with_ytdlp(
            download_url,
            output_plan=output_plan,
            audio=want_audio,
            recode_video=bool(video_override),
            on_progress=_hook,
            on_postprocess=_pp_hook,
            cookies=cookies,
            cookies_from_browser=cookies_from_browser,
            debug=ui.level == "debug",
        )
    except RipmediaError as e:
        _record_step(live, step_callback, "Download", False, str(e), download_start)
        raise
    if not download_steps_done:
        _record_step(live, step_callback, "Download", True, None, download_start)
    if postprocess_cm is not None:
        postprocess_cm.__exit__(None, None, None)
    if own_progress:
        progress.stop()

    if prefer_mp3_mp4 and result.downloaded_path.suffix.lower() == ".mp4":
        optimize_start = monotonic()
        label = "Optimize mp4"
        _tick(live, status_callback, label)
        if show_stage:
            ui.stage("Post-process", label)
        try:
            safe_path = _ensure_playable_mp4(result.downloaded_path)
            if safe_path != result.downloaded_path:
                result = replace(result, downloaded_path=safe_path)
            _record_step(live, step_callback, label, True, None, optimize_start)
        except RipmediaError as e:
            _record_step(live, step_callback, label, False, str(e), optimize_start)
            raise

    if show_stage:
        ui.stage("Tagging", None)
    try:
        tag_start = monotonic()
        _tick(live, status_callback, "Tagging")
        artwork_override = None
        if result.artwork_bytes:
            artwork_override = Artwork(bytes=result.artwork_bytes, mime=result.artwork_mime)
        tag_file(result.downloaded_path, working_item, artwork_override=artwork_override)
        _record_step(live, step_callback, "Tagging", True, None, tag_start)
    except RipmediaError as e:
        ui.verbose(f"Tagging skipped/failed: {e}")
        _record_step(live, step_callback, "Tagging", True, "skipped", tag_start)
    saved_step = StepResult(label="Saved", ok=True, detail=ui.path_link(result.downloaded_path))
    if live is not None:
        live.add_result(saved_step)
    if step_callback is not None:
        step_callback(saved_step)
    return result.downloaded_path


def _record_step(
    live: LiveProgress | None,
    step_callback: Callable[[StepResult], None] | None,
    label: str,
    ok: bool,
    detail: str | None,
    start_time: float,
) -> None:
    duration = monotonic() - start_time
    step = StepResult(label=label, ok=ok, detail=detail, duration_s=duration)
    if live is not None:
        live.add_result(step)
    if step_callback is not None:
        step_callback(step)


def _tick(
    live: LiveProgress | None,
    status_callback: Callable[[str], None] | None,
    label: str,
) -> None:
    if live is not None:
        live.tick(label)
    if status_callback is not None:
        status_callback(label)


def _download_step_label(info: dict) -> str | None:
    vcodec = info.get("vcodec")
    acodec = info.get("acodec")
    if isinstance(vcodec, str) and vcodec != "none" and (not acodec or acodec == "none"):
        return "Video data"
    if isinstance(acodec, str) and acodec != "none" and (not vcodec or vcodec == "none"):
        return "Audio data"
    if isinstance(vcodec, str) and vcodec != "none" and isinstance(acodec, str) and acodec != "none":
        return "Media data"
    return None


def _postprocess_label(name: str | None) -> str:
    if not name:
        return "Post-process"
    lower = name.lower()
    if "merger" in lower or "merge" in lower:
        return "Remux"
    if "extractaudio" in lower or "audioextract" in lower:
        return "Extract audio"
    if "videoconvert" in lower or "convert" in lower:
        return "Convert video"
    if "embedthumbnail" in lower or "thumbnail" in lower:
        return "Embed artwork"
    if "metadata" in lower:
        return "Write metadata"
    if "fixup" in lower:
        return "Fixup stream"
    return _split_camel(name)


def _split_camel(text: str) -> str:
    if not text:
        return text
    out: list[str] = [text[0]]
    for prev, ch in zip(text, text[1:]):
        if ch.isupper() and prev.islower():
            out.append(" ")
        out.append(ch)
    return "".join(out)


def _ensure_playable_mp4(path: Path) -> Path:
    video_codec, audio_codec = _probe_codecs(path)
    needs_transcode = video_codec != "h264" or (audio_codec not in (None, "aac"))
    if needs_transcode:
        return _ffmpeg_transcode_mp4(path)
    return _ffmpeg_faststart(path)


def _probe_codecs(path: Path) -> tuple[str | None, str | None]:
    def _probe(stream: str) -> str | None:
        try:
            proc = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    stream,
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=nk=1:nw=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError:
            return None
        if proc.returncode != 0:
            return None
        value = (proc.stdout or "").strip().splitlines()
        return value[0].strip().lower() if value else None

    return _probe("v:0"), _probe("a:0")


def _ffmpeg_faststart(path: Path) -> Path:
    tmp_path = _temp_sibling(path)
    args = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(tmp_path),
    ]
    _run_ffmpeg(args, stage="Post-process")
    tmp_path.replace(path)
    return path


def _ffmpeg_transcode_mp4(path: Path) -> Path:
    tmp_path = _temp_sibling(path)
    args = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(tmp_path),
    ]
    _run_ffmpeg(args, stage="Post-process")
    tmp_path.replace(path)
    return path


def _run_ffmpeg(args: list[str], *, stage: str) -> None:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as e:
        raise DownloadError("ffmpeg not found. Install ffmpeg and ensure it's on PATH.", stage=stage) from e
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "ffmpeg failed"
        raise DownloadError(f"FFmpeg failed: {stderr}", stage=stage)


def _temp_sibling(path: Path) -> Path:
    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent, suffix=path.suffix) as tmp:
        return Path(tmp.name)


def _fetch_metadata(
    url: str,
    *,
    cookies: Path | None = None,
    cookies_from_browser: str | None = None,
) -> NormalizedItem:
    from .providers.detect import detect_provider
    from .providers.spotify import fetch_spotify_metadata
    from .providers.ytdlp_metadata import fetch_ytdlp_metadata

    provider = detect_provider(url)
    if provider == Provider.SPOTIFY:
        return fetch_spotify_metadata(url)
    return fetch_ytdlp_metadata(
        url,
        provider=provider,
        cookies=cookies,
        cookies_from_browser=cookies_from_browser,
    )
