$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = Join-Path $projectRoot "scripts\run_monthly.ps1"
$taskName = "Taiwan Trade Monthly Workflow"
$powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$taskCommand = "`"$powerShell`" -NoProfile -ExecutionPolicy Bypass -File `"$runner`""
& schtasks.exe /Create /TN $taskName /TR $taskCommand /SC MONTHLY /D 15 /ST 14:00 /F
if ($LASTEXITCODE -ne 0) {
    throw "Unable to create Windows scheduled task (exit code $LASTEXITCODE)."
}
Write-Host "Created scheduled task '$taskName' for the 15th of each month at 14:00."
