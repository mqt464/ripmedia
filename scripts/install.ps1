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
  $sums = (Invoke-WebRequest $sumAsset.browser_download_url).Content
  $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($sums -notmatch "(?im)^$hash\s+\*?ripmedia-win-x64\.zip$") { throw 'Release checksum verification failed.' }
  $target = Join-Path $versions $release.tag_name
  if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force -Recurse }
  New-Item -ItemType Directory -Path $target -Force | Out-Null
  Expand-Archive -LiteralPath $zip -DestinationPath $target -Force
  New-Item -ItemType Directory -Path $bin -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $bin 'ripmedia.cmd') -Value "@echo off`r`n`"$target\ripmedia.exe`" %*" -NoNewline
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (($userPath -split ';') -notcontains $bin) { [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $bin), 'User') }
  if (($env:Path -split ';') -notcontains $bin) { $env:Path += ';' + $bin }
  Write-Host "ripmedia $($release.tag_name) installed. Run: ripmedia --help"
} finally {
  if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -Recurse }
}
