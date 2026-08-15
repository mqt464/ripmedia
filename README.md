# ripmedia

`ripmedia` is a Windows CLI that downloads media from yt-dlp-compatible public or user-authorized URLs while preserving the source's chosen format by default.

## Install

```powershell
irm https://raw.githubusercontent.com/mqt464/ripmedia/main/scripts/install.ps1 | iex
```

The installer downloads a verified GitHub Release bundle. It includes ripmedia, yt-dlp, and FFmpeg—no Python or separate setup is required.

## Use

```powershell
ripmedia "https://soundcloud.com/artist/track"
ripmedia download "https://example.com/video" --format mp4
ripmedia "https://example.com/video" --mp4
ripmedia "https://example.com/audio" --mp3
ripmedia info "https://example.com/video" --formats
ripmedia cookies
```

By default ripmedia saves the highest-quality source video and audio streams available to Downloads, merging them with FFmpeg when needed, without transcoding. When you select a browser profile with `ripmedia cookies`, YouTube downloads use that profile's authorized session and the bundled local token provider to access high-quality streams. `--audio` selects the best source audio; `--mp3`, `--mp4`, and `--format` explicitly convert using FFmpeg. Supported conversion targets are `mp3`, `m4a`, `aac`, `flac`, `ogg`, `opus`, `wav`, `mp4`, `mkv`, and `webm`.

Run `ripmedia config` to open `settings.json` in your default JSON or text editor. Leave `DefaultAudioFormat` and `DefaultVideoFormat` blank to keep source formats; set them to a supported audio or video format to convert downloads of that media type. Per-download `--format`, `--mp3`, and `--mp4` options take precedence.

SoundCloud playlists are saved as numbered collection folders and tagged with available metadata and artwork. TikTok downloads the best stream made available by the extractor; ripmedia does not remove an embedded watermark or bypass DRM, paywalls, logins, or access controls.

## Commands

`download` (default), `info`, `cookies`, `config`, `webhost`, `update`, `version`, and `help`.

`ripmedia webhost` opens a minimal local downloader at `http://127.0.0.1:4747`. Paste a URL followed by any download flags and press Enter to queue it (for example, `https://example.com/video --mp3`); further URLs run in parallel. Quote flag values containing spaces, such as `--output-dir "C:\Media Files"`. Keep the terminal open while downloads run; press Ctrl+C to stop the web host. It skips browser-profile cookies because it opens a browser itself; use a configured cookies file if an authorized URL requires authentication.

`ripmedia cookies` shows an interactive browser-profile menu. It stores a profile reference only; it does not export browser cookies. You may also pass `--cookies <netscape.txt>` or `--cookies-from-browser <yt-dlp-spec>` per command.

## License

GPL-3.0-only. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
