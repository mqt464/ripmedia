from __future__ import annotations


def normalize_cookies_from_browser(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if str(v))
    raw = str(value).strip()
    if not raw or raw.lower() in {"none", "null", "false"}:
        return None
    parts = _split_spec(raw)
    if not parts:
        return None
    return _build_spec_tuple(parts)


def _split_spec(raw: str) -> list[str]:
    if "|" in raw:
        parts = [p for p in raw.split("|") if p]
    else:
        parts = [p for p in raw.split(":") if p]
        parts = _repair_windows_path_parts(parts)
    return parts


def _repair_windows_path_parts(parts: list[str]) -> list[str]:
    if len(parts) < 3:
        return parts
    for idx in range(1, len(parts) - 1):
        head = parts[idx]
        tail = parts[idx + 1]
        if len(head) == 1 and head.isalpha() and (tail.startswith("\\") or tail.startswith("/")):
            return parts[:idx] + [":".join(parts[idx:])]
    return parts


def _build_spec_tuple(parts: list[str]) -> tuple[str, ...]:
    if not parts:
        return None  # type: ignore[return-value]
    if len(parts) == 1:
        return (parts[0],)
    if len(parts) == 2:
        return (parts[0], parts[1])

    browser = parts[0]
    profile = parts[1]
    tail = parts[2]

    if _looks_like_path(tail):
        profile_path = tail
        if not profile_path.endswith(profile):
            profile_path = _join_path(profile_path, profile)
        return (browser, profile_path)

    if len(parts) == 3:
        return (browser, profile, None, tail)

    return (browser, profile, parts[2], parts[3])


def _looks_like_path(value: str) -> bool:
    return (
        "\\" in value
        or "/" in value
        or (len(value) > 2 and value[1:3] == ":\\" and value[0].isalpha())
    )


def _join_path(base: str, leaf: str) -> str:
    if base.endswith(("\\", "/")):
        return f"{base}{leaf}"
    if "\\" in base:
        return f"{base}\\{leaf}"
    return f"{base}/{leaf}"
