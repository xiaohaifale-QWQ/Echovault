param(
    [switch]$InstallDependencies,
    [ValidateSet("Lite", "Full")]
    [string]$Profile = "Lite",
    [string]$Python = "python",
    [string]$DistPath = "dist",
    [string]$WorkPath = "build"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

if ($InstallDependencies) {
    $RequirementFiles = @("requirements-cloud.txt", "requirements-dev.txt")
    if ($Profile -eq "Full") {
        $RequirementFiles += @("requirements-local.txt", "requirements-translation.txt")
    }
    $RequirementArguments = foreach ($RequirementFile in $RequirementFiles) {
        "-r"
        $RequirementFile
    }
    & $Python -m pip install @RequirementArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed with exit code $LASTEXITCODE"
    }
}

$CloudDependenciesAvailable = & $Python -c "import groq, requests; print('yes')" 2>$null
if ($LASTEXITCODE -ne 0 -or $CloudDependenciesAvailable -ne "yes") {
    throw "Cloud dependencies are missing. Run build.ps1 with -InstallDependencies."
}

if ($Profile -eq "Full") {
    $LocalDependenciesAvailable = & $Python -c "import argostranslate, audio_separator, demucs, torch, torchaudio, whisper; print('yes')" 2>$null
    if ($LASTEXITCODE -ne 0 -or $LocalDependenciesAvailable -ne "yes") {
        throw "Full-build AI dependencies are missing. Run build.ps1 -Profile Full -InstallDependencies."
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
$env:ECHOVAULT_BUILD_PROFILE = $Profile.ToLowerInvariant()
& $Python -m PyInstaller --clean --noconfirm Echovault.spec `
    --distpath $DistPath --workpath $WorkPath
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$OutputDirectory = Join-Path (Resolve-Path -LiteralPath $DistPath) "Echovault"
$OutputBytes = (
    Get-ChildItem -LiteralPath $OutputDirectory -Recurse -File |
    Measure-Object -Property Length -Sum
).Sum
$OutputMegabytes = [math]::Round($OutputBytes / 1MB, 1)
Write-Host "Build profile: $Profile"
Write-Host "Build complete: $OutputDirectory\Echovault.exe"
Write-Host "Build size: $OutputMegabytes MB"
