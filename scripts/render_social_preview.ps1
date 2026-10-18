param(
    [string]$Source = (Join-Path $PSScriptRoot "..\assets\app.png"),
    [string]$Output = (Join-Path $PSScriptRoot "..\assets\social-preview.png"),
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
if (-not $Python) {
    $venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}
$generator = Join-Path $PSScriptRoot "generate_brand_assets.py"
& $Python $generator --social-preview-only --source $Source --output $Output
if ($LASTEXITCODE -ne 0) {
    throw "Could not generate the PNG social preview. Python with Pillow is required."
}
