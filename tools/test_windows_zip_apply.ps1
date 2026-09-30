# Exercise in-place ZIP updates, portable data preservation, and failure diagnostics.
[CmdletBinding()]
param([string]$HelperPath = '')

$ErrorActionPreference = 'Stop'
if (-not $HelperPath) {
    $HelperPath = Join-Path $PSScriptRoot '..\assets\updater\windows_apply_update.ps1'
}
$Helper = (Resolve-Path -LiteralPath $HelperPath).Path
$TempRoot = [System.IO.Path]::GetFullPath($(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP })).TrimEnd('\')
$Root = Join-Path $TempRoot ("OpenWandZipApplySmoke-" + [guid]::NewGuid().ToString('N'))
$InstallRoot = Join-Path $Root 'portable\OpenWand'
$WorkRoot = Join-Path $Root 'work'
$Candidate = Join-Path $WorkRoot 'extract\OpenWand'
$Archive = Join-Path $Root 'downloads\bridge.zip'
$RestartTarget = Join-Path $InstallRoot 'OpenWand.exe'
$BackupRoot = "$InstallRoot.previous-update"
$ErrorLog = Join-Path (Split-Path -Parent $Archive) 'apply-bridge-error.log'
$Bootstrap = Join-Path $Root 'invoke-old-updater.ps1'

function Invoke-OldUpdater {
    param([string]$CurrentCandidate)
    $env:OW_TEST_HELPER = $Helper
    $env:OW_TEST_ARCHIVE = $Archive
    $env:OW_TEST_INSTALL_ROOT = $InstallRoot
    $env:OW_TEST_CANDIDATE = $CurrentCandidate
    $env:OW_TEST_RESTART_TARGET = $RestartTarget
    $env:OW_TEST_BACKUP_ROOT = $BackupRoot
    $env:OW_TEST_WORK_ROOT = $WorkRoot
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', "`"$Bootstrap`""
    ) -PassThru -Wait -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Root 'bootstrap-out.txt') `
        -RedirectStandardError (Join-Path $Root 'bootstrap-err.txt')
    if ($process.ExitCode -ne 0) {
        $details = if (Test-Path -LiteralPath $ErrorLog) { Get-Content -LiteralPath $ErrorLog -Raw } else {
            Get-Content -LiteralPath (Join-Path $Root 'bootstrap-err.txt') -Raw
        }
        throw "Old updater bootstrap failed with exit code $($process.ExitCode): $details"
    }
}

try {
    New-Item -ItemType Directory -Path $InstallRoot, $Candidate, (Split-Path -Parent $Archive) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $env:WINDIR 'System32\whoami.exe') -Destination $RestartTarget
    Copy-Item -LiteralPath $RestartTarget -Destination (Join-Path $Candidate 'OpenWand.exe')
    Set-Content -LiteralPath $Archive -Value 'test archive placeholder'
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot '_internal'), (Join-Path $Candidate '_internal') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'addons') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $InstallRoot '_internal\version.txt') -Value 'old'
    Set-Content -LiteralPath (Join-Path $InstallRoot '_internal\obsolete.txt') -Value 'remove me'
    Set-Content -LiteralPath (Join-Path $Candidate '_internal\version.txt') -Value 'bridge'
    Set-Content -LiteralPath (Join-Path $InstallRoot 'addons\user-addon.txt') -Value 'keep me'
    Set-Content -LiteralPath (Join-Path $InstallRoot 'Uninstall OpenWand.bat') -Value 'old batch'
    Set-Content -LiteralPath (Join-Path $Candidate 'Uninstall OpenWand.bat') -Value 'bridge batch'
    @'
Set-Location -LiteralPath (Join-Path $env:OW_TEST_INSTALL_ROOT '_internal')
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $env:OW_TEST_HELPER `
    -Archive $env:OW_TEST_ARCHIVE -InstallRoot $env:OW_TEST_INSTALL_ROOT `
    -Candidate $env:OW_TEST_CANDIDATE -RestartTarget $env:OW_TEST_RESTART_TARGET `
    -BackupRoot $env:OW_TEST_BACKUP_ROOT -WorkRoot $env:OW_TEST_WORK_ROOT
