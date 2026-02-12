from __future__ import annotations

from typing import Any

from yt_dlp import YoutubeDL

from pathlib import Path

from ..errors import MetadataError
from ..model import MediaKind, NormalizedItem, Provider
from ..ytdlp_utils import normalize_cookies_from_browser


class _NoopLogger:
    def debug(self, msg: str) -> None:  # noqa: D401
        pass

    def warning(self, msg: str) -> None:  # noqa: D401
        pass

    def error(self, msg: str) -> None:  # noqa: D401
        pass


def fetch_ytdlp_metadata(
    url: str,
    *,
    provider: Provider,
    cookies: Path | None = None,
    cookies_from_browser: str | None = None,
) -> NormalizedItem:
    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": False,
            "no_warnings": True,
            "logger": _NoopLogger(),
        }
        if cookies is not None:
            ydl_opts["cookiefile"] = str(cookies)
        else:
            cookies_spec = normalize_cookies_from_browser(cookies_from_browser)
            if cookies_spec:
                ydl_opts["cookiesfrombrowser"] = cookies_spec

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        raise MetadataError(f"Failed to fetch metadata via yt-dlp: {e}", stage="Metadata") from e

    if not isinstance(info, dict):
        raise MetadataError("Unexpected yt-dlp metadata response.", stage="Metadata")

    kind = _guess_kind(info)
    title = info.get("title")
    duration = info.get("duration")
    thumbnail = _pick_thumbnail(info)

    artist = info.get("artist") or info.get("uploader") or info.get("channel")
    album = info.get("album")
    track_number = info.get("track_number")
    release_year = info.get("release_year")
    upload_date = info.get("upload_date")

    entries = _extract_entries(provider, info) if kind == MediaKind.PLAYLIST else None
    return NormalizedItem(
        provider=provider,
        kind=kind,
        id=info.get("id"),
        url=url,
        title=title,
        artist=artist,
        album=album,
        track_number=track_number,
        year=release_year,
        date=upload_date,
        duration_seconds=duration,
        artwork_url=thumbnail,
        entries=entries,
        extra={"ytdlp": _minimize_info(info)},
    )


def _guess_kind(info: dict[str, Any]) -> MediaKind:
    if info.get("_type") == "playlist":
        return MediaKind.PLAYLIST
    if info.get("ie_key") == "YoutubeTab":
        return MediaKind.PLAYLIST
    vcodec = info.get("vcodec")
    if vcodec and str(vcodec).lower() != "none":
        return MediaKind.VIDEO
    return MediaKind.TRACK


def _minimize_info(info: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "id",
        "title",
        "duration",
        "webpage_url",
        "extractor",
        "extractor_key",
        "uploader",
        "channel",
        "artist",
        "album",
        "track_number",
        "release_year",
        "upload_date",
        "thumbnail",
    }
    return {k: info.get(k) for k in keep if k in info}


def _pick_thumbnail(info: dict[str, Any]) -> str | None:
    thumb = info.get("thumbnail")
    if thumb:
        return str(thumb)
    thumbs = info.get("thumbnails")
    if not isinstance(thumbs, list):
        return None
    for t in reversed(thumbs):
        if isinstance(t, dict) and t.get("url"):
            return str(t["url"])
    return None


def _extract_entries(provider: Provider, info: dict[str, Any]) -> list[NormalizedItem] | None:
    raw_entries = info.get("entries") or []
    if not isinstance(raw_entries, list) or not raw_entries:
        return None
    entries: list[NormalizedItem] = []
    for idx, e in enumerate(raw_entries, start=1):
        if not isinstance(e, dict):
            continue
        entry_url = e.get("webpage_url") or e.get("url")
        if not entry_url:
            continue
        entries.append(
            NormalizedItem(
                provider=provider,
                kind=MediaKind.VIDEO,
                id=e.get("id"),
                url=str(entry_url),
                title=e.get("title"),
                track_number=e.get("playlist_index") or idx,
                artwork_url=e.get("thumbnail"),
            )
        )
    return entries or None
