# ripmedia

ripmedia is a metadata-first CLI tool. Give it a URL (or list of URLs) and it saves clean, tagged files to a predictable path.

## Features

- Providers: YouTube, SoundCloud, Spotify (metadata only + resolver), Twitter/X, Pornhub, and other yt-dlp supported sites
- Clean tags: title, artist, album, year, track and disc where available
- Cover art embedding when available
- Deterministic naming + folder layout
- Batch downloads and playlist/album expansion
- Browser cookie profile discovery + export helpers
- Local web UI (`ripmedia webhost`) with live progress

## Requirements

- Python 3.10+
- ffmpeg on PATH (`ffmpeg -version`)

## Install

1) Clone the repo (or download a ZIP) and `cd` into it.

2) Install pipx and ensure PATH:

```powershell
py -m pip install --user --upgrade pipx
py -m pipx ensurepath
# restart your terminal after ensurepath
```

3) Install ripmedia:

```powershell
pipx install -e .
```

After that, `ripmedia --help` should work from any directory.

### Windows installer script (optional)

This repo includes a helper that checks requirements, installs pipx + ripmedia, and runs a quick verification:

```powershell
.\scripts\install.ps1
```

If ffmpeg is missing, run with `-InstallFfmpeg` to attempt a winget install:

```powershell
.\scripts\install.ps1 -InstallFfmpeg
```

## Verify install

```powershell
ripmedia --help
ripmedia info <url>
```

## Updating

Because this is an editable install, updates are just a pull + reinstall:

```powershell
git pull
pipx reinstall ripmedia
```

Or run the built-in updater:

```powershell
ripmedia update
```

By default, `ripmedia update` pulls/install updates from GitHub.
For local development, disable that behavior:

```powershell
ripmedia update --no-github-update
```

Or set it in config:

```powershell
ripmedia config update_from_github=false
```

## Usage

Download:

```powershell
ripmedia <url...>
ripmedia download <url...>
```

Metadata preview:

```powershell
ripmedia info <url>
ripmedia info <url> --json
```

Batch:

```powershell
ripmedia urls.txt
ripmedia <url1> <url2> <url3>
```

Local web UI:

```powershell
ripmedia webhost
ripmedia webhost --port 8787 --parallel 4 --no-open
```

Other built-in helpers:

```powershell
ripmedia help
ripmedia cookies
ripmedia cookies refresh
```

## Plugins

Plugins are just Python files in `~/.ripmedia/plugins`. They can add new subcommands or react to events.
Available hook events: `download_start`, `download_complete`, `download_error`.

Basic management:

```powershell
ripmedia plugins
ripmedia plugins init discord
ripmedia plugins enable discord
ripmedia plugins disable discord
ripmedia plugins remove discord
```

Example (Discord webhook):

```powershell
ripmedia discord send "https://youtu.be/..." --mp3
```

Set `discord_webhook` in `config.ini` for that example.

Minimal plugin skeleton:

```python
def register(plugin):
    @plugin.command("hello")
    def hello():
        ui = plugin.make_ui()
        ui.status("Plugin", True, "Hello from a plugin")
```

### Format overrides

Default output behavior:

- With `prefer_mp3_mp4=true` (default): audio defaults to `.mp3`, video defaults to `.mp4`
- With `prefer_mp3_mp4=false`: legacy defaults are used (`.m4a` for audio, `.mp4` for video)

Override formats explicitly with:

```powershell
ripmedia --audio-format mp3 <url>
ripmedia --video-format mkv <url>
ripmedia --mp3 <url>
```

Tagging is implemented for `mp3`, `m4a`, and `mp4`. Other formats will be saved but may skip tagging.

When `prefer_mp3_mp4` is true (default), mp4 outputs are auto-optimized for broad playback (H.264 + AAC + faststart), so they work better in Discord and on phones.

### Spotify resolver

By default, Spotify items resolve to YouTube for the actual media. To use SoundCloud:

```powershell
ripmedia --resolver soundcloud "https://open.spotify.com/track/<id>"
```

If a Spotify match confidence is low, re-run with `--interactive` to select a candidate manually.

### Cookies

Interactive browser profile selection:

```powershell
ripmedia cookies
```

Export detected browser cookies to a local `cookies.txt` and save it in config:

```powershell
ripmedia cookies refresh
```

You can also set cookies directly:

```powershell
ripmedia --cookies "C:\path\to\cookies.txt" <url>
ripmedia --cookies-from-browser "chrome|Default|C:\Users\You\AppData\Local\Google\Chrome\User Data" <url>
```

### PowerShell note (URLs with `&`)

In PowerShell, `&` is a special operator. If your URL contains tracking parameters, quote it:

```powershell
ripmedia "https://soundcloud.com/...?...&utm_campaign=..."
```

Alternative: stop-parsing token:

```powershell
ripmedia --% https://soundcloud.com/...?...&utm_campaign=...
```

## Configuration

Config file location:

- Windows: `C:\Users\You\.ripmedia\config.ini`
- macOS/Linux: `~/.ripmedia/config.ini`

Open the config file:

```powershell
ripmedia config
```

Update config defaults and remove legacy keys:

```powershell
ripmedia config update
```

Set a value:

```powershell
ripmedia config output_dir="C:\Users\You\Downloads"
ripmedia config resolver=soundcloud
ripmedia config audio=true
```

Supported keys:

- `output_dir` (default base folder)
- `web_port` (default port for `ripmedia webhost`, `0` = auto)
- `override_audio_format` (format string or `false`)
- `override_video_format` (format string or `false`)
- `prefer_mp3_mp4` (use mp3/mp4 defaults; set `false` to keep legacy m4a/mp4)
- `show_file_size` (show file size in progress output)
- `update_from_github` (when `true`, `ripmedia update` uses GitHub updates)
- `speed_unit` (`mb/s` for MB/s, `mbp/s` for Mb/s)
- `resolver` (`youtube` or `soundcloud`)
- `audio` (default audio-first)
- `verbose`
- `debug`
- `quiet`
- `print_path`
- `no_color`
- `interactive`
- `cookies`
- `cookies_from_browser`

Boolean values accept `true/false`, `yes/no`, `on/off`, `1/0`. Use `none` or `false` to clear a value.

## Spotify notes

For full Spotify album/playlist expansion, set:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
