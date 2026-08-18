param(
    [string]$TaskName = "conductordata-japan-import-monthly",
    [string]$RunAt = "10:00"
)

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run_monthly.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Runner not found: $runner"
}

$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runner`""
& schtasks.exe /Create /F /TN $TaskName /SC MONTHLY /D 1 /ST $RunAt /TR $taskCommand
if ($LASTEXITCODE -ne 0) {
    throw "Could not create scheduled task $TaskName. Run PowerShell as a user allowed to create tasks."
}
Write-Output "Created scheduled task '$TaskName' for day 1 of every month at $RunAt."
