$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDirectory = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDirectory "monthly_$timestamp.log"

$pythonCommand = Get-Command python -ErrorAction Stop
$nodeCommand = Get-Command node -ErrorAction Stop

Push-Location $projectRoot
try {
    & $pythonCommand.Source ".\src\pipeline.py" `
        --auto `
        --flow both `
        --refresh-months 3 `
        --refresh-reference `
        --concurrency 4 `
        --excel-concurrency 6 `
        --node $nodeCommand.Source 2>&1 | Tee-Object -FilePath $logFile
    if ($LASTEXITCODE -ne 0) {
        throw "Taiwan monthly workflow failed with exit code $LASTEXITCODE. See $logFile"
    }
}
finally {
    Pop-Location
}

