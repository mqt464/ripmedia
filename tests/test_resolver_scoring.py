from ripmedia.model import MediaKind, NormalizedItem, Provider
from ripmedia.resolver import _score_candidate


def test_score_candidate_prefers_matching_artist() -> None:
    item = NormalizedItem(
        provider=Provider.SPOTIFY,
        kind=MediaKind.TRACK,
        id="t1",
        url="https://open.spotify.com/track/t1",
        title="Tear Me Apart",
        artist="Concernn",
        duration_seconds=180,
    )

    good = {"title": "Concernn - Tear Me Apart (Audio)", "channel": "Concernn", "duration": 181}
    bad = {"title": "Tear Me Apart", "channel": "RandomUploader", "duration": 180}

    assert _score_candidate(item, good) > _score_candidate(item, bad)

