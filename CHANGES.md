# Changes Summary

## Naming and Paths
- Single-item track filenames now include artist and title to reduce collisions and match expected output.
- Playlist item numbering now prefers playlist order (when available) without altering tag metadata.

## Download Reliability
- Downloaded media selection now prioritizes yt-dlp reported file paths.
- Fallback file selection now ignores image thumbnails to prevent moving artwork as media.
- yt-dlp errors are condensed to the most useful message (e.g., HTTP status).

## Tagging Robustness
- Missing `ffmpeg` now raises a clean tagging error instead of a raw crash for non-mp3/mp4 formats.

## Config and CLI Consistency
- Config format overrides are validated on load for clearer errors.
- Typer option definitions are centralized to keep flags and help text consistent.
- Resolver option handling is case-insensitive across commands.
- Added `ripmedia update` to refresh code, update yt-dlp, and check/install system deps.
- Added `ripmedia config update` to add missing defaults and remove legacy config keys.
- Added `web_port` config for the webhost server port (`0` auto-assigns).
- Added `ripmedia plugins` for local plugins (enable/disable/init/remove) with a Discord template.
- Download error hints now show a single, clean line: "Try running `ripmedia update`."
- yt-dlp warnings are suppressed during metadata and resolver fetches for cleaner output.
- New `prefer_mp3_mp4` config flag controls mp3/mp4 defaults (set `false` to keep legacy m4a).
- Added `speed_unit` config to choose MB/s or Mb/s in progress output.
- Update output now shows a live progress bar with step status lines underneath.
- Progress bar now shows count on the left, elapsed time, and hides counts when total is unknown.
- Update steps show spinner, per-step duration, timestamp, and trimmed details.

## Download UI
- Download progress now includes bytes, configurable speed units, and per-stage status entries.
- New `show_file_size` config toggles file size in the progress bar.
- Post-processing stages label common operations like remux or audio extraction.
- MP4 outputs now auto-optimize for Discord/phone playback (H.264 + AAC + faststart) when `prefer_mp3_mp4` is true.

## Providers
- Added Twitter/X URL detection.

## Webhost
- Added `ripmedia webhost` for a lightweight local web UI with SSE updates.

## Versioning
- Package version now reads from installed metadata with a safe fallback.
