from ripmedia.model import Provider
from ripmedia.providers.detect import detect_provider


def test_detect_youtube_variants() -> None:
    assert detect_provider("https://youtu.be/abc") == Provider.YOUTUBE
    assert detect_provider("https://www.youtube.com/watch?v=abc") == Provider.YOUTUBE
    assert detect_provider("https://music.youtube.com/watch?v=abc") == Provider.YOUTUBE


def test_detect_soundcloud() -> None:
    assert detect_provider("https://soundcloud.com/user/track") == Provider.SOUNDCLOUD
    assert detect_provider("https://on.soundcloud.com/abc123") == Provider.SOUNDCLOUD


def test_detect_spotify() -> None:
    assert detect_provider("https://open.spotify.com/track/abc") == Provider.SPOTIFY
