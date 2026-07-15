$ErrorActionPreference = "Stop"

if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and
    (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    ffmpeg -version | Select-Object -First 1
    ffprobe -version | Select-Object -First 1
    exit 0
}

$archive = Join-Path $env:RUNNER_TEMP "ffmpeg-release-essentials.7z"
$destination = Join-Path $env:RUNNER_TEMP "echovault-ffmpeg"
$url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.7z"

Invoke-WebRequest -Uri $url -OutFile $archive
$sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
$sevenZipPath = if ($sevenZip) {
    $sevenZip.Source
} else {
    Join-Path $env:ProgramFiles "7-Zip\7z.exe"
}
if (-not (Test-Path -LiteralPath $sevenZipPath)) {
    throw "7-Zip was not found on the Windows runner"
}
New-Item -ItemType Directory -Force -Path $destination | Out-Null
& $sevenZipPath x $archive "-o$destination" -y
if ($LASTEXITCODE -ne 0) {
    throw "Unable to extract the FFmpeg archive (exit code $LASTEXITCODE)"
}
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
