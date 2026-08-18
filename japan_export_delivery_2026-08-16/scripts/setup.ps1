$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$systemPython = (Get-Command python -ErrorAction Stop).Source
$node = (Get-Command node -ErrorAction Stop).Source
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $systemPython -m venv .venv
    }
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed with exit code $LASTEXITCODE."
    }
    & $node -e "import('@oai/artifact-tool').then(() => console.log('Excel runtime OK'))"
    if ($LASTEXITCODE -ne 0) {
        throw "The vendored Excel runtime could not be loaded."
    }
    Write-Host "Setup complete. Run scripts\run_monthly.ps1 to update the workbooks."
}
finally {
    Pop-Location
}

