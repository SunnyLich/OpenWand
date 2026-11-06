# Compile the real installer script with a unique product identity and tiny payload.
# Never touches the user's OpenWand installation, shortcuts, or profile.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CompilerPath,
    [switch]$KeepInstalledForReview
)

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Compiler = (Resolve-Path -LiteralPath $CompilerPath).Path
$RunId = [guid]::NewGuid().ToString('N')
$Root = Join-Path $Repo ".tmp\installer-maintenance-$RunId"
$Bundle = Join-Path $Root 'bundle'
$Install = Join-Path $Root 'installed'
$AppId = "OW.Maint.$RunId"
$Key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\${AppId}_is1"
$ShortcutName = "OpenWand Maintenance Smoke $RunId"
$Script = Join-Path $Root 'OpenWand.iss'
$Output = Join-Path $Root 'output'
New-Item -ItemType Directory -Path $Bundle, $Output -Force | Out-Null
$Source = Get-Content -LiteralPath (Join-Path $Repo 'packaging\windows\OpenWand.iss') -Raw -Encoding UTF8
$Source = $Source.Replace('OpenWand.Desktop', $AppId).Replace(
    'Name: "{autoprograms}\OpenWand"', "Name: `"{autoprograms}\$ShortcutName`"")
$Source = $Source.Replace('AppName=OpenWand', 'AppName=OpenWand (isolated installer test)')
$Source | Set-Content -LiteralPath $Script -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $Repo 'packaging\windows\installed.marker') -Destination $Root
Copy-Item -LiteralPath (Join-Path $Repo 'packaging\windows\InstallerMessages.iss') -Destination $Root
Copy-Item -LiteralPath (Join-Path $Repo 'packaging\windows\languages') -Destination $Root -Recurse
# Not launched: a harmless placeholder suffices for installer file operations.
Set-Content -LiteralPath (Join-Path $Bundle 'OpenWand.exe') -Value 'Maintenance test payload only'
Set-Content -LiteralPath (Join-Path $Bundle 'repair-marker.txt') -Value 'Restored by repair'

function Build-Fixture([string]$Version) {
    & $Compiler '/Q' '/DOpenWandDevelopmentBuild=1' "/DOpenWandBundle=$Bundle" `
        "/DOpenWandVersion=$Version" "/DOpenWandOutput=$Output" $Script | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed for $Version." }
    return Join-Path $Output "OpenWand-dev-v$Version-windows-x64-setup.exe"
}

