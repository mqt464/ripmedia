$ErrorActionPreference = 'Stop'
$repo = 'mqt464/ripmedia'
$root = Join-Path $env:LOCALAPPDATA 'ripmedia'
$versions = Join-Path $root 'versions'
$bin = Join-Path $root 'bin'

$release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'ripmedia-installer' }
$zipAsset = $release.assets | Where-Object { $_.name -eq 'ripmedia-win-x64.zip' } | Select-Object -First 1
$sumAsset = $release.assets | Where-Object { $_.name -eq 'SHA256SUMS' } | Select-Object -First 1
if (-not $zipAsset -or -not $sumAsset) { throw 'The latest ripmedia release is incomplete.' }

$temp = Join-Path ([IO.Path]::GetTempPath()) ("ripmedia-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
  $zip = Join-Path $temp 'ripmedia-win-x64.zip'
  Invoke-WebRequest $zipAsset.browser_download_url -OutFile $zip
  # Windows PowerShell 5.1 exposes Invoke-WebRequest .Content as a byte array.
  # Invoke-RestMethod decodes this text asset consistently in both Windows
  # PowerShell and PowerShell 7+, so the checksum regex sees the actual file.
  $sums = Invoke-RestMethod $sumAsset.browser_download_url -Headers @{ 'User-Agent' = 'ripmedia-installer' }
  $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($sums -notmatch "(?im)^$hash\s+\*?ripmedia-win-x64\.zip\r?$") { throw 'Release checksum verification failed.' }
  $target = Join-Path $versions $release.tag_name
  if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force -Recurse }
  New-Item -ItemType Directory -Path $target -Force | Out-Null
  Expand-Archive -LiteralPath $zip -DestinationPath $target -Force
  New-Item -ItemType Directory -Path $bin -Force | Out-Null
  $launcher = Join-Path $target 'ripmedia-launcher.exe'
  if (-not (Test-Path -LiteralPath $launcher)) { throw 'Release bundle is missing the ripmedia launcher.' }
  Copy-Item -LiteralPath $launcher -Destination (Join-Path $bin 'ripmedia.exe') -Force
  Set-Content -LiteralPath (Join-Path $bin 'current.txt') -Value (Join-Path $target 'ripmedia.exe') -NoNewline
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (($userPath -split ';') -notcontains $bin) { [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $bin), 'User') }
  if (($env:Path -split ';') -notcontains $bin) { $env:Path += ';' + $bin }
  Write-Host "ripmedia $($release.tag_name) installed. Run: ripmedia --help"
} finally {
  if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -Recurse }
}
