# Verify the released ZIP updater's bridge helper completes installer migration
# without reopening the portable copy or asking for a second Settings action.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Helper = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\assets\updater\windows_apply_update.ps1')).Path
$TempRoot = [IO.Path]::GetFullPath($(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP })).TrimEnd('\')
$Root = Join-Path $TempRoot ("OpenWandZipAutoInstaller-" + [guid]::NewGuid().ToString('N'))
$InstallRoot = Join-Path $Root 'portable\OpenWand'
$Candidate = Join-Path $Root 'work\extract\OpenWand'
$WorkRoot = Join-Path $Root 'work'
$Archive = Join-Path $Root 'user-data\updates\bridge.zip'
$InstallerSource = Join-Path $Root 'signed-setup.exe'
$Manifest = Join-Path $Root 'manifest.json'
$Report = Join-Path $Root 'migration-report.txt'
$PortableRestart = Join-Path $Root 'portable-restarted.txt'
$RestartTarget = Join-Path $InstallRoot 'OpenWand.exe'

try {
    New-Item -ItemType Directory -Path $InstallRoot, $Candidate, (Split-Path -Parent $Archive) -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot '_internal'), (Join-Path $Candidate '_internal\assets\updater') -Force | Out-Null
    $probeSource = Join-Path $Root 'portable-probe.cs'
    @'
using System;
using System.IO;
public static class Program {
    public static int Main() {
        File.WriteAllText(Environment.GetEnvironmentVariable("OW_TEST_PORTABLE_RESTART"), "restarted");
        return 0;
    }
}
'@ | Set-Content -LiteralPath $probeSource
    $env:OW_TEST_PROBE_SOURCE = $probeSource
    $env:OW_TEST_PROBE_EXE = $RestartTarget
    $env:OW_TEST_PORTABLE_RESTART = $PortableRestart
    & powershell.exe -NoProfile -NonInteractive -Command 'Add-Type -Path $env:OW_TEST_PROBE_SOURCE -OutputAssembly $env:OW_TEST_PROBE_EXE -OutputType ConsoleApplication'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $RestartTarget)) {
        throw 'Could not compile the portable restart probe.'
    }
    Copy-Item -LiteralPath $RestartTarget -Destination (Join-Path $Candidate 'OpenWand.exe')
    Set-Content -LiteralPath (Join-Path $InstallRoot '_internal\version.txt') -Value 'old'
    Set-Content -LiteralPath (Join-Path $Candidate '_internal\version.txt') -Value 'bridge'
    Set-Content -LiteralPath $Archive -Value 'bridge archive fixture'
    Set-Content -LiteralPath $InstallerSource -Value 'signed installer fixture'

    # The real installer helper's signature/install behavior is exercised by
    # test_portable_to_installer.ps1. This probe checks the one-click handoff.
    @'
