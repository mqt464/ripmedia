from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from ..errors import MetadataError
from ..model import Attribution, MediaKind, NormalizedItem, Provider


@dataclass(frozen=True)
class SpotifyRef:
    kind: MediaKind
    id: str
    url: str


def parse_spotify_url(url: str) -> SpotifyRef:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise MetadataError("Unrecognized Spotify URL.", stage="Detected")
    kind_s, id_s = parts[0], parts[1]
    kind_map = {"track": MediaKind.TRACK, "album": MediaKind.ALBUM, "playlist": MediaKind.PLAYLIST}
    if kind_s not in kind_map:
        raise MetadataError(f"Unsupported Spotify type: {kind_s}", stage="Detected")
    return SpotifyRef(kind=kind_map[kind_s], id=id_s, url=url)


def fetch_spotify_metadata(url: str) -> NormalizedItem:
    ref = parse_spotify_url(url)
    item = _fetch_via_spotipy(ref)
    if item is not None:
        return item
    if ref.kind in (MediaKind.ALBUM, MediaKind.PLAYLIST):
        raise MetadataError(
            "Spotify album/playlist expansion requires API credentials. Set SPOTIFY_CLIENT_ID and "
            "SPOTIFY_CLIENT_SECRET.",
            stage="Metadata",
        )
    return _fetch_via_oembed(ref)


def _fetch_via_spotipy(ref: SpotifyRef) -> NormalizedItem | None:
    try:
        import os

        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None

        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials

        sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
        )

        if ref.kind == MediaKind.TRACK:
            data = sp.track(ref.id)
            album = data.get("album") or {}
            artists = data.get("artists") or []
            artist = (artists[0].get("name") if artists else None) or None
            images = (album.get("images") or []) if isinstance(album, dict) else []
            artwork = images[0]["url"] if images else None
            release_date = (album.get("release_date") if isinstance(album, dict) else None) or None
            year = int(release_date.split("-")[0]) if release_date else None
            duration_ms = data.get("duration_ms")
            isrc = ((data.get("external_ids") or {}).get("isrc")) if isinstance(data, dict) else None
            return NormalizedItem(
                provider=Provider.SPOTIFY,
                kind=MediaKind.TRACK,
                id=ref.id,
                url=ref.url,
                title=data.get("name"),
                artist=artist,
                album=(album.get("name") if isinstance(album, dict) else None),
                track_number=data.get("track_number"),
                disc_number=data.get("disc_number"),
                year=year,
                date=release_date,
                duration_seconds=int(duration_ms / 1000) if duration_ms else None,
                artwork_url=artwork,
                attribution=Attribution(metadata_source=Provider.SPOTIFY),
                extra={"spotify": {"isrc": isrc}},
            )

        if ref.kind == MediaKind.ALBUM:
            return _fetch_album(sp, ref)
        if ref.kind == MediaKind.PLAYLIST:
            return _fetch_playlist(sp, ref)
    except Exception:  # noqa: BLE001
        return None

    return None


def _fetch_album(sp: Any, ref: SpotifyRef) -> NormalizedItem:
    data = sp.album(ref.id)
    title = data.get("name")
    artists = data.get("artists") or []
    artist = (artists[0].get("name") if artists else None) or None
    images = data.get("images") or []
    artwork = images[0]["url"] if images else None
    release_date = data.get("release_date")
    year = int(release_date.split("-")[0]) if release_date else None

    tracks: list[NormalizedItem] = []
    page = sp.album_tracks(ref.id, limit=50, offset=0)
    while True:
        for t in page.get("items") or []:
            if not isinstance(t, dict):
                continue
            tid = t.get("id")
            if not tid:
                continue
            t_artists = t.get("artists") or []
            t_artist = (t_artists[0].get("name") if t_artists else None) or artist
            duration_ms = t.get("duration_ms")
            track_url = f"https://open.spotify.com/track/{tid}"
            tracks.append(
                NormalizedItem(
                    provider=Provider.SPOTIFY,
                    kind=MediaKind.TRACK,
                    id=tid,
                    url=track_url,
                    title=t.get("name"),
                    artist=t_artist,
                    album=title,
                    track_number=t.get("track_number"),
                    disc_number=t.get("disc_number"),
                    year=year,
                    date=release_date,
                    duration_seconds=int(duration_ms / 1000) if duration_ms else None,
                    artwork_url=artwork,
                    attribution=Attribution(metadata_source=Provider.SPOTIFY),
                )
            )
        next_url = page.get("next")
        if not next_url:
            break
        page = sp.next(page)

    return NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.ALBUM,
        id=ref.id,
        url=ref.url,
        title=title,
        artist=artist,
        album=title,
        year=year,
        date=release_date,
        artwork_url=artwork,
        attribution=Attribution(metadata_source=Provider.SPOTIFY),
        entries=tracks,
        extra={"spotify": {"total_tracks": len(tracks)}},
    )


