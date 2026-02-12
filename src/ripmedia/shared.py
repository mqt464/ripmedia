from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .ytdlp_utils import normalize_cookies_from_browser


class NoopLogger:
    def debug(self, msg: str) -> None:  # noqa: D401
        pass

    def warning(self, msg: str) -> None:  # noqa: D401
        pass

    def error(self, msg: str) -> None:  # noqa: D401
        pass


def apply_cookie_options(
    ydl_opts: dict[str, Any],
    *,
    cookies: Path | None,
    cookies_from_browser: str | None,
) -> None:
    if cookies is not None:
        ydl_opts["cookiefile"] = str(cookies)
        return
    cookies_spec = normalize_cookies_from_browser(cookies_from_browser)
    if cookies_spec:
        ydl_opts["cookiesfrombrowser"] = cookies_spec


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    if total < 0:
        total = 0
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_speed(speed_bps: float, unit: str) -> str:
    if unit == "Mbps":
        value = (float(speed_bps) * 8) / 1_000_000
        suffix = "Mb/s"
    else:
        value = float(speed_bps) / 1_000_000
        suffix = "MB/s"
    return f"{value:>5.1f} {suffix}"


def sniff_image_mime(blob: bytes) -> str | None:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return "image/gif"
    return None


def image_mime_from_ext(ext: str) -> str | None:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".avif": "image/avif",
        ".heic": "image/heic",
    }.get(ext.lower())


def image_ext_from_mime(mime: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/heic": ".heic",
    }.get(mime, ".img")


def open_with_default_app(path: Path, *, reveal_parent: bool = False) -> None:
    target = path
    if reveal_parent:
        target = path if path.is_dir() else path.parent

    if sys.platform.startswith("win"):
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)
