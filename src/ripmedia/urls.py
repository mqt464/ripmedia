from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse


_TWITTER_HOSTS = {
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    "x.com",
    "www.x.com",
    "mobile.x.com",
}


def expand_url_args(args: list[str]) -> list[str]:
    urls: list[str] = []
    for arg in args:
        path = Path(arg)
        if path.exists() and path.is_file():
            urls.extend(_read_urls_file(path))
        else:
            urls.append(arg)
    return [normalize_url(u) for u in urls]


def _read_urls_file(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def normalize_url(url: str) -> str:
    raw = str(url).strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host in _TWITTER_HOSTS:
        match = re.search(r"/status/(\d+)", parsed.path or "")
        if not match:
            match = re.search(r"/i/status/(\d+)", parsed.path or "")
        if match:
            status_id = match.group(1)
            return f"https://twitter.com/i/status/{status_id}"
        normalized = parsed._replace(scheme="https", netloc="twitter.com", query="", fragment="")
        return urlunparse(normalized)
    return raw
