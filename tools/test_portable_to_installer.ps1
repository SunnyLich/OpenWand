# Exercise the shipped portable-to-installer helper with the signed CI setup.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$InstallerPath)

$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$Helper = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\assets\updater\windows_apply_installer.ps1')).Path
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenWand.Desktop_is1'
$ExpectedInstall = Join-Path $env:LOCALAPPDATA 'Programs\OpenWand'
if ((Test-Path -LiteralPath $UninstallKey) -or (Test-Path -LiteralPath $ExpectedInstall)) {
    throw 'Refusing migration smoke test because the default OpenWand install is already present.'
}

$RunId = [guid]::NewGuid().ToString('N')
$Root = Join-Path $env:RUNNER_TEMP "OpenWandMigrationSmoke-$RunId"
$Portable = Join-Path $Root 'portable\OpenWand'
$DataRoot = Join-Path $Root 'user-data\OpenWand'
$Addons = Join-Path $DataRoot 'addons'
$Ready = Join-Path $Root 'installed-ready.json'
$Status = Join-Path $Root 'migration-status.txt'
$SourceAddon = Join-Path $Portable 'addons\custom-addon'
$SourceConflict = Join-Path $Portable 'addons\existing-addon'
$TargetConflict = Join-Path $Addons 'existing-addon'
New-Item -ItemType Directory -Path $SourceAddon, $SourceConflict, $TargetConflict -Force | Out-Null
Set-Content -LiteralPath (Join-Path $Portable 'OpenWand.exe') -Value 'portable backup placeholder'
Set-Content -LiteralPath (Join-Path $SourceAddon 'addon.toml') -Value 'portable add-on'
Set-Content -LiteralPath (Join-Path $SourceConflict 'addon.toml') -Value 'portable version'
Set-Content -LiteralPath (Join-Path $TargetConflict 'addon.toml') -Value 'existing user version'

$env:OPENWAND_DATA_ROOT = $DataRoot
$env:OPENWAND_USER_DATA_DIR = $DataRoot
$env:OPENWAND_LAUNCH_SMOKE_READY_FILE = $Ready
$env:OPENWAND_LAUNCH_SMOKE_EXIT_AFTER_READY = '1'
$env:OPENWAND_LAUNCH_SMOKE_DISABLE_AUTOSTART_SYNC = '1'
$env:OPENWAND_BRAIN_FAKE_LLM = '1'
$env:OPENWAND_RUNTIME_LOG_MODE = 'crash'
$env:OPENWAND_SUPERVISOR_PID = '2147483000'
$env:OPENWAND_SUPERVISOR_CREATE_TIME = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
Remove-Item Env:OPENWAND_ADDONS_DIR -ErrorAction SilentlyContinue

$Uninstaller = Join-Path $ExpectedInstall 'unins000.exe'
try {
    $Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Helper `
        -Installer $Installer -ExpectedSha256 $Hash -WaitPid 2147483000 `
        -CurrentExecutable (Join-Path $Portable 'OpenWand.exe') `
        -SingleInstanceLock (Join-Path $DataRoot 'openwand.lock') `
        -StatusPath $Status -PortableRoot $Portable -UserAddonsRoot $Addons
    if ($LASTEXITCODE -ne 0) {
        throw "Portable migration helper failed: $(Get-Content -LiteralPath $Status -Raw)"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Portable '.openwand-migrated-to-installer') -PathType Leaf)) {
        throw 'The portable backup was not marked as migrated.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Portable 'OpenWand.exe') -PathType Leaf)) {
        throw 'Migration removed the portable backup.'
    }
    if ((Get-Content -LiteralPath (Join-Path $Addons 'custom-addon\addon.toml') -Raw).Trim() -ne 'portable add-on') {
        throw 'The portable user add-on was not copied.'
    }
    if ((Get-Content -LiteralPath (Join-Path $TargetConflict 'addon.toml') -Raw).Trim() -ne 'existing user version') {
        throw 'Migration overwrote an existing user add-on.'
    }
    $Entry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction Stop
    if ([System.IO.Path]::GetFullPath($Entry.InstallLocation).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($ExpectedInstall).TrimEnd('\')) {
        throw 'Migration installed OpenWand outside the registered default location.'
    }
    if (-not (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) {
        throw 'Migration did not register a Windows uninstaller.'
    }
    for ($Attempt = 0; $Attempt -lt 480 -and -not (Test-Path -LiteralPath $Ready -PathType Leaf); $Attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $Ready -PathType Leaf)) {
        throw "The installed app did not reach readiness. See $Status"
    }
    Write-Host 'Portable migration copied add-ons, retained the backup, installed and launched the signed app.'
} finally {
    if ($Uninstaller -and (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) {
        Start-Sleep -Seconds 2
        $Process = Start-Process -FilePath $Uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -PassThru -Wait -WindowStyle Hidden
        if ($Process.ExitCode -ne 0) { throw "Migration cleanup uninstaller failed: $($Process.ExitCode)" }
        for ($Attempt = 0; $Attempt -lt 30 -and (Test-Path -LiteralPath $UninstallKey); $Attempt++) {
            Start-Sleep -Milliseconds 500
        }
        if (Test-Path -LiteralPath $UninstallKey) { throw 'Migration cleanup left Windows uninstall registration.' }
    }
}
