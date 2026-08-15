[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [string]$Destination
)

$ErrorActionPreference = 'Stop'

$manifestPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'eng/dependencies.json'
$dependencies = Get-Content -Raw $manifestPath | ConvertFrom-Json

New-Item -ItemType Directory -Path $Destination -Force | Out-Null

function Restore-File {
  param(
    [Parameter(Mandatory)]$Dependency,
    [Parameter(Mandatory)][string]$Path
  )

  if (Test-Path -LiteralPath $Path) {
    $actualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -eq $Dependency.sha256) { return }
    Remove-Item -LiteralPath $Path -Force
  }

  Invoke-WebRequest -Uri $Dependency.url -OutFile $Path
  $actualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualHash -ne $Dependency.sha256) {
    Remove-Item -LiteralPath $Path -Force
    throw "Checksum verification failed for $(Split-Path $Path -Leaf)."
  }
}

Restore-File -Dependency $dependencies.ytDlp -Path (Join-Path $Destination 'yt-dlp.exe')

$ffmpegZip = Join-Path ([IO.Path]::GetTempPath()) ("ripmedia-ffmpeg-" + [guid]::NewGuid() + '.zip')
$ffmpegDirectory = Join-Path ([IO.Path]::GetTempPath()) ("ripmedia-ffmpeg-" + [guid]::NewGuid())
try {
  Restore-File -Dependency $dependencies.ffmpeg -Path $ffmpegZip
  Expand-Archive -LiteralPath $ffmpegZip -DestinationPath $ffmpegDirectory
  $ffmpeg = Get-ChildItem -LiteralPath $ffmpegDirectory -Recurse -Filter ffmpeg.exe | Select-Object -First 1
  if (-not $ffmpeg) { throw 'The FFmpeg archive did not contain ffmpeg.exe.' }
  Copy-Item -LiteralPath $ffmpeg.FullName -Destination (Join-Path $Destination 'ffmpeg.exe') -Force
} finally {
  if (Test-Path -LiteralPath $ffmpegZip) { Remove-Item -LiteralPath $ffmpegZip -Force }
  if (Test-Path -LiteralPath $ffmpegDirectory) { Remove-Item -LiteralPath $ffmpegDirectory -Force -Recurse }
}

$node = Get-Command node.exe -ErrorAction SilentlyContinue
$npm = Get-Command npm -ErrorAction SilentlyContinue
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $node -or -not $npm -or -not $git) { throw 'Restoring YouTube high-quality support requires Node.js, npm, and Git.' }

$provider = $dependencies.youtubePoTokenProvider
$providerSource = Join-Path ([IO.Path]::GetTempPath()) ("ripmedia-pot-provider-" + [guid]::NewGuid())
$pluginDirectory = Join-Path $Destination 'yt-dlp-plugins'
$plugin = Join-Path $pluginDirectory 'bgutil-ytdlp-pot-provider.zip'
$providerDirectory = Join-Path $Destination 'pot-provider'
try {
  New-Item -ItemType Directory -Path $pluginDirectory -Force | Out-Null
  Restore-File -Dependency ([pscustomobject]@{ url = $provider.pluginUrl; sha256 = $provider.pluginSha256 }) -Path $plugin
  & $git.Source clone --no-checkout $provider.repository $providerSource
  if ($LASTEXITCODE -ne 0) { throw 'Could not download the YouTube PO-token provider source.' }
  & $git.Source -C $providerSource checkout $provider.commit
  if ($LASTEXITCODE -ne 0) { throw 'Could not verify the YouTube PO-token provider source.' }
  Push-Location (Join-Path $providerSource 'server')
  try {
    & $npm.Source ci --include=dev
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the YouTube PO-token provider dependencies.' }
    & (Join-Path (Get-Location) 'node_modules\.bin\tsc.cmd')
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the YouTube PO-token provider.' }
  } finally { Pop-Location }
  New-Item -ItemType Directory -Path $providerDirectory -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $providerSource 'server') -Destination (Join-Path $providerDirectory 'server') -Recurse -Force
  Copy-Item -LiteralPath $node.Source -Destination (Join-Path $providerDirectory 'node.exe') -Force
} finally {
  if (Test-Path -LiteralPath $providerSource) { Remove-Item -LiteralPath $providerSource -Force -Recurse }
}
