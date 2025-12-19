# ripmedia — TODO / Roadmap

This file tracks the work needed to ship `ripmedia` v1 per the current spec.

## Milestone 0 — Project bootstrap

- [x] Choose implementation stack (Python + Typer + Rich).
- [x] Add `README.md` basics (what it is/isn't, requirements, quickstart).
- [x] Add basic project scaffolding (packaging, entrypoint, versioning).
- [x] Add CI (lint/test/build).
- [ ] Decide release plan (pipx/git, PyPI, binaries).
- [x] Decide config strategy (v1: CLI-only vs config file).

## Milestone 1 - Core CLI contract + UX

- [x] Commands:
  - [x] `ripmedia <url...>` (defaults to `download`)
  - [x] `ripmedia download <url...>`
  - [x] `ripmedia info <url>` (`--json` supported)
  - [x] `ripmedia config` (open file / set key=value)
- [x] Flags:
  - [x] `--audio`, `-v/--verbose`, `--debug`, `--quiet`, `--print-path`, `--no-color`, `--interactive`, `--resolver`
- [x] Pipeline stage UX:
  - [x] Detected
  - [x] Resolve (Spotify)
  - [x] Downloading (progress bar)
  - [x] Post-process (explicit stage + spinner when ffmpeg runs)
  - [x] Tagging
  - [x] Saved
- [x] Exit codes:
  - [x] `0` success
  - [x] `1` partial success (batch failures)
  - [x] `2` invalid input/usage
- [x] Error messaging standard:
  - [x] Always include stage + hint (retry/auth/cookies/change resolver)

## Milestone 2 — Normalized metadata model

- [x] Track + Video item model with common fields (`id`, `provider`, `url`, `title`, `artist`, etc).
- [x] Album/Playlist as collections (track list + ordering in the model).
- [x] `info` serialization:
  - [x] human readable
  - [x] `--json`

## Milestone 3 — Providers (detect + metadata)

- [x] Provider detection (YouTube/SoundCloud/Spotify; includes `on.soundcloud.com`).
- [x] YouTube metadata (via `yt-dlp`).
- [x] SoundCloud metadata (via `yt-dlp`).
- [x] Spotify:
  - [x] Track metadata (Spotipy if creds, else oEmbed fallback)
  - [x] Album/playlist expansion (track list + per-track metadata; requires creds)

## Milestone 4 — Resolver (Spotify -> downloadable source)

- [x] Default resolver: YouTube search
- [x] Confidence hints in default output (duration delta where available)
- [x] Verbose shows selected title/URL
- [x] Improve confidence scoring:
  - [x] ISRC match when available (search + scoring bonus)
- [x] Interactive selection for low-confidence matches

## Milestone 5 — Downloader (yt-dlp wrapper)

- [x] Safe execution (no shell, temp dirs, cleanup).
- [x] Progress parsing -> single progress bar.
- [x] Sensible defaults:
  - [x] audio-first for track-like sources (SoundCloud/Spotify/TRACK)
  - [x] best audio when `--audio`
- [x] Album/playlist downloads:
  - [x] overall counter `12/43`
  - [x] per-item progress for active item
  - [x] continue-on-error inside playlist by default (exit `1` if partial)
- [x] Cookies/auth pass-through flags.

## Milestone 6 - Post-processing (ffmpeg wrapper)

- [x] Explicit post-process stage in UI (spinner by default, raw logs in debug).
- [x] Optional transcode support (format override via ffmpeg).

## Milestone 7 - Tagging + artwork embedding

- [x] Basic tagging for mp3/m4a/mp4 (title/artist/album/year/track, cover art when available).
- [x] Disc number support where available.
- [x] Decide/lock output formats for v1 and document them.

## Milestone 8 — Deterministic output (paths + filenames)

- [x] Sanitization (Windows-safe) + stable filenames.
- [x] Collision strategy (suffix ` (1)`).
- [x] Output layout:
  - [x] Single items: save directly into Downloads (flat).
  - [x] Collections: create one folder per album/playlist and put tracks inside.
- [x] `--print-path` support.

## Milestone 9 — Batch + file input

- [x] Multiple URLs in one invocation.
- [x] `urls.txt` input (ignore blanks/comments).
- [x] Summary at end (success/fail counts, list failed URLs).

## Validation & quality gates

- [x] Tests: URL detection + filename sanitization.
- [x] Tests: metadata JSON serialization.
- [x] Tests: resolver scoring (unit tests; no network).
- [ ] Optional: integration smoke script for known public URLs.
