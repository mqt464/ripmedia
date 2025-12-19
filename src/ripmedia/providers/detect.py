from __future__ import annotations

from urllib.parse import urlparse

from ..model import Provider


def detect_provider(url: str) -> Provider:
    host = (urlparse(url).hostname or "").lower()
    if host in {
        "youtu.be",
        "www.youtube.com",
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }:
        return Provider.YOUTUBE
    if host in {
        "soundcloud.com",
        "www.soundcloud.com",
        "m.soundcloud.com",
        "on.soundcloud.com",
    }:
        return Provider.SOUNDCLOUD
    if host in {"open.spotify.com"}:
        return Provider.SPOTIFY
    return Provider.UNKNOWN
