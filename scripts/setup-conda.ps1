param(
    [string]$EnvName = "emata",
    [string]$CondaRoot = "",
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

$CondaExe = $null
if ($CondaRoot) {
    $Candidate = Join-Path $CondaRoot "Scripts/conda.exe"
    if (Test-Path $Candidate) {
        $CondaExe = $Candidate
    }
}

if (-not $CondaExe) {
    $Command = Get-Command conda -ErrorAction SilentlyContinue
    if ($Command) {
        $CondaExe = $Command.Source
    }
}

if (-not $CondaExe) {
    Write-Error "conda not found. Install Miniconda first, or pass -CondaRoot with the install directory."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot "environment.yml"
$FrontendDir = Join-Path $ProjectRoot "frontend"

Write-Host "Updating conda environment from $EnvFile ..."
& $CondaExe env update --name $EnvName --file $EnvFile --prune

Write-Host "Activating environment and verifying Python ..."
& $CondaExe run -n $EnvName python --version

$EnvPrefix = (
    & $CondaExe run -n $EnvName python -c "import sys; print(sys.prefix)" |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -Last 1
).Trim()
$NpmCmd = Join-Path $EnvPrefix "npm.cmd"

if (-not $SkipFrontend) {
    Write-Host "Installing frontend dependencies ..."
    Push-Location $FrontendDir
    try {
        if (Test-Path $NpmCmd) {
            & $NpmCmd install
        }
        else {
            & $CondaExe run -n $EnvName npm install
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Ready."
Write-Host "Activate with: conda activate $EnvName"
Write-Host "Backend tests: `$env:PYTHONPATH='E:/Project/Agent/backend'; python -m unittest E:/Project/Agent/backend/tests/test_api_contract.py E:/Project/Agent/backend/tests/test_persistence.py E:/Project/Agent/backend/tests/test_integrations.py"
Write-Host "Frontend tests: node --test E:/Project/Agent/frontend/tests/dashboard.test.mjs"
