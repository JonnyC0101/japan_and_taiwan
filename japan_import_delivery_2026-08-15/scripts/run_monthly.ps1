param(
    [string]$Python = "",
    [string]$Node = "node",
    [int]$RefreshMonths = 2
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not $Python) {
    $Python = if (Test-Path -LiteralPath $projectPython) { $projectPython } else { "python" }
}
$bundledNode = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if ($Node -eq "node" -and -not (Get-Command node -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $bundledNode)) {
    $Node = $bundledNode
}
$logDirectory = Join-Path $projectRoot "outputs\logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDirectory "monthly_$stamp.log"

Push-Location $projectRoot
try {
    & $Python ".\src\pipeline.py" `
        --auto `
        --refresh-months $RefreshMonths `
        --excel-scope all `
        --node $Node 2>&1 | Tee-Object -FilePath $logPath
    if ($LASTEXITCODE -ne 0) {
        throw "Monthly pipeline failed with exit code $LASTEXITCODE. See $logPath"
    }
}
finally {
    Pop-Location
}
