# Regenerates locked requirement files from the shared human-edited manifests.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$PythonVersionFile = Join-Path $Root ".python-version"
if ((-not (Test-Path $PythonVersionFile)) -or ((Get-Item $PythonVersionFile).Length -eq 0)) {
    throw ".python-version is required and must contain a Python version like 3.12 or 3.12.13."
}
$Want = (Get-Content $PythonVersionFile -TotalCount 1).Trim()
if ($Want -notmatch '^\d+\.\d+(\.\d+)?$') {
    throw ".python-version must contain a Python version like 3.12 or 3.12.13."
}
$WantMinor = ($Want -split "\.")[0..1] -join "."

function Require-Input {
    param([string]$Path)
    if ((-not (Test-Path -LiteralPath $Path)) -or ((Get-Item -LiteralPath $Path).Length -eq 0)) {
        throw "$Path is required to compile dependency locks."
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required to compile dependency lock files. Install it from https://docs.astral.sh/uv/ and rerun this script."
}

Require-Input "requirements/requirements.txt"
Require-Input "requirements/requirements-dev.txt"
Require-Input "requirements/requirements-build.txt"

function Compile-RuntimeLock {
    param(
        [string]$Platform,
        [string]$OutputFile
    )
    uv pip compile requirements/requirements.txt `
        --upgrade `
        --no-header `
        --python-version $WantMinor `
        --python-platform $Platform `
        --output-file $OutputFile
    Write-Host "Updated $OutputFile for $Platform / Python $WantMinor."
}

function Compile-UniversalLock {
    param(
        [string]$InputFile,
        [string]$OutputFile
    )
    uv pip compile $InputFile `
        --upgrade `
        --universal `
        --no-header `
        --python-version $WantMinor `
        --output-file $OutputFile
    Write-Host "Updated $OutputFile for Python $WantMinor."
}

function Compile-OptionalLock {
    param(
        [string]$Platform,
        [string]$ConstraintFile,
        [string]$InputFile,
        [string]$OutputFile
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
    $UvArgs = @(
        "pip", "compile", $InputFile,
        "--upgrade", "--no-header", "--emit-index-url",
        "--python-version", $WantMinor,
        "--python-platform", $Platform,
        "--constraint", $ConstraintFile,
        "--output-file", $OutputFile
    )
    if ($InputFile -like "*kokoro-gpu.in") {
        $UvArgs += @("--index-strategy", "unsafe-best-match")
    }
    & uv @UvArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to compile optional dependency lock $OutputFile."
    }
    Write-Host "Updated $OutputFile for $Platform / Python $WantMinor."
}

function Compile-OptionalLocks {
    $Matrix = @(
        @{ Name = "windows-x64"; Platform = "x86_64-pc-windows-msvc"; Constraint = "requirements/requirements-windows.lock"; Variants = @("stt-cpu", "stt-cuda", "kokoro-cpu", "kokoro-gpu", "elevenlabs", "live-voice") },
        @{ Name = "linux-x64"; Platform = "x86_64-manylinux_2_34"; Constraint = "requirements/requirements-linux.lock"; Variants = @("stt-cpu", "kokoro-cpu", "kokoro-gpu", "elevenlabs", "live-voice") },
        @{ Name = "macos-arm64"; Platform = "aarch64-apple-darwin"; Constraint = "requirements/requirements-macos.lock"; Variants = @("stt-cpu", "kokoro-cpu", "elevenlabs", "live-voice") }
    )
    foreach ($ContractTarget in $Matrix) {
        foreach ($Kind in @("source", "release")) {
            foreach ($Variant in $ContractTarget.Variants) {
                $InputVariant = $Variant
                if ($Kind -eq "source" -and $Variant -eq "stt-cuda") {
                    $InputVariant = "stt-cpu"
                }
                Compile-OptionalLock `
                    $ContractTarget.Platform `
                    $ContractTarget.Constraint `
                    "requirements/optional/inputs/$InputVariant.in" `
                    "requirements/optional/$Kind/$($ContractTarget.Name)/$Variant.lock"
            }
        }
    }
}

$Targets = $args
if ($Targets.Count -eq 0) {
    $Targets = @("all")
}

foreach ($Target in $Targets) {
    switch ($Target) {
        "all" {
            Compile-RuntimeLock "x86_64-pc-windows-msvc" "requirements/requirements-windows.lock"
            Compile-RuntimeLock "x86_64-manylinux_2_34" "requirements/requirements-linux.lock"
            Compile-RuntimeLock "aarch64-apple-darwin" "requirements/requirements-macos.lock"
            Compile-UniversalLock "requirements/requirements-dev.txt" "requirements/requirements-dev.lock"
            Compile-UniversalLock "requirements/requirements-build.txt" "requirements/requirements-build.lock"
            Compile-OptionalLocks
        }
        "windows" { Compile-RuntimeLock "x86_64-pc-windows-msvc" "requirements/requirements-windows.lock" }
        "linux" { Compile-RuntimeLock "x86_64-manylinux_2_34" "requirements/requirements-linux.lock" }
        "macos" { Compile-RuntimeLock "aarch64-apple-darwin" "requirements/requirements-macos.lock" }
        "dev" { Compile-UniversalLock "requirements/requirements-dev.txt" "requirements/requirements-dev.lock" }
        "build" { Compile-UniversalLock "requirements/requirements-build.txt" "requirements/requirements-build.lock" }
        "optional" { Compile-OptionalLocks }
        default { throw "Unknown lock target '$Target'. Use all, windows, linux, macos, dev, build, or optional." }
    }
}
