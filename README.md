# ripmedia

ripmedia is a metadata-first CLI tool. Give it a URL (or list of URLs) and it saves clean, tagged files to a predictable path.

## Features

- Providers: YouTube, SoundCloud, Spotify (metadata only + resolver)
- Clean tags: title, artist, album, year, track and disc where available
- Cover art embedding when available
- Deterministic naming + folder layout
- Batch downloads and playlist/album expansion

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

### Format overrides

Defaults are audio `.m4a` and video `.mp4`. Override with:

```powershell
ripmedia --audio-format mp3 <url>
ripmedia --video-format mkv <url>
ripmedia --mp3 <url>
```

Tagging is implemented for `mp3`, `m4a`, and `mp4`. Other formats will be saved but may skip tagging.

### Spotify resolver

By default, Spotify items resolve to YouTube for the actual media. To use SoundCloud:

```powershell
ripmedia --resolver soundcloud "https://open.spotify.com/track/<id>"
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

Set a value:

```powershell
ripmedia config output_dir="C:\Users\You\Downloads"
ripmedia config resolver=soundcloud
ripmedia config audio=true
```

Supported keys:

- `output_dir` (default base folder)
- `override_audio_format` (format string or `false`)
- `override_video_format` (format string or `false`)
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