exit $LASTEXITCODE
'@ | Set-Content -LiteralPath $Bootstrap

    Invoke-OldUpdater -CurrentCandidate $Candidate
    for ($attempt = 0; $attempt -lt 120 -and (Test-Path -LiteralPath $WorkRoot); $attempt++) {
        if (Test-Path -LiteralPath $ErrorLog) { throw "Bridge helper failed: $(Get-Content -LiteralPath $ErrorLog -Raw)" }
        Start-Sleep -Milliseconds 500
    }
    if ((Get-Content -LiteralPath (Join-Path $InstallRoot '_internal\version.txt') -Raw).Trim() -ne 'bridge') {
        throw 'The bridge did not update the packaged files.'
    }
    if (Test-Path -LiteralPath (Join-Path $InstallRoot '_internal\obsolete.txt')) {
        throw 'The bridge left an obsolete packaged file.'
    }
    if ((Get-Content -LiteralPath (Join-Path $InstallRoot 'addons\user-addon.txt') -Raw).Trim() -ne 'keep me') {
        throw 'The bridge changed portable add-ons.'
    }
    if ((Test-Path -LiteralPath $BackupRoot) -or (Test-Path -LiteralPath $WorkRoot)) {
        throw 'The bridge left its backup or extraction folder after success.'
    }

    $MissingCandidate = Join-Path $Root 'missing-candidate'
    Invoke-OldUpdater -CurrentCandidate $MissingCandidate
    for ($attempt = 0; $attempt -lt 120 -and -not (Test-Path -LiteralPath $ErrorLog); $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $ErrorLog)) { throw 'The helper did not retain its own error log.' }
    if ((Get-Content -LiteralPath (Join-Path $InstallRoot '_internal\version.txt') -Raw).Trim() -ne 'bridge') {
        throw 'A failed bridge attempt altered the portable files.'
    }

    Remove-Item -LiteralPath $ErrorLog -Force
    New-Item -ItemType Directory -Path (Join-Path $Candidate '_internal') -Force | Out-Null
    $oldExeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $RestartTarget).Hash
    Set-Content -LiteralPath (Join-Path $Candidate 'OpenWand.exe') -Value 'invalid executable'
    Set-Content -LiteralPath (Join-Path $Candidate '_internal\version.txt') -Value 'incomplete'
    Invoke-OldUpdater -CurrentCandidate $Candidate
    for ($attempt = 0; $attempt -lt 120 -and -not (Test-Path -LiteralPath $ErrorLog); $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $ErrorLog)) { throw 'The failed copy did not retain its error log.' }
    if ((Get-Content -LiteralPath (Join-Path $InstallRoot '_internal\version.txt') -Raw).Trim() -ne 'bridge' -or
        (Test-Path -LiteralPath $BackupRoot) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $RestartTarget).Hash -ne $oldExeHash) {
        throw 'The bridge did not restore packaged files after a failed copy.'
    }
    if ((Get-Content -LiteralPath (Join-Path $InstallRoot 'addons\user-addon.txt') -Raw).Trim() -ne 'keep me') {
        throw 'The failed copy changed portable add-ons.'
    }
    Write-Host 'Windows ZIP bridge updated in place, retained add-ons, restored a failed copy, and preserved diagnostics.'
} finally {
    $ResolvedRoot = [System.IO.Path]::GetFullPath($Root)
    if (-not $ResolvedRoot.StartsWith($TempRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
        [System.IO.Path]::GetFileName($ResolvedRoot) -notlike 'OpenWandZipApplySmoke-*') {
        throw "Unsafe cleanup target: $ResolvedRoot"
    }
    if (Test-Path -LiteralPath $ResolvedRoot) {
        Remove-Item -LiteralPath $ResolvedRoot -Recurse -Force
    }
}
