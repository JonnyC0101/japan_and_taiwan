$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $projectRoot
try {
    python -m compileall -q src tests
    python -m unittest discover -s tests\unit -v
    python tests\validation\validate_delivery.py
    python tests\validation\validate_single_code.py
    $latestMonthDirectory = Get-ChildItem ".\outputs\monthly" -Directory |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $latestMonthDirectory) {
        throw "No monthly output directory was found."
    }
    $latestOutput = $latestMonthDirectory.FullName
    node tests\validation\scan_workbooks.mjs `
        (Join-Path $latestOutput "import\all_ccc_import.xlsx") `
        (Join-Path $latestOutput "export\all_ccc_export.xlsx") `
        (Join-Path $latestOutput "import\by_ccc_code\84021200004.xlsx") `
        (Join-Path $latestOutput "export\by_ccc_code\84021200004.xlsx")
}
finally {
    Pop-Location
}
