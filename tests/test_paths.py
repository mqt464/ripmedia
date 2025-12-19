from pathlib import Path

from ripmedia.model import MediaKind, NormalizedItem, Provider
from ripmedia.paths import build_collection_item_plan, build_output_plan, collection_directory, sanitize_path_segment


def test_sanitize_path_segment_windows_illegals() -> None:
    s = sanitize_path_segment('a<>:"/\\\\|?*b')
    for ch in '<>:"/\\|?*':
        assert ch not in s


def test_build_output_plan_stable() -> None:
    item = NormalizedItem(
        provider=Provider.YOUTUBE,
        kind=MediaKind.TRACK,
        id="abc",
        url="https://example.com",
        title="Hello:World",
        artist="Some/Artist",
        album="An<Album>",
        track_number=1,
    )
    plan = build_output_plan(item, output_dir=Path("output"), extension=".m4a")
    assert plan.directory.as_posix().endswith("output")
    assert plan.filename_stem == "Some_Artist - Hello_World"


def test_build_output_plan_album_folder() -> None:
    album = NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.ALBUM,
        id="alb",
        url="https://example.com",
        title="My Album",
        album="My Album",
        track_number=2,
    )
    folder = collection_directory(album, output_dir=Path("output"))
    assert folder.as_posix().endswith("output/My Album")

    track = NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.TRACK,
        id="t1",
        url="https://example.com/t1",
        title="Song Name",
        track_number=2,
    )
    plan = build_collection_item_plan(track, output_dir=folder, extension=".m4a", track_number=2)
    assert plan.filename_stem == "02 - Song Name"
