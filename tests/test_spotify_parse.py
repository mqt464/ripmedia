from ripmedia.model import MediaKind
from ripmedia.providers.spotify import parse_spotify_url


def test_parse_spotify_track() -> None:
    ref = parse_spotify_url("https://open.spotify.com/track/abc123")
    assert ref.kind == MediaKind.TRACK
    assert ref.id == "abc123"


def test_parse_spotify_album() -> None:
    ref = parse_spotify_url("https://open.spotify.com/album/abc123")
    assert ref.kind == MediaKind.ALBUM


def test_parse_spotify_playlist() -> None:
    ref = parse_spotify_url("https://open.spotify.com/playlist/abc123")
    assert ref.kind == MediaKind.PLAYLIST

