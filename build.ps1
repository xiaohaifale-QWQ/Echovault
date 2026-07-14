param(
    [switch]$InstallDependencies,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

if ($InstallDependencies) {
    & $Python -m pip install -r requirements-cloud.txt -r requirements-local.txt -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed with exit code $LASTEXITCODE"
    }
}

$PyInstallerAvailable = & $Python -c "import PyInstaller; print('yes')" 2>$null
if ($LASTEXITCODE -ne 0 -or $PyInstallerAvailable -ne "yes") {
    throw "PyInstaller is not installed. Run: python -m pip install -r requirements-dev.txt"
}

$FfmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $FfmpegCommand) {
    throw "ffmpeg was not found. Install it and add it to PATH before building."
}
$FfprobeCommand = Get-Command ffprobe -ErrorAction SilentlyContinue
if (-not $FfprobeCommand) {
    throw "ffprobe was not found. Install ffmpeg (including ffprobe) and add it to PATH before building."
}

$env:ECHOVAULT_FFMPEG = $FfmpegCommand.Source
$env:ECHOVAULT_FFPROBE = $FfprobeCommand.Source
& $Python -m PyInstaller --clean --noconfirm Echovault.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host "Build complete: $ProjectRoot\dist\Echovault\Echovault.exe"
