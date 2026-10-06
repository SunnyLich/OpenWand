# Exercise the signed release installer against a clean per-user install on CI.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$InstallerPath)

$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenWand.Desktop_is1'
if (Test-Path -LiteralPath $UninstallKey) {
    throw 'Refusing installer smoke test while OpenWand is already registered for this user.'
}
if ((Get-AuthenticodeSignature -LiteralPath $Installer).Status -ne 'Valid') {
    throw 'The release installer lacks a valid Authenticode signature.'
}
$RunId = [guid]::NewGuid().ToString('N')
$Root = Join-Path $env:RUNNER_TEMP "OpenWandInstallerSmoke-$RunId"
$Install = Join-Path $Root 'OpenWand'
New-Item -ItemType Directory -Path $Root -Force | Out-Null
$Uninstaller = $null
try {
    $InstallLog = Join-Path $Root 'install.log'
    $InstallArgs = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$Install`"", "/LOG=`"$InstallLog`"")
    $Process = Start-Process -FilePath $Installer -ArgumentList $InstallArgs -PassThru -Wait -WindowStyle Hidden
    if ($Process.ExitCode -ne 0) { throw "Installer failed: $($Process.ExitCode). See $InstallLog" }

    $Entry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction Stop
    if ([System.IO.Path]::GetFullPath($Entry.InstallLocation).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($Install).TrimEnd('\')) {
        throw 'Windows uninstall registration points to the wrong location.'
    }
    $InstalledExe = Join-Path $Install 'OpenWand.exe'
    $Marker = Join-Path $Install '.openwand-installed'
    $Uninstaller = Join-Path $Install 'unins000.exe'
    foreach ($Required in @($InstalledExe, $Marker, $Uninstaller)) {
        if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) { throw "Installed file missing: $Required" }
    }
    if ((Get-AuthenticodeSignature -LiteralPath $Uninstaller).Status -ne 'Valid') {
        throw 'The installed uninstaller lacks a valid Authenticode signature.'
    }
    $env:OPENWAND_INSTALLER_SMOKE_EXE = $InstalledExe
    python -c 'import os; from pathlib import Path; from core import uninstaller; plan = uninstaller.build_uninstall_plan(platform="win32", frozen=True, executable=os.environ["OPENWAND_INSTALLER_SMOKE_EXE"]); assert plan.registered_uninstaller == Path(os.environ["OPENWAND_INSTALLER_SMOKE_EXE"]).parent / "unins000.exe"'
    if ($LASTEXITCODE -ne 0) { throw 'The in-app uninstall plan could not resolve Inno registration.' }
    python scripts/run_launcher_smoke.py --kind packaged --executable $InstalledExe --timeout 240
    if ($LASTEXITCODE -ne 0) { throw 'Installed OpenWand did not reach launcher readiness.' }
} finally {
    if ($Uninstaller -and (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) {
        $Process = Start-Process -FilePath $Uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -PassThru -Wait -WindowStyle Hidden
        if ($Process.ExitCode -ne 0) { throw "Windows uninstaller failed: $($Process.ExitCode)" }
        for ($Attempt = 0; $Attempt -lt 30 -and (Test-Path -LiteralPath $UninstallKey); $Attempt++) {
            Start-Sleep -Milliseconds 500
        }
        if (Test-Path -LiteralPath $UninstallKey) { throw 'Windows uninstall entry remained after removal.' }
    }
}
Write-Host 'Signed installer, installed launcher, and Windows uninstaller smoke test passed.'
