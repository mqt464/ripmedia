from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import monotonic

from .downloader import download_with_ytdlp
from .errors import MetadataError, PartialSuccessError, RipmediaError
from .model import Attribution, MediaKind, NormalizedItem, Provider
from .paths import build_collection_item_plan, build_output_plan, collection_directory
from .resolver import resolve_candidates
from .tagger import Artwork, tag_file
from .ui import Ui


def run_info(url: str, *, ui: Ui) -> NormalizedItem:
    _ = ui
    return _fetch_metadata(url)

def _default_extension(item: NormalizedItem, *, audio: bool) -> str:
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
) -> list[Path]:
    item = _fetch_metadata(url)
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
    )
    ui.stage("Saved", str(path))
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
        if ui.level != "quiet" and not ui.print_path_only:
            ui.info(f"[dim]{idx}/{total}[/dim] {title}")
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
            )
            saved.append(saved_path)
        except RipmediaError as e:
            failures.append((entry.url, str(e), e.stage))
            continue
        except Exception as e:  # noqa: BLE001
            failures.append((entry.url, str(e), None))
            continue

    ui.stage("Saved", str(folder))
    if failures and saved:
        raise PartialSuccessError(
            f"{len(failures)}/{total} items failed",
            stage="Downloading",
            saved_paths=saved,
            failures=failures,
        )
    if failures and not saved:
        raise MetadataError("All items in the collection failed.", stage="Downloading")
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
) -> Path:
    download_url = item.url
    working_item = item
    if item.provider == Provider.SPOTIFY and item.kind == MediaKind.TRACK:
        resolver_name = resolver.strip().lower()
        preferred = Provider.SOUNDCLOUD if resolver_name == "soundcloud" else Provider.YOUTUBE

        candidates = resolve_candidates(item, preferred=preferred, limit=5)
        if not candidates:
            raise MetadataError("No resolver candidates found.", stage="Resolve")

        best = candidates[0]
        hint = f" ({best.confidence_hint})" if best.confidence_hint else ""
        ui.stage("Resolve", f"spotify → {best.provider.value}…{hint}")

        if best.confidence < 0.6 and not interactive:
            raise MetadataError(
                "Low confidence match. Re-run with `--interactive` to choose a candidate, or "
                "try `--resolver soundcloud`.",
                stage="Resolve",
            )

        selected = best
        if interactive:
            if ui.level == "quiet" or ui.print_path_only:
                raise MetadataError("Interactive mode is not available with --quiet/--print-path.", stage="Resolve")
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
                    raise MetadataError("Invalid selection.", stage="Resolve") from e
                if idx < 1 or idx > len(candidates):
                    raise MetadataError("Selection out of range.", stage="Resolve")
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

    want_audio = _should_download_audio(working_item, audio_flag=audio)
    audio_override = _normalize_override(override_audio_format) if want_audio else None
    video_override = _normalize_override(override_video_format) if not want_audio else None
    ext = audio_override or video_override or _default_extension(working_item, audio=want_audio)
    if in_collection:
        output_plan = build_collection_item_plan(
            working_item, output_dir=output_dir, extension=ext, track_number=working_item.track_number
        )
    else:
        output_plan = build_output_plan(working_item, output_dir=output_dir, extension=ext)

    display_name = (
        f"{working_item.artist} - {working_item.title}"
        if working_item.artist and working_item.title
        else (working_item.title or working_item.url)
    )
    ui.stage("Downloading", display_name)
    with ui.progress() as progress:
        task_id = progress.add_task(display_name[:80] if display_name else "download", total=1.0)
        postprocess_cm = None
        postprocess_started = False
        last_update = 0.0

        def _hook(d: dict) -> None:
            nonlocal last_update
            status = d.get("status")
            if status == "downloading":
                filename = d.get("filename")
                if filename:
                    try:
                        name = Path(str(filename)).name
                        if name:
                            progress.update(task_id, description=name[:80])
                    except Exception:  # noqa: BLE001
                        pass
                total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes")
                now = monotonic()
                if total_bytes and downloaded and (now - last_update) > 0.2:
                    last_update = now
                    progress.update(task_id, total=float(total_bytes), completed=float(downloaded))
            elif status == "finished":
                total_now = progress.tasks[0].total or 1.0
                progress.update(task_id, total=total_now, completed=total_now)

        def _pp_hook(d: dict) -> None:
            nonlocal postprocess_cm, postprocess_started
            status = str(d.get("status") or "").lower()
            if status == "started" and not postprocess_started:
                postprocess_started = True
                name = d.get("postprocessor")
                detail = f"{name}…" if name else "ffmpeg…"
                ui.stage("Post-process", detail)
                if ui.level == "normal" and not ui.print_path_only:
                    postprocess_cm = ui.spinner("Post-processing…")
                    postprocess_cm.__enter__()
            elif status in {"finished", "done"}:
                if postprocess_cm is not None:
                    postprocess_cm.__exit__(None, None, None)
                    postprocess_cm = None

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
        if postprocess_cm is not None:
            postprocess_cm.__exit__(None, None, None)

    ui.stage("Tagging", None)
    try:
        artwork_override = None
        if result.artwork_bytes:
            artwork_override = Artwork(bytes=result.artwork_bytes, mime=result.artwork_mime)
        tag_file(result.downloaded_path, working_item, artwork_override=artwork_override)
    except RipmediaError as e:
        ui.verbose(f"Tagging skipped/failed: {e}")
    return result.downloaded_path


def _fetch_metadata(url: str) -> NormalizedItem:
    from .providers.detect import detect_provider
    from .providers.spotify import fetch_spotify_metadata
    from .providers.ytdlp_metadata import fetch_ytdlp_metadata

    provider = detect_provider(url)
    if provider == Provider.SPOTIFY:
        return fetch_spotify_metadata(url)
    if provider in (Provider.YOUTUBE, Provider.SOUNDCLOUD):
        return fetch_ytdlp_metadata(url, provider=provider)
    raise MetadataError("Unsupported/unknown provider URL.", stage="Detected")
