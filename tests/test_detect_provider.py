from ripmedia.model import Provider
from ripmedia.providers.detect import detect_provider


def test_detect_provider_twitter() -> None:
    assert detect_provider("https://twitter.com/user/status/1") == Provider.TWITTER
    assert detect_provider("https://x.com/user/status/1") == Provider.TWITTER
