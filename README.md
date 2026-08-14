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
ripmedia "https://example.com/audio" --mp3
ripmedia info "https://example.com/video" --formats
ripmedia cookies
```

By default ripmedia saves the best source-provided combined file to Downloads without transcoding. `--audio` selects source audio; `--mp3` and `--format` explicitly convert using FFmpeg. Supported conversion targets are `mp3`, `m4a`, `aac`, `flac`, `ogg`, `opus`, `wav`, `mp4`, `mkv`, and `webm`.

SoundCloud playlists are saved as numbered collection folders and tagged with available metadata and artwork. TikTok downloads the best stream made available by the extractor; ripmedia does not remove an embedded watermark or bypass DRM, paywalls, logins, or access controls.

## Commands

`download` (default), `info`, `cookies`, `config`, `update`, `version`, and `help`.

`ripmedia cookies` shows an interactive browser-profile menu. It stores a profile reference only; it does not export browser cookies. You may also pass `--cookies <netscape.txt>` or `--cookies-from-browser <yt-dlp-spec>` per command.

## License

GPL-3.0-only. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
