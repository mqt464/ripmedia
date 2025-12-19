param(
    [string]$RepoPath = (Get-Location),
    [switch]$InstallFfmpeg
)

$ErrorActionPreference = "Stop"

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command "py")) {
    Write-Error "Python launcher not found. Install Python 3.10+ from python.org and try again."
    exit 1
}

if (-not (Test-Command "ffmpeg")) {
    if ($InstallFfmpeg -and (Test-Command "winget")) {
        Write-Host "Installing ffmpeg with winget..."
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    } else {
        Write-Error "ffmpeg not found. Install it and re-run (or use -InstallFfmpeg if winget is available)."
        exit 1
    }
}

Write-Host "Installing pipx..."
py -m pip install --user --upgrade pipx | Out-Host
py -m pipx ensurepath | Out-Host

if (-not (Test-Path -Path $RepoPath)) {
    Write-Error "Repo path not found: $RepoPath"
    exit 1
}

Push-Location $RepoPath
try {
    $hasRipmedia = (pipx list 2>$null | Select-String -Pattern "^package ripmedia")
    if ($hasRipmedia) {
        Write-Host "Reinstalling ripmedia..."
        pipx reinstall ripmedia | Out-Host
    } else {
        Write-Host "Installing ripmedia..."
        pipx install -e . | Out-Host
    }
} finally {
    Pop-Location
}

if (Test-Command "ripmedia") {
    Write-Host "ripmedia is installed. Running --help to verify..."
    ripmedia --help | Out-Host
} else {
    Write-Warning "ripmedia is not on PATH yet. Restart your terminal and run: ripmedia --help"
}
