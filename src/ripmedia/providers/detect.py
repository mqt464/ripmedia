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
    if host in {
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "vxtwitter.com",
        "www.vxtwitter.com",
        "fxtwitter.com",
        "www.fxtwitter.com",
    }:
        return Provider.TWITTER
    if host in {"pornhub.com", "www.pornhub.com", "m.pornhub.com"}:
        return Provider.PORNHUB
    return Provider.UNKNOWN
