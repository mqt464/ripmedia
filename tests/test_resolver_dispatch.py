import ripmedia.resolver as resolver
from ripmedia.model import MediaKind, NormalizedItem, Provider


def test_resolve_dispatches_to_soundcloud() -> None:
    item = NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.TRACK,
        id="t1",
        url="https://open.spotify.com/track/t1",
        title="Song",
        artist="Artist",
    )

    original = resolver._resolve_spotify_to_soundcloud
    try:
        resolver._resolve_spotify_to_soundcloud = lambda _item: resolver.ResolvedSource(
            url="https://soundcloud.com/x/y",
            provider=Provider.SOUNDCLOUD,
            confidence=1.0,
        )
        out = resolver.resolve(item, preferred=Provider.SOUNDCLOUD)
        assert out.provider == Provider.SOUNDCLOUD
    finally:
        resolver._resolve_spotify_to_soundcloud = original

