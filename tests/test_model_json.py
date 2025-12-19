from ripmedia.model import Attribution, MediaKind, NormalizedItem, Provider


def test_to_json_serializes_enums_and_entries() -> None:
    child = NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.TRACK,
        id="t1",
        url="https://open.spotify.com/track/t1",
        title="Song",
        attribution=Attribution(metadata_source=Provider.SPOTIFY, media_source=Provider.YOUTUBE),
    )
    parent = NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.ALBUM,
        id="a1",
        url="https://open.spotify.com/album/a1",
        title="Album",
        entries=[child],
    )

    data = parent.to_json()
    assert data["provider"] == "spotify"
    assert data["kind"] == "album"
    assert isinstance(data["entries"], list)
    assert data["entries"][0]["provider"] == "spotify"
    assert data["entries"][0]["attribution"]["media_source"] == "youtube"

