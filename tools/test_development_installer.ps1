# Test the real Inno script with an explicitly unsigned local development build.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [string]$PythonPath = '',
    [string]$ReportDirectory = '',
    [switch]$ReviewUninstallDialog
)

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$DevelopmentOutput = [IO.Path]::GetFullPath((Join-Path $Repo 'dist\installer-development')) + '\'
if (-not $Installer.StartsWith($DevelopmentOutput, [StringComparison]::OrdinalIgnoreCase) -or
    (Split-Path -Leaf $Installer) -notlike 'OpenWand-dev-v*-windows-x64-setup.exe') {
    throw 'Only an explicitly named local development installer is accepted.'
}
if (-not $PythonPath) { $PythonPath = Join-Path $Repo '.venv\Scripts\python.exe' }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not $ReportDirectory) { $ReportDirectory = Join-Path $Repo 'reports\development-installer' }
$ReportDirectory = [IO.Path]::GetFullPath($ReportDirectory)
if (-not $ReportDirectory.StartsWith($Repo + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Installer validation reports and disposable installs must stay inside the repository.'
}
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenWand.Desktop_is1'
$Shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'OpenWand.lnk'
if ((Test-Path -LiteralPath $UninstallKey) -or (Test-Path -LiteralPath $Shortcut) -or
    (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\OpenWand'))) {
    throw 'Refusing to test while an existing OpenWand installation or Start Menu shortcut is present.'
}
$Root = Join-Path $ReportDirectory ('install-' + [guid]::NewGuid().ToString('N'))
$Install = Join-Path $Root 'application'
$State = Join-Path $Root 'state'
$Data = Join-Path $State 'data\OpenWand'
$External = Join-Path $Root 'external-provider-model.txt'
New-Item -ItemType Directory -Path $Data -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $State '.user-journey-state') | Out-Null
Set-Content -LiteralPath $External -Value 'External provider data must survive.'

# Every cleanup worker inherits this disposable profile and credential backend.
$env:OPENWAND_DATA_ROOT = $Data
$env:OPENWAND_USER_DATA_DIR = $Data
$env:OPENWAND_SETTINGS_ENV_PATH = Join-Path $Data '.env'
$env:OPENWAND_ADDONS_DIR = Join-Path $Data 'addons'
$env:OPENWAND_SECRET_STATUS_PATH = Join-Path $Data 'private\secret-status.json'
$env:OPENWAND_E2E_STATE = $State
$env:PYTHON_KEYRING_BACKEND = 'scripts.user_journeys.keyring_backend.DisposableKeyring'
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:OPENWAND_LAUNCH_SMOKE_DISABLE_AUTOSTART_SYNC = '1'
$Uninstaller = Join-Path $Install 'unins000.exe'
$JourneyStatus = $null

function Install-TestCopy {
    param([string]$LogName)
    $Process = Start-Process -FilePath $Installer -ArgumentList @(
        '/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
        "/DIR=`"$Install`"", "/LOG=`"$(Join-Path $Root $LogName)`""
    ) -WindowStyle Hidden -PassThru -Wait
    if ($Process.ExitCode -ne 0) { throw "Development install failed: $($Process.ExitCode)" }
    $Entry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction Stop
    if ([IO.Path]::GetFullPath($Entry.InstallLocation).TrimEnd('\') -ine $Install.TrimEnd('\')) {
        throw 'Installer registered an unexpected application directory.'
    }
    foreach ($Required in @('OpenWand.exe', '.openwand-installed', 'unins000.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Install $Required) -PathType Leaf)) {
            throw "Missing installed file: $Required"
        }
    }
}

function Remove-TestCopy {
    param([string[]]$Options = @())
    $Entry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction Stop
    if ([IO.Path]::GetFullPath($Entry.InstallLocation).TrimEnd('\') -ine $Install.TrimEnd('\')) {
        throw 'Refusing to remove an installation outside this test directory.'
    }
    $Process = Start-Process -FilePath $Uninstaller -ArgumentList (@(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    ) + $Options) -WindowStyle Hidden -PassThru -Wait
    if ($Process.ExitCode -ne 0) { throw "Development uninstall failed: $($Process.ExitCode)" }
    for ($Attempt = 0; $Attempt -lt 60 -and (Test-Path -LiteralPath $UninstallKey); $Attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if (Test-Path -LiteralPath $UninstallKey) { throw 'Uninstall registration remained after removal.' }
    if (Test-Path -LiteralPath (Join-Path $Install 'OpenWand.exe')) { throw 'Application remained after uninstall.' }
    if (-not (Test-Path -LiteralPath $External)) { throw 'External provider data was removed.' }
}

try {
    Install-TestCopy 'install.log'
    # Exercise the installed executable, not the source runtime or a startup stub.
    & $PythonPath -m scripts.user_journeys --executable (Join-Path $Install 'OpenWand.exe') `
        --output (Join-Path $Root 'user-journeys') --timeout 480
    $JourneyStatus = $LASTEXITCODE
    if ($ReviewUninstallDialog) {
        @{ uninstaller = $Uninstaller; install = $Install } | ConvertTo-Json |
            Set-Content -LiteralPath (Join-Path $ReportDirectory 'ui-review-ready.json') -Encoding utf8
        Write-Host 'Installed journeys finished; waiting for the cancel-only uninstall dialog review.'
        $Deadline = (Get-Date).AddMinutes(5)
        while (-not (Test-Path -LiteralPath (Join-Path $ReportDirectory 'ui-review-complete.json'))) {
            if ((Get-Date) -gt $Deadline) { throw 'Uninstall dialog review timed out.' }
            Start-Sleep -Milliseconds 250
        }
    }
    Set-Content -LiteralPath (Join-Path $Data 'keep-on-reinstall.txt') -Value 'Retained data'
    foreach ($Relative in @('.env', 'chats\test.json', 'memory\test.json', 'addons\fixture\addon.toml', 'python_packages\fixture.txt')) {
        $Fixture = Join-Path $Data $Relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $Fixture) -Force | Out-Null
        Set-Content -LiteralPath $Fixture -Value 'Installer lifecycle fixture'
    }
    & $PythonPath -c 'import keyring; keyring.set_password("python-ai-overlay", "github-oauth", "installer-test-credential")'
    if ($LASTEXITCODE -ne 0) { throw 'Could not seed the disposable credential store.' }
    Remove-TestCopy
    if (-not (Test-Path -LiteralPath (Join-Path $Data 'keep-on-reinstall.txt'))) {
        throw 'Default uninstall erased saved data.'
    }
    Install-TestCopy 'reinstall.log'
    if ((Get-Content -LiteralPath (Join-Path $Data 'keep-on-reinstall.txt') -Raw).Trim() -ne 'Retained data') {
        throw 'Reinstall failed to preserve saved data.'
    }
    & $PythonPath -c 'import keyring; assert keyring.get_password("python-ai-overlay", "github-oauth") == "installer-test-credential"'
    if ($LASTEXITCODE -ne 0) { throw 'Default uninstall or reinstall lost saved credentials.' }
    Remove-TestCopy @('/REMOVEUSERDATA', '/KEEPUSERDATA')
    if (-not (Test-Path -LiteralPath (Join-Path $Data 'keep-on-reinstall.txt'))) {
        throw '/KEEPUSERDATA did not take precedence over /REMOVEUSERDATA.'
    }
    Install-TestCopy 'reinstall-after-keep-override.log'
    $env:OPENWAND_USER_JOURNEYS = '1' # Separate mutex for noninteractive cleanup only.
    Remove-TestCopy @('/REMOVEUSERDATA')
    if (Test-Path -LiteralPath $Data) { throw 'Explicit data removal left user data behind.' }
    & $PythonPath -c 'import keyring; assert keyring.get_password("python-ai-overlay", "github-oauth") is None'
    if ($LASTEXITCODE -ne 0) { throw 'Explicit removal left saved credentials behind.' }
    $Result = [ordered]@{
        installer = $Installer; sha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
        unsigned_development_build = $true; install = 'passed'; default_keep_data = 'passed'
        reinstall = 'passed'; explicit_remove_data_and_credentials = 'passed'
        keep_data_switch_precedence = 'passed'
        external_provider_preserved = $true; packaged_journeys_exit_code = $JourneyStatus
        report = (Join-Path $Root 'user-journeys\report.md')
    }
    $Result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ReportDirectory 'installer-result.json') -Encoding utf8
    if ($JourneyStatus -ne 0) { throw 'Packaged user journeys failed; see the retained report.' }
} finally {
    # Never leave a test registration that could confuse a real later install.
    if ((Test-Path -LiteralPath $UninstallKey) -and (Test-Path -LiteralPath $Uninstaller)) {
        Remove-TestCopy @('/KEEPUSERDATA')
    }
}
Write-Host "Development installer lifecycle and packaged journeys passed. Reports: $ReportDirectory"
