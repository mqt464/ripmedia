from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Literal


class Provider(str, Enum):
    YOUTUBE = "youtube"
    SOUNDCLOUD = "soundcloud"
    SPOTIFY = "spotify"
    UNKNOWN = "unknown"


class MediaKind(str, Enum):
    TRACK = "track"
    VIDEO = "video"
    ALBUM = "album"
    PLAYLIST = "playlist"


@dataclass(frozen=True)
class Attribution:
    metadata_source: Provider
    media_source: Provider | None = None


@dataclass(frozen=True)
class NormalizedItem:
    provider: Provider
    kind: MediaKind
    id: str | None
    url: str
    title: str | None = None

    artist: str | None = None
    album: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    date: str | None = None
    duration_seconds: int | None = None

    artwork_url: str | None = None
    attribution: Attribution | None = None

    entries: list["NormalizedItem"] | None = None
    extra: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["provider"] = self.provider.value
        d["kind"] = self.kind.value
        if self.attribution is not None:
            d["attribution"] = {
                "metadata_source": self.attribution.metadata_source.value,
                "media_source": self.attribution.media_source.value
                if self.attribution.media_source is not None
                else None,
            }
        if self.entries is not None:
            d["entries"] = [e.to_json() for e in self.entries]
        return d


JsonDict = dict[str, Any]
LogLevel = Literal["quiet", "normal", "verbose", "debug"]
