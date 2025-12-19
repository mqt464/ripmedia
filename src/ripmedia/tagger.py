from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from .errors import TagError
from .model import Attribution, MediaKind, NormalizedItem


@dataclass(frozen=True)
class TagResult:
    artwork_embedded: bool


def tag_file(path: Path, item: NormalizedItem) -> TagResult:
    suffix = path.suffix.lower()
    artwork = _download_artwork(item.artwork_url) if item.artwork_url else None

    if suffix == ".mp3":
        return _tag_mp3(path, item, artwork)
    if suffix in {".m4a", ".mp4"}:
        return _tag_mp4(path, item, artwork)

    raise TagError(f"Tagging not implemented for file type: {suffix}", stage="Tagging")


@dataclass(frozen=True)
class Artwork:
    bytes: bytes
    mime: str


def _download_artwork(url: str) -> Artwork | None:
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "ripmedia/0.1"})
        resp.raise_for_status()
        mime = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        blob = resp.content
        if not mime:
            mime = _sniff_mime(blob) or "image/jpeg"
        return Artwork(bytes=blob, mime=mime)
    except Exception:  # noqa: BLE001
        return None


def _sniff_mime(blob: bytes) -> str | None:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def _attribution_note(attribution: Attribution | None) -> str | None:
    if attribution is None:
        return None
    meta = attribution.metadata_source.value
    media = attribution.media_source.value if attribution.media_source is not None else None
    if media and media != meta:
        return f"Metadata: {meta}, Media source: {media}"
    return f"Metadata: {meta}"


def _album_title(item: NormalizedItem) -> str | None:
    if item.album:
        return item.album
    if item.kind == MediaKind.TRACK and item.title:
        return item.title
    return None


def _album_artist(item: NormalizedItem) -> str | None:
    return item.artist


def _tag_mp3(path: Path, item: NormalizedItem, artwork: Artwork | None) -> TagResult:
    try:
        from mutagen.id3 import (
            APIC,
            COMM,
            ID3,
            ID3NoHeaderError,
            TALB,
            TDRC,
            TIT2,
            TPE1,
            TPE2,
            TPOS,
            TRCK,
        )
        from mutagen.mp3 import MP3

        audio = MP3(path)
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

        if item.title:
            tags.setall("TIT2", [TIT2(encoding=3, text=item.title)])
        if item.artist:
            tags.setall("TPE1", [TPE1(encoding=3, text=item.artist)])
        album_title = _album_title(item)
        if album_title:
            tags.setall("TALB", [TALB(encoding=3, text=album_title)])
        album_artist = _album_artist(item)
        if album_artist:
            tags.setall("TPE2", [TPE2(encoding=3, text=album_artist)])
        if item.track_number is not None:
            tags.setall("TRCK", [TRCK(encoding=3, text=str(item.track_number))])
        if item.disc_number is not None:
            tags.setall("TPOS", [TPOS(encoding=3, text=str(item.disc_number))])
        if item.year is not None:
            tags.setall("TDRC", [TDRC(encoding=3, text=str(item.year))])

        note = _attribution_note(item.attribution)
        if note:
            tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="ripmedia", text=note)])

        artwork_embedded = False
        if artwork:
            tags.setall(
                "APIC",
                [
                    APIC(
                        encoding=3,
                        mime=artwork.mime,
                        type=3,
                        desc="Cover",
                        data=artwork.bytes,
                    )
                ],
            )
            artwork_embedded = True

        tags.save(path)
        audio.save()
        return TagResult(artwork_embedded=artwork_embedded)
    except Exception as e:  # noqa: BLE001
        raise TagError(f"Failed to tag mp3: {e}", stage="Tagging") from e


def _tag_mp4(path: Path, item: NormalizedItem, artwork: Artwork | None) -> TagResult:
    try:
        from mutagen.mp4 import MP4, MP4Cover

        mp4 = MP4(path)
        if item.title:
            mp4["\xa9nam"] = [item.title]
        if item.artist:
            mp4["\xa9ART"] = [item.artist]
        album_title = _album_title(item)
        if album_title:
            mp4["\xa9alb"] = [album_title]
        album_artist = _album_artist(item)
        if album_artist:
            mp4["aART"] = [album_artist]
        if item.track_number is not None:
            mp4["trkn"] = [(item.track_number, 0)]
        if item.disc_number is not None:
            mp4["disk"] = [(item.disc_number, 0)]
        if item.year is not None:
            mp4["\xa9day"] = [str(item.year)]

        note = _attribution_note(item.attribution)
        if note:
            mp4["\xa9cmt"] = [note]

        artwork_embedded = False
        if artwork:
            fmt = MP4Cover.FORMAT_PNG if artwork.mime == "image/png" else MP4Cover.FORMAT_JPEG
            mp4["covr"] = [MP4Cover(artwork.bytes, imageformat=fmt)]
            artwork_embedded = True

        mp4.save()
        return TagResult(artwork_embedded=artwork_embedded)
    except Exception as e:  # noqa: BLE001
        raise TagError(f"Failed to tag mp4/m4a: {e}", stage="Tagging") from e
