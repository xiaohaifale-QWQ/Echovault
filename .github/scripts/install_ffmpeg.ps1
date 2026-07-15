$ErrorActionPreference = "Stop"

if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and
    (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    ffmpeg -version | Select-Object -First 1
    ffprobe -version | Select-Object -First 1
    exit 0
}

$archive = Join-Path $env:RUNNER_TEMP "ffmpeg-n7.1-win64-gpl.zip"
$destination = Join-Path $env:RUNNER_TEMP "echovault-ffmpeg"
$url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-win64-gpl-7.1.zip"

Invoke-WebRequest -Uri $url -OutFile $archive
Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
$ffmpeg = Get-ChildItem -LiteralPath $destination -Recurse -Filter "ffmpeg.exe" |
    Select-Object -First 1
if (-not $ffmpeg) {
    throw "Downloaded FFmpeg archive does not contain ffmpeg.exe"
}
$binDirectory = $ffmpeg.Directory.FullName
$ffprobe = Join-Path $binDirectory "ffprobe.exe"
if (-not (Test-Path -LiteralPath $ffprobe)) {
    throw "Downloaded FFmpeg archive does not contain ffprobe.exe"
}

$binDirectory | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
$env:Path = "$binDirectory;$env:Path"
ffmpeg -version | Select-Object -First 1
ffprobe -version | Select-Object -First 1
