# Exercise the signed release installer against a clean per-user install on CI.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [string]$PreviousInstallerPath = ''
)

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
$Uninstaller = Join-Path $Install 'unins000.exe'
$Python = Join-Path $PSScriptRoot '..\.venv-build\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { $Python = 'python' }
$PreservedFiles = @{}
try {
    $InstallLog = Join-Path $Root 'install.log'
    $InstallArgs = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$Install`"", "/LOG=`"$InstallLog`"")
    if ($PreviousInstallerPath) {
        $PreviousInstaller = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
        if ((Get-AuthenticodeSignature -LiteralPath $PreviousInstaller).Status -ne 'Valid') {
            throw 'The previous installer lacks a valid Authenticode signature.'
        }
        $Previous = Start-Process -FilePath $PreviousInstaller -ArgumentList $InstallArgs -PassThru -Wait -WindowStyle Hidden
        if ($Previous.ExitCode -ne 0) { throw "Previous installer failed: $($Previous.ExitCode)" }
        $OldEntry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction Stop
        if ([IO.Path]::GetFullPath($OldEntry.InstallLocation).TrimEnd('\') -ine $Install.TrimEnd('\')) {
            throw 'Previous installation registered an unexpected directory.'
        }
        $Data = Join-Path $Root 'profile\OpenWand'
        $env:OPENWAND_DATA_ROOT = $Data
        $env:OPENWAND_USER_DATA_DIR = $Data
        $env:OPENWAND_SETTINGS_ENV_PATH = Join-Path $Data '.env'
        foreach ($Relative in @('.env', 'chats\upgrade-marker.txt', 'memory\upgrade-marker.txt', 'addons\upgrade-marker.txt')) {
            $Fixture = Join-Path $Data $Relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $Fixture) -Force | Out-Null
            Set-Content -LiteralPath $Fixture -Value 'BUBBLE_WIDTH=340'
            $PreservedFiles[$Fixture] = (Get-FileHash -LiteralPath $Fixture -Algorithm SHA256).Hash
        }
        Write-Host "Testing in-place upgrade from $($OldEntry.DisplayVersion)."
    }
    $Process = Start-Process -FilePath $Installer -ArgumentList $InstallArgs -PassThru -Wait -WindowStyle Hidden
    if ($Process.ExitCode -ne 0) { throw "Installer failed: $($Process.ExitCode). See $InstallLog" }

    $Entry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction Stop
    $ExpectedVersion = (& $Python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])').Trim()
    if ($LASTEXITCODE -ne 0 -or $Entry.DisplayVersion -ne $ExpectedVersion) {
        throw "Installed version $($Entry.DisplayVersion) does not match $ExpectedVersion."
    }
    if ([System.IO.Path]::GetFullPath($Entry.InstallLocation).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($Install).TrimEnd('\')) {
        throw 'Windows uninstall registration points to the wrong location.'
    }
    foreach ($Fixture in $PreservedFiles.Keys) {
        if (-not (Test-Path -LiteralPath $Fixture) -or
            (Get-FileHash -LiteralPath $Fixture -Algorithm SHA256).Hash -ne $PreservedFiles[$Fixture]) {
            throw "In-place upgrade changed retained user data: $Fixture"
        }
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
    & $Python -c 'import os; from pathlib import Path; from core import uninstaller; plan = uninstaller.build_uninstall_plan(platform="win32", frozen=True, executable=os.environ["OPENWAND_INSTALLER_SMOKE_EXE"]); assert plan.registered_uninstaller == Path(os.environ["OPENWAND_INSTALLER_SMOKE_EXE"]).parent / "unins000.exe"'
    if ($LASTEXITCODE -ne 0) { throw 'The in-app uninstall plan could not resolve Inno registration.' }
    & $Python scripts/run_launcher_smoke.py --kind packaged --executable $InstalledExe --timeout 240
    if ($LASTEXITCODE -ne 0) { throw 'Installed OpenWand did not reach launcher readiness.' }

    # Exercise the actual frozen entry point, which does not accept CPython -c.
    $CheckSource = Join-Path $Root 'must-not-execute.py'
    Set-Content -LiteralPath $CheckSource -Value "raise RuntimeError('Syntax validation must never execute this file')"
    $CheckProcess = Start-Process -FilePath $InstalledExe -ArgumentList @(
        '-m', 'runtime.workers.workspace_check', 'python_syntax', "`"$CheckSource`""
    ) -PassThru -Wait -WindowStyle Hidden
    if ($CheckProcess.ExitCode -ne 0 -or (Test-Path -LiteralPath (Join-Path $Root '__pycache__'))) {
        throw 'The installed syntax-check worker failed or wrote bytecode into the workspace.'
    }
    Set-Content -LiteralPath $CheckSource -Value 'def broken(:'
    $InvalidCheck = Start-Process -FilePath $InstalledExe -ArgumentList @(
        '-m', 'runtime.workers.workspace_check', 'python_syntax', "`"$CheckSource`""
    ) -PassThru -Wait -WindowStyle Hidden
    if ($InvalidCheck.ExitCode -ne 1) { throw 'Invalid syntax did not produce a controlled worker failure.' }
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
