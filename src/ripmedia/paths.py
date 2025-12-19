from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import MediaKind, NormalizedItem


_ILLEGAL_WINDOWS = re.compile(r'[<>:"/\\\\|?*]')
_CONTROL = re.compile(r"[\x00-\x1f]")


def sanitize_path_segment(value: str, *, replacement: str = "_") -> str:
    value = value.strip()
    value = _CONTROL.sub(replacement, value)
    value = _ILLEGAL_WINDOWS.sub(replacement, value)
    value = value.rstrip(" .")
    value = re.sub(r"\s+", " ", value).strip()
    return value or "unknown"


@dataclass(frozen=True)
class OutputPlan:
    directory: Path
    filename_stem: str
    extension: str

    @property
    def final_path(self) -> Path:
        return self.directory / f"{self.filename_stem}{self.extension}"


def build_output_plan(item: NormalizedItem, *, output_dir: Path, extension: str) -> OutputPlan:
    title = sanitize_path_segment(item.title) if item.title else "unknown"

    directory = output_dir
    track_prefix = ""
    if item.track_number is not None:
        track_prefix = f"{item.track_number:02d} - "

    if item.kind == MediaKind.TRACK and item.artist and item.title:
        filename = f"{item.artist} - {item.title}"
    else:
        filename = title

    filename_stem = sanitize_path_segment(filename)
    if not extension.startswith("."):
        extension = "." + extension
    return OutputPlan(directory=directory, filename_stem=filename_stem, extension=extension)


def collection_directory(item: NormalizedItem, *, output_dir: Path) -> Path:
    if item.kind == MediaKind.ALBUM:
        folder = item.album or item.title
        return output_dir / sanitize_path_segment(folder) if folder else output_dir / "unknown album"
    if item.kind == MediaKind.PLAYLIST:
        folder = item.title
        return output_dir / sanitize_path_segment(folder) if folder else output_dir / "unknown playlist"
    return output_dir


def build_collection_item_plan(
    item: NormalizedItem, *, output_dir: Path, extension: str, track_number: int | None
) -> OutputPlan:
    title = sanitize_path_segment(item.title) if item.title else "unknown"
    directory = output_dir
    prefix = f"{track_number:02d} - " if track_number is not None else ""
    filename_stem = sanitize_path_segment(f"{prefix}{title}")
    if not extension.startswith("."):
        extension = "." + extension
    return OutputPlan(directory=directory, filename_stem=filename_stem, extension=extension)


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for i in range(1, 10_000):
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find available filename for: {path}")