def _fetch_playlist(sp: Any, ref: SpotifyRef) -> NormalizedItem:
    data = sp.playlist(ref.id)
    title = data.get("name")
    images = data.get("images") or []
    artwork = images[0]["url"] if images else None

    tracks: list[NormalizedItem] = []
    page = sp.playlist_items(ref.id, limit=100, offset=0, additional_types=("track",))
    index = 0
    while True:
        for it in page.get("items") or []:
            track = (it or {}).get("track") if isinstance(it, dict) else None
            if not isinstance(track, dict):
                continue
            tid = track.get("id")
            if not tid:
                continue
            index += 1
            t_artists = track.get("artists") or []
            artist = (t_artists[0].get("name") if t_artists else None) or None
            album = track.get("album") or {}
            album_name = album.get("name") if isinstance(album, dict) else None
            release_date = album.get("release_date") if isinstance(album, dict) else None
            year = int(release_date.split("-")[0]) if release_date else None
            duration_ms = track.get("duration_ms")
            images = album.get("images") if isinstance(album, dict) else None
            t_artwork = (images[0]["url"] if images else None) or artwork
            isrc = ((track.get("external_ids") or {}).get("isrc")) if isinstance(track, dict) else None
            track_url = f"https://open.spotify.com/track/{tid}"
            tracks.append(
                NormalizedItem(
                    provider=Provider.SPOTIFY,
                    kind=MediaKind.TRACK,
                    id=tid,
                    url=track_url,
                    title=track.get("name"),
                    artist=artist,
                    album=album_name,
                    track_number=track.get("track_number"),
                    disc_number=track.get("disc_number"),
                    year=year,
                    date=release_date,
                    duration_seconds=int(duration_ms / 1000) if duration_ms else None,
                    artwork_url=t_artwork,
                    attribution=Attribution(metadata_source=Provider.SPOTIFY),
                    extra={"spotify": {"isrc": isrc}, "playlist_index": index},
                )
            )
        next_url = page.get("next")
        if not next_url:
            break
        page = sp.next(page)

    return NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.PLAYLIST,
        id=ref.id,
        url=ref.url,
        title=title,
        artwork_url=artwork,
        attribution=Attribution(metadata_source=Provider.SPOTIFY),
        entries=tracks,
        extra={"spotify": {"total_tracks": len(tracks)}},
    )


def _fetch_via_oembed(ref: SpotifyRef) -> NormalizedItem:
    try:
        resp = requests.get(
            "https://open.spotify.com/oembed",
            params={"url": ref.url},
            timeout=15,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except Exception as e:  # noqa: BLE001
        raise MetadataError(
            "Spotify metadata requires credentials (SPOTIFY_CLIENT_ID/SECRET) or oEmbed access.",
            stage="Metadata",
        ) from e

    title = data.get("title")
    author = data.get("author_name")
    thumbnail = data.get("thumbnail_url")
    return NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=ref.kind,
        id=ref.id,
        url=ref.url,
        title=title,
        artist=author,
        artwork_url=thumbnail,
        attribution=Attribution(metadata_source=Provider.SPOTIFY),
        extra={"spotify_oembed": data},
    )
