from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from yt_dlp import YoutubeDL

from .errors import ResolveError
from .model import NormalizedItem, Provider


class _NoopLogger:
    def debug(self, msg: str) -> None:  # noqa: D401
        pass

    def warning(self, msg: str) -> None:  # noqa: D401
        pass

    def error(self, msg: str) -> None:  # noqa: D401
        pass


@dataclass(frozen=True)
class ResolvedSource:
    url: str
    provider: Provider
    confidence: float
    confidence_hint: str | None = None
    selected_title: str | None = None
    selected_channel: str | None = None


def resolve(item: NormalizedItem, *, preferred: Provider = Provider.YOUTUBE) -> ResolvedSource:
    if item.provider != Provider.SPOTIFY:
        raise ResolveError("Resolver is only used for Spotify items in v1.", stage="Resolve")
    if preferred == Provider.YOUTUBE:
        return _resolve_spotify_to_youtube(item)
    if preferred == Provider.SOUNDCLOUD:
        return _resolve_spotify_to_soundcloud(item)
    raise ResolveError(f"Unsupported resolver provider: {preferred}", stage="Resolve")

def resolve_candidates(
    item: NormalizedItem,
    *,
    preferred: Provider = Provider.YOUTUBE,
    limit: int = 5,
) -> list[ResolvedSource]:
    if item.provider != Provider.SPOTIFY:
        raise ResolveError("Resolver is only used for Spotify items in v1.", stage="Resolve")
    if preferred == Provider.YOUTUBE:
        return _resolve_candidates_from_search(item, provider=Provider.YOUTUBE, prefix="ytsearch", limit=limit)
    if preferred == Provider.SOUNDCLOUD:
        return _resolve_candidates_from_search(
            item, provider=Provider.SOUNDCLOUD, prefix="scsearch", limit=limit
        )
    raise ResolveError(f"Unsupported resolver provider: {preferred}", stage="Resolve")


def _resolve_spotify_to_youtube(item: NormalizedItem) -> ResolvedSource:
    candidates = resolve_candidates(item, preferred=Provider.YOUTUBE, limit=5)
    if not candidates:
        raise ResolveError("No YouTube candidates found.", stage="Resolve")
    return candidates[0]


def _resolve_spotify_to_soundcloud(item: NormalizedItem) -> ResolvedSource:
    candidates = resolve_candidates(item, preferred=Provider.SOUNDCLOUD, limit=5)
    if not candidates:
        raise ResolveError("No SoundCloud candidates found.", stage="Resolve")
    return candidates[0]


def _resolve_candidates_from_search(
    item: NormalizedItem, *, provider: Provider, prefix: str, limit: int
) -> list[ResolvedSource]:
    if not item.title:
        raise ResolveError("Spotify item is missing title; cannot resolve.", stage="Resolve")

    query_parts = [item.artist, item.title]
    base_query = " - ".join([p for p in query_parts if p])
    isrc = _spotify_isrc(item)

    search_queries = []
    if isrc:
        search_queries.append(f"{prefix}{max(limit,5)}:{base_query} {isrc}")
    search_queries.append(f"{prefix}{max(limit,5)}:{base_query}")

    entries: list[dict] = []
    try:
        with YoutubeDL(
            {
                "quiet": True,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "no_warnings": True,
                "logger": _NoopLogger(),
            }
        ) as ydl:
            for search in search_queries:
                info = ydl.extract_info(search, download=False)
                if isinstance(info, dict):
                    entries.extend([e for e in (info.get("entries") or []) if isinstance(e, dict)])
    except Exception as e:  # noqa: BLE001
        label = "YouTube" if provider == Provider.YOUTUBE else "SoundCloud"
        raise ResolveError(f"{label} search failed: {e}", stage="Resolve") from e

    if not entries:
        return []

    deduped: dict[str, dict] = {}
    for e in entries:
        url = _entry_url(provider, e)
        if not url:
            continue
        deduped[url] = e

    candidates: list[ResolvedSource] = []
    for url, e in deduped.items():
        candidate_duration = e.get("duration")
        hint = _duration_hint(item.duration_seconds, candidate_duration)
        confidence = _score_candidate(item, e)
        candidates.append(
            ResolvedSource(
                url=url,
                provider=provider,
                confidence=confidence,
                confidence_hint=hint,
                selected_title=e.get("title"),
                selected_channel=e.get("channel") or e.get("uploader"),
            )
        )

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates[:limit]


def _entry_url(provider: Provider, entry: dict) -> str | None:
    url = entry.get("webpage_url") or entry.get("url")
    if not url:
        return None
    url_s = str(url)
    if provider == Provider.YOUTUBE and url_s and "://" not in url_s:
        return f"https://www.youtube.com/watch?v={url_s}"
    return url_s


def _score_candidate(item: NormalizedItem, candidate: dict) -> float:
    expected_title = _norm_text(item.title or "")
    expected_artist = _norm_text(item.artist or "")

    cand_title = _norm_text(candidate.get("title") or "")
    cand_channel = _norm_text(candidate.get("channel") or "")
    cand_uploader = _norm_text(candidate.get("uploader") or "")

    title_score = _similarity(expected_title, cand_title)
    if expected_artist:
        artist_score = max(
            _similarity(expected_artist, cand_channel),
            _contains(expected_artist, cand_channel),
            _similarity(expected_artist, cand_uploader),
            _contains(expected_artist, cand_uploader),
            _similarity(expected_artist, cand_title),  # catches "Artist - Title" cases
            _contains(expected_artist, cand_title),
        )
    else:
        artist_score = 0.0

    base: float
    if item.duration_seconds is None or candidate.get("duration") is None:
        base = (0.7 * title_score) + (0.3 * artist_score)
    else:
        delta = abs(int(item.duration_seconds) - int(candidate["duration"]))
        duration_score = max(0.0, 1.0 - (delta / 30.0))  # 0 at >=30s mismatch
        base = (0.45 * title_score) + (0.35 * artist_score) + (0.20 * duration_score)

    isrc = _spotify_isrc(item)
    if isrc:
        hay = " ".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("channel") or ""),
                str(candidate.get("uploader") or ""),
            ]
        ).lower()
        if isrc.lower() in hay:
            base += 0.15
    return min(1.0, base)


def _duration_hint(expected: int | None, actual: int | None) -> str | None:
    if expected is None or actual is None:
        return None
    delta = int(actual) - int(expected)
    sign = "+" if delta >= 0 else ""
    return f"duration delta {sign}{delta}s"


_PUNCT = re.compile(r"[^a-z0-9]+")


def _norm_text(value: str) -> str:
    value = value.lower()
    value = value.replace("&", " and ")
    value = _PUNCT.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _contains(needle: str, haystack: str) -> float:
    if not needle or not haystack:
        return 0.0
    return 1.0 if needle in haystack else 0.0


def _spotify_isrc(item: NormalizedItem) -> str | None:
    if not item.extra:
        return None
    spotify = item.extra.get("spotify")
    if not isinstance(spotify, dict):
        return None
    isrc = spotify.get("isrc")
    return str(isrc).strip() if isrc else None
