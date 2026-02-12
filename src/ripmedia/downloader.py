from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yt_dlp import YoutubeDL

from .errors import DownloadError
from .paths import OutputPlan, ensure_unique_path
from .ytdlp_utils import normalize_cookies_from_browser

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".heic"}


@dataclass(frozen=True)
class DownloadResult:
    downloaded_path: Path
    info: dict[str, Any]
    artwork_bytes: bytes | None = None
    artwork_mime: str | None = None


class _NoopLogger:
    def debug(self, msg: str) -> None:  # noqa: D401
        pass

    def warning(self, msg: str) -> None:  # noqa: D401
        pass

    def error(self, msg: str) -> None:  # noqa: D401
        pass


def download_with_ytdlp(
    url: str,
    *,
    output_plan: OutputPlan,
    audio: bool,
    recode_video: bool = False,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_postprocess: Callable[[dict[str, Any]], None] | None = None,
    cookies: Path | None = None,
    cookies_from_browser: str | None = None,
    debug: bool = False,
) -> DownloadResult:
    output_plan.directory.mkdir(parents=True, exist_ok=True)

    final_path = ensure_unique_path(output_plan.final_path)
    with tempfile.TemporaryDirectory(prefix="ripmedia-") as tmp:
        tmp_dir = Path(tmp)
        outtmpl = str(tmp_dir / "%(id)s.%(ext)s")

        ydl_opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "noplaylist": False,
            "quiet": not debug,
            "no_warnings": not debug,
            "progress_hooks": [on_progress] if on_progress else [],
            "postprocessor_hooks": [on_postprocess] if on_postprocess else [],
            "logger": None if debug else _NoopLogger(),
            "writethumbnail": True,
        }
        if cookies is not None:
            ydl_opts["cookiefile"] = str(cookies)
        else:
            cookies_spec = normalize_cookies_from_browser(cookies_from_browser)
            if cookies_spec:
                ydl_opts["cookiesfrombrowser"] = cookies_spec

        if audio:
            # Prefer stable container. yt-dlp will still select whatever stream is best, but
            # extraction ensures the final artifact matches our expected extension.
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": final_path.suffix.lstrip(".")}
            ]
        else:
            out_ext = final_path.suffix.lstrip(".").lower()
            if recode_video:
                ydl_opts["format"] = "bestvideo*+bestaudio/best"
                ydl_opts["postprocessors"] = [
                    {"key": "FFmpegVideoConvertor", "preferedformat": out_ext}
                ]
            else:
                if out_ext == "mp4":
                    # Ensure we pick mux-compatible streams (avoid webm/opus -> mp4 mux failures).
                    ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
                else:
                    ydl_opts["format"] = "bestvideo*+bestaudio/best"
                ydl_opts["merge_output_format"] = out_ext

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as e:  # noqa: BLE001
            raise DownloadError(f"yt-dlp failed: {_clean_ytdlp_error(e)}", stage="Downloading") from e

        downloaded = _select_downloaded_media(info, tmp_dir)
        if downloaded is None:
            raise DownloadError("yt-dlp completed but no output file was found.", stage="Downloading")

        artwork_bytes, artwork_mime = _load_thumbnail_bytes(tmp_dir)

        try:
            shutil.move(str(downloaded), str(final_path))
        except Exception as e:  # noqa: BLE001
            raise DownloadError(f"Failed to move output file into place: {e}", stage="Saved") from e

        return DownloadResult(
            downloaded_path=final_path,
            info=info if isinstance(info, dict) else {},
            artwork_bytes=artwork_bytes,
            artwork_mime=artwork_mime,
        )


def _select_downloaded_media(info: dict[str, Any] | None, tmp_dir: Path) -> Path | None:
    paths: list[Path] = []
    if isinstance(info, dict):
        requested = info.get("requested_downloads")
        if isinstance(requested, list):
            for entry in requested:
                if not isinstance(entry, dict):
                    continue
                raw = entry.get("filepath") or entry.get("filename")
                if raw:
                    paths.append(Path(str(raw)))
        for key in ("filepath", "_filename", "filename"):
            raw = info.get(key)
            if raw:
                paths.append(Path(str(raw)))

    for p in paths:
        candidate = p if p.is_absolute() else (tmp_dir / p)
        if candidate.exists() and _is_media_file(candidate):
            return candidate

    return _find_latest_media_file(tmp_dir)


def _find_latest_media_file(tmp_dir: Path) -> Path | None:
    candidates = [p for p in tmp_dir.glob("*") if p.is_file() and _is_media_file(p)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _load_thumbnail_bytes(tmp_dir: Path) -> tuple[bytes | None, str | None]:
    candidates = [p for p in tmp_dir.glob("*") if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    if not candidates:
        return None, None
    best = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        blob = best.read_bytes()
    except Exception:  # noqa: BLE001
        return None, None
    mime = _sniff_image_mime(blob) or _mime_from_ext(best.suffix)
    return blob, mime


def _mime_from_ext(ext: str) -> str | None:
    ext = ext.lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".avif": "image/avif",
        ".heic": "image/heic",
    }
    return mapping.get(ext)


def _is_media_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTS:
        return False
    return suffix != ".part"


def _clean_ytdlp_error(err: Exception) -> str:
    text = str(err).strip()
    if "HTTP Error" in text:
        idx = text.find("HTTP Error")
        return text[idx:]
    if "ERROR:" in text:
        return text.replace("ERROR:", "").strip()
    return text


def _sniff_image_mime(blob: bytes) -> str | None:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return "image/gif"
    return None