function Invoke-Fixture([string]$Setup, [string]$Label, [string[]]$Extra = @(), [switch]$ExpectFailure) {
    $Arguments = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$(Join-Path $Root "$Label.log")`"") + $Extra
    $Process = Start-Process -FilePath $Setup -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    if ($ExpectFailure) {
        if ($Process.ExitCode -eq 0) { throw "$Label should have refused installation." }
        $Log = Get-Content -LiteralPath (Join-Path $Root "$Label.log") -Raw -Encoding UTF8
        if ($Log.Contains('Starting the installation process.')) {
            throw "$Label started changing files before refusing installation."
        }
    } elseif ($Process.ExitCode -ne 0) {
        throw "$Label failed with exit $($Process.ExitCode)."
    }
}

function Assert-Version([string]$Expected) {
    $Entry = Get-ItemProperty -LiteralPath $Key -ErrorAction Stop
    if ($Entry.DisplayVersion -ne $Expected -or
        [IO.Path]::GetFullPath($Entry.InstallLocation).TrimEnd('\') -ine $Install.TrimEnd('\')) {
        throw "Unexpected registered version/location: $($Entry.DisplayVersion), $($Entry.InstallLocation)."
    }
}

function Remove-Fixture {
    if (Test-Path -LiteralPath $Key) {
        $Entry = Get-ItemProperty -LiteralPath $Key -ErrorAction Stop
        $ResolvedInstall = [IO.Path]::GetFullPath($Entry.InstallLocation).TrimEnd('\')
        if ($ResolvedInstall -ine $Install.TrimEnd('\') -or
            -not $ResolvedInstall.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to uninstall a copy outside the isolated test directory.'
        }
        $Process = Start-Process -FilePath (Join-Path $Install 'unins000.exe') -ArgumentList @(
            '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/KEEPUSERDATA'
        ) -PassThru -Wait -WindowStyle Hidden
        if ($Process.ExitCode -ne 0 -or (Test-Path -LiteralPath $Key)) { throw 'Fixture uninstall failed.' }
    } elseif (Test-Path -LiteralPath (Join-Path $Install 'unins000.exe')) {
        # Also clean up a partial fixture registration after a failed assertion.
        $Process = Start-Process -FilePath (Join-Path $Install 'unins000.exe') -ArgumentList @(
            '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/KEEPUSERDATA'
        ) -PassThru -Wait -WindowStyle Hidden
        if ($Process.ExitCode -ne 0) { throw 'Partial fixture uninstall failed.' }
    }
}

$Keep = $false
try {
    $Old = Build-Fixture '0.12.2'
    $Current = Build-Fixture '0.12.3'
    $Newer = Build-Fixture '0.12.10'
    Invoke-Fixture $Old 'fresh-install' @("/DIR=`"$Install`"")
    Assert-Version '0.12.2'
    $DataMarker = Join-Path $Root 'retained-user-data.txt'
    Set-Content -LiteralPath $DataMarker -Value 'Keep this data'
    $DataHash = (Get-FileHash -LiteralPath $DataMarker -Algorithm SHA256).Hash

    # No /DIR: prove the registered non-default directory is found automatically.
    Invoke-Fixture $Current 'upgrade-without-dir'
    Assert-Version '0.12.3'
    Remove-Item -LiteralPath (Join-Path $Install 'repair-marker.txt')
    Invoke-Fixture $Current 'repair-without-dir'
    if (-not (Test-Path -LiteralPath (Join-Path $Install 'repair-marker.txt'))) { throw 'Repair did not restore the missing payload.' }
    Assert-Version '0.12.3'

    foreach ($Language in @('en', 'zhHant', 'zh', 'es', 'fr')) {
        Invoke-Fixture $Current "language-$Language" @("/LANG=$Language")
        $LanguageEntry = Get-ItemProperty -LiteralPath $Key -ErrorAction Stop
        if ($LanguageEntry.'Inno Setup: Language' -ne $Language) {
            throw "Installer did not persist the selected language: $Language."
        }
    }

    Invoke-Fixture $Old 'allowed-downgrade'
    $DowngradeLog = Get-Content -LiteralPath (Join-Path $Root 'allowed-downgrade.log') -Raw -Encoding UTF8
    if (-not $DowngradeLog.Contains('Version downgrade: OpenWand 0.12.3 is already installed, but this installer contains 0.12.2.')) {
        throw 'Downgrade warning did not identify both installed and installer versions.'
    }
    Assert-Version '0.12.2'
    Invoke-Fixture $Current 'upgrade-after-downgrade'
    Assert-Version '0.12.3'
    Invoke-Fixture $Current 'blocked-relocation' @("/DIR=`"$(Join-Path $Root 'wrong-location')`"") -ExpectFailure
    Assert-Version '0.12.3'
    if (Test-Path -LiteralPath (Join-Path $Root 'wrong-location\OpenWand.exe')) { throw 'Blocked relocation wrote a second installation.' }
    # Numeric comparison must treat 0.12.10 as newer than 0.12.3.
    Invoke-Fixture $Newer 'numeric-upgrade'
    Assert-Version '0.12.10'
    Invoke-Fixture $Current 'allowed-numeric-downgrade'
    Assert-Version '0.12.3'
    $NumericLog = Get-Content -LiteralPath (Join-Path $Root 'allowed-numeric-downgrade.log') -Raw -Encoding UTF8
    if (-not $NumericLog.Contains('Version downgrade: OpenWand 0.12.10 is already installed, but this installer contains 0.12.3.')) {
        throw 'Numeric downgrade comparison did not identify 0.12.10 as newer than 0.12.3.'
    }
    Set-ItemProperty -LiteralPath $Key -Name DisplayVersion -Value 'unknown'
    Invoke-Fixture $Current 'blocked-unknown-version' @() -ExpectFailure
    Assert-Version 'unknown'
    Set-ItemProperty -LiteralPath $Key -Name DisplayVersion -Value '0.12.3'
    Remove-Fixture
    Invoke-Fixture $Old 'review-baseline' @("/DIR=`"$Install`"")
    if ((Get-FileHash -LiteralPath $DataMarker -Algorithm SHA256).Hash -ne $DataHash) { throw 'Retained data marker changed.' }

    [ordered]@{
        root = $Root; registry_key = $Key; install = $Install
        old_installer = $Old; current_installer = $Current; newer_installer = $Newer
        fresh_install = 'passed'; automatic_directory_upgrade = 'passed'; repair_missing_file = 'passed'
        downgrade_allowed_with_logged_notice = 'passed'; numeric_version_comparison = 'passed'
        installed_languages = @('en', 'zhHant', 'zh', 'es', 'fr')
        unknown_version_blocked = 'passed'; relocation_blocked = 'passed'
        retained_external_marker = 'passed'; native_ui = 'not reviewed by this script'
        keep_installed_for_review = [bool]$KeepInstalledForReview
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root 'result.json') -Encoding UTF8
    $Keep = [bool]$KeepInstalledForReview
    Write-Host "Installer maintenance checks passed. Report: $Root\result.json"
} finally {
    if (-not $Keep) { Remove-Fixture }
}
