from ripmedia.urls import normalize_url


def test_normalize_twitter_status_url():
    url = "https://x.com/rinabearz/status/2021005545956835462?s=20"
    assert normalize_url(url) == "https://twitter.com/i/status/2021005545956835462"


def test_normalize_twitter_status_with_video_path():
    url = "https://twitter.com/user/status/1234567890/video/1"
    assert normalize_url(url) == "https://twitter.com/i/status/1234567890"


def test_normalize_non_twitter_url():
    url = "https://example.com/path?x=1"
    assert normalize_url(url) == url
