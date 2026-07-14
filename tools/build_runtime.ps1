param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("cpu", "cuda", "winml")]
    [string]$Backend,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeId,
    [string]$Python = "python",
    [string]$OutputDirectory = "release-out"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $ProjectRoot "build\runtime\$RuntimeId"
$DistRoot = Join-Path $BuildRoot "dist"
$WorkRoot = Join-Path $BuildRoot "work"
$SpecRoot = Join-Path $BuildRoot "spec"
$RuntimeRoot = Join-Path $BuildRoot "runtime"
$ReleaseRoot = Join-Path $ProjectRoot $OutputDirectory

if ($Backend -eq "winml") {
    throw "WinML Worker is not implemented yet; do not publish a winml runtime package."
}

& $Python -c "import torch, whisper; print(torch.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "The selected Python must contain Torch and openai-whisper."
}

$TorchReport = & $Python -c "import torch; print('cuda=' + str(torch.version.cuda)); print('available=' + str(torch.cuda.is_available()))"
if ($Backend -eq "cuda" -and $TorchReport -notmatch "cuda=.+" ) {
    throw "CUDA runtime build requires a CUDA-enabled Torch wheel in the selected Python environment."
}
if ($Backend -eq "cpu" -and $TorchReport -match "cuda=.+") {
    Write-Warning "Building a CPU package with a CUDA Torch environment; use a CPU Torch build to keep the package small."
}

Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean EchovaultWorker.spec `
        --distpath $DistRoot --workpath $WorkRoot --specpath $SpecRoot
    if ($LASTEXITCODE -ne 0) {
        throw "ASR Worker build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$WorkerSource = Join-Path $DistRoot "echovault-asr-worker"
$WorkerDestination = Join-Path $RuntimeRoot "worker"
Copy-Item -LiteralPath $WorkerSource -Destination $WorkerDestination -Recurse

$Metadata = [ordered]@{
    runtime_id = $RuntimeId
    backend = $Backend
    worker_path = "worker/echovault-asr-worker.exe"
    built_at_utc = [DateTime]::UtcNow.ToString("o")
}
$Metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeRoot "runtime.json") -Encoding utf8

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
$Archive = Join-Path $ReleaseRoot "$RuntimeId.zip"
Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $RuntimeRoot "*") -DestinationPath $Archive -CompressionLevel Optimal

Write-Host "Runtime package created: $Archive"
Write-Host "Next: split and sign it with tools\publish_runtime.py before uploading to the GitHub Release."
