from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile

import requests

from .errors import TagError
from .model import Attribution, NormalizedItem


@dataclass(frozen=True)
class TagResult:
    artwork_embedded: bool


def tag_file(
    path: Path,
    item: NormalizedItem,
    *,
    artwork_override: Artwork | None = None,
) -> TagResult:
    suffix = path.suffix.lower()
    if artwork_override is not None:
        artwork = artwork_override
    else:
        artwork = _download_artwork(item.artwork_url, referer=item.url) if item.artwork_url else None

    if suffix == ".mp3":
        return _tag_mp3(path, item, artwork)
    if suffix in {".m4a", ".mp4"}:
        return _tag_mp4(path, item, artwork)

    return _tag_with_ffmpeg(path, item)


@dataclass(frozen=True)
class Artwork:
    bytes: bytes
    mime: str | None


def _download_artwork(url: str, *, referer: str | None = None) -> Artwork | None:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        if referer:
            headers["Referer"] = referer
        resp = requests.get(url, timeout=20, headers=headers)
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
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return "image/gif"
    return None


def _mime_extension(mime: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/heic": ".heic",
    }
    return mapping.get(mime, ".img")


def _coerce_artwork(artwork: Artwork) -> Artwork:
    mime = artwork.mime or _sniff_mime(artwork.bytes) or "image/jpeg"
    return Artwork(bytes=artwork.bytes, mime=mime)


def _convert_artwork_to_jpeg(artwork: Artwork) -> Artwork | None:
    input_ext = _mime_extension(artwork.mime)
    with tempfile.NamedTemporaryFile(delete=False, suffix=input_ext) as tmp_in:
        tmp_in.write(artwork.bytes)
        in_path = Path(tmp_in.name)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_out:
        out_path = Path(tmp_out.name)
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                    "-i",
                    str(in_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(out_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or not out_path.exists():
            return None
        data = out_path.read_bytes()
        return Artwork(bytes=data, mime="image/jpeg")
    except Exception:  # noqa: BLE001
        return None
    finally:
        for p in (in_path, out_path):
            if p.exists():
                try:
                    p.unlink()
                except Exception:  # noqa: BLE001
                    pass


def _prepare_artwork(artwork: Artwork | None, *, target: str) -> Artwork | None:
    if artwork is None:
        return None
    artwork = _coerce_artwork(artwork)
    if target == "mp4":
        if artwork.mime in {"image/jpeg", "image/png"}:
            return artwork
        return _convert_artwork_to_jpeg(artwork)
    if artwork.mime in {"image/jpeg", "image/png"}:
        return artwork
    converted = _convert_artwork_to_jpeg(artwork)
    return converted or artwork


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
    if item.title:
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

        artwork = _prepare_artwork(artwork, target="mp3")
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

        tags.save(path, v2_version=3)
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

        artwork = _prepare_artwork(artwork, target="mp4")
        artwork_embedded = False
        if artwork:
            fmt = MP4Cover.FORMAT_PNG if artwork.mime == "image/png" else MP4Cover.FORMAT_JPEG
            mp4["covr"] = [MP4Cover(artwork.bytes, imageformat=fmt)]
            artwork_embedded = True

        mp4.save()
        return TagResult(artwork_embedded=artwork_embedded)
    except Exception as e:  # noqa: BLE001
        raise TagError(f"Failed to tag mp4/m4a: {e}", stage="Tagging") from e


def _tag_with_ffmpeg(path: Path, item: NormalizedItem) -> TagResult:
    metadata: list[tuple[str, str]] = []
    if item.title:
        metadata.append(("title", item.title))
    if item.artist:
        metadata.append(("artist", item.artist))
    album_title = _album_title(item)
    if album_title:
        metadata.append(("album", album_title))
    album_artist = _album_artist(item)
    if album_artist:
        metadata.append(("album_artist", album_artist))
    if item.track_number is not None:
        metadata.append(("track", str(item.track_number)))
    if item.disc_number is not None:
        metadata.append(("disc", str(item.disc_number)))
    if item.year is not None:
        metadata.append(("date", str(item.year)))

    if not metadata:
        return TagResult(artwork_embedded=False)

    args = ["ffmpeg", "-y", "-i", str(path), "-map", "0", "-c", "copy"]
    for key, value in metadata:
        args.extend(["-metadata", f"{key}={value}"])

    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent, suffix=path.suffix) as tmp:
        tmp_path = Path(tmp.name)
    try:
        try:
            proc = subprocess.run(
                args + [str(tmp_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as e:
            raise TagError("ffmpeg not found. Install ffmpeg and ensure it's on PATH.", stage="Tagging") from e
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or "ffmpeg failed"
            raise TagError(f"Failed to tag via ffmpeg: {stderr}", stage="Tagging")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:  # noqa: BLE001
                pass
    return TagResult(artwork_embedded=False)