param(
    [string]$Installer, [string]$ExpectedSha256, [int]$WaitPid,
    [string]$CurrentExecutable, [string]$SingleInstanceLock,
    [string]$StatusPath, [string]$PortableRoot, [string]$UserAddonsRoot
)
Set-Content -LiteralPath $env:OW_TEST_MIGRATION_REPORT -Value "$Installer|$ExpectedSha256|$WaitPid|$PortableRoot|$UserAddonsRoot"
exit 0
'@ | Set-Content -LiteralPath (Join-Path $Candidate '_internal\assets\updater\windows_apply_installer.ps1')

    $archiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    $installerHash = (Get-FileHash -LiteralPath $InstallerSource -Algorithm SHA256).Hash.ToLowerInvariant()
    @{
        version = '0.12.0'
        assets = @{
            'windows-x64' = @{ name = 'bridge.zip'; url = ([uri]$Archive).AbsoluteUri; sha256 = $archiveHash }
            'windows-x64-installer' = @{ name = 'signed-setup.exe'; url = ([uri]$InstallerSource).AbsoluteUri; sha256 = $installerHash }
        }
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Manifest
    $env:OPENWAND_UPDATE_MANIFEST_URL = ([uri]$Manifest).AbsoluteUri
    $env:OW_TEST_MIGRATION_REPORT = $Report

    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Helper `
        -Archive $Archive -InstallRoot $InstallRoot -Candidate $Candidate `
        -RestartTarget $RestartTarget -BackupRoot "$InstallRoot.previous-update" `
        -WorkRoot $WorkRoot -SingleInstanceLock (Join-Path $Root 'user-data\openwand.lock')
    if ($LASTEXITCODE -ne 0) { throw "Bridge handoff failed: $LASTEXITCODE" }
    for ($attempt = 0; $attempt -lt 120 -and -not (Test-Path -LiteralPath $Report); $attempt++) {
        $errorLog = Join-Path (Split-Path -Parent $Archive) 'apply-installer-migration-error.log'
        if (Test-Path -LiteralPath $errorLog) { throw (Get-Content -LiteralPath $errorLog -Raw) }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $Report)) { throw 'Bridge did not invoke the installer helper.' }
    $fields = (Get-Content -LiteralPath $Report -Raw).Trim() -split '\|'
    $downloaded = Join-Path (Split-Path -Parent $Archive) 'signed-setup.exe'
    if ($fields.Count -ne 5 -or $fields[0] -ine $downloaded -or
        $fields[1] -ine $installerHash -or $fields[2] -ne '0' -or
        $fields[3] -ine $InstallRoot -or
        $fields[4] -ine (Join-Path $Root 'user-data\addons')) {
        throw "Bridge passed incorrect installer arguments: $($fields -join '|')"
    }
    if ((Get-FileHash -LiteralPath $downloaded -Algorithm SHA256).Hash -ine $installerHash) {
        throw 'Bridge did not download the manifest-verified installer.'
    }
    if ((Get-Content -LiteralPath (Join-Path $InstallRoot '_internal\version.txt') -Raw).Trim() -ne 'bridge') {
        throw 'Bridge did not apply the ZIP before installer handoff.'
    }
    Start-Sleep -Seconds 1
    if (Test-Path -LiteralPath $PortableRestart) {
        throw 'Bridge reopened the portable copy after successful installer handoff.'
    }
    for ($attempt = 0; $attempt -lt 40 -and (Test-Path -LiteralPath $WorkRoot); $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (Test-Path -LiteralPath $WorkRoot) { throw 'Successful bridge left its extraction folder.' }

    # An installer failure must reopen the now-updated portable copy.
    New-Item -ItemType Directory -Path (Join-Path $Candidate '_internal\assets\updater') -Force | Out-Null
    Copy-Item -LiteralPath $RestartTarget -Destination (Join-Path $Candidate 'OpenWand.exe')
    Set-Content -LiteralPath (Join-Path $Candidate '_internal\version.txt') -Value 'bridge-fallback'
    Set-Content -LiteralPath (Join-Path $Candidate '_internal\assets\updater\windows_apply_installer.ps1') -Value 'exit 1'
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Helper `
        -Archive $Archive -InstallRoot $InstallRoot -Candidate $Candidate `
        -RestartTarget $RestartTarget -BackupRoot "$InstallRoot.previous-update" `
        -WorkRoot $WorkRoot -SingleInstanceLock (Join-Path $Root 'user-data\openwand.lock')
    if ($LASTEXITCODE -ne 0) { throw "Fallback bridge handoff failed: $LASTEXITCODE" }
    $fallbackError = Join-Path (Split-Path -Parent $Archive) 'apply-installer-migration-error.log'
    for ($attempt = 0; $attempt -lt 120 -and -not (Test-Path -LiteralPath $PortableRestart); $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $PortableRestart) -or -not (Test-Path -LiteralPath $fallbackError)) {
        throw 'Failed installer handoff did not reopen portable OpenWand with diagnostics.'
    }
    if ((Get-Content -LiteralPath (Join-Path $InstallRoot '_internal\version.txt') -Raw).Trim() -ne 'bridge-fallback') {
        throw 'Installer failure lost the updated portable files.'
    }
    for ($attempt = 0; $attempt -lt 40 -and (Test-Path -LiteralPath $WorkRoot); $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (Test-Path -LiteralPath $WorkRoot) { throw 'Fallback bridge left its extraction folder.' }
    Write-Host 'ZIP bridge handed off to the verified installer, and installer failure reopened the portable copy.'
} finally {
    Remove-Item Env:OPENWAND_UPDATE_MANIFEST_URL, Env:OW_TEST_MIGRATION_REPORT, Env:OW_TEST_PROBE_SOURCE, Env:OW_TEST_PROBE_EXE, Env:OW_TEST_PORTABLE_RESTART -ErrorAction SilentlyContinue
    $resolved = [IO.Path]::GetFullPath($Root)
    if (-not $resolved.StartsWith($TempRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolved) -notlike 'OpenWandZipAutoInstaller-*') {
        throw "Unsafe cleanup target: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
}
