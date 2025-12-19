from __future__ import annotations

from pathlib import Path


def expand_url_args(args: list[str]) -> list[str]:
    urls: list[str] = []
    for arg in args:
        path = Path(arg)
        if path.exists() and path.is_file():
            urls.extend(_read_urls_file(path))
        else:
            urls.append(arg)
    return urls


def _read_urls_file(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls

