from ripmedia.ytdlp_utils import normalize_cookies_from_browser


def test_normalize_cookies_from_browser_single():
    assert normalize_cookies_from_browser("chrome") == ("chrome",)


def test_normalize_cookies_from_browser_split():
    assert normalize_cookies_from_browser("chrome:Default") == ("chrome", "Default")


def test_normalize_cookies_from_browser_none():
    assert normalize_cookies_from_browser("none") is None


def test_normalize_cookies_from_browser_windows_path():
    raw = r"chrome:C:\Users\mat\AppData\Local\Helium\User Data"
    assert normalize_cookies_from_browser(raw) == (
        r"chrome",
        r"C:\Users\mat\AppData\Local\Helium\User Data",
    )


def test_normalize_cookies_from_browser_windows_path_with_profile():
    raw = r"chrome:Profile 1:C:\Users\mat\AppData\Local\Helium\User Data"
    assert normalize_cookies_from_browser(raw) == (
        r"chrome",
        r"C:\Users\mat\AppData\Local\Helium\User Data\Profile 1",
    )


def test_normalize_cookies_from_browser_pipe_separator():
    raw = r"chrome|Profile 1|C:\Users\mat\AppData\Local\Helium\User Data"
    assert normalize_cookies_from_browser(raw) == (
        r"chrome",
        r"C:\Users\mat\AppData\Local\Helium\User Data\Profile 1",
    )
