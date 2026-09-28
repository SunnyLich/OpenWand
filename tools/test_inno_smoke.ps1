# Exercise Inno Setup's basic offline install and uninstall lifecycle.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CompilerPath
)

$ErrorActionPreference = 'Stop'
$Compiler = (Resolve-Path -LiteralPath $CompilerPath).Path
$RunId = [guid]::NewGuid().ToString('N')
$Root = Join-Path $env:TEMP "OpenWandInnoSmoke-$RunId"
$Build = Join-Path $Root 'build'
$Install = Join-Path $Root 'installed'
$Payload = Join-Path $Root 'payload.txt'
$Script = Join-Path $Root 'smoke.iss'
$Setup = Join-Path $Build 'OpenWand-Inno-Smoke.exe'
$InstallLog = Join-Path $Root 'install.log'
$DisplayName = "OpenWand Inno Smoke $RunId"

New-Item -ItemType Directory -Path $Build -Force | Out-Null
Set-Content -LiteralPath $Payload -Value 'OpenWand Inno Setup smoke test' -Encoding UTF8
@"
[Setup]
AppId=OpenWand.InnoSmoke.$RunId
AppName=$DisplayName
AppVersion=0.0.1
UninstallDisplayName=$DisplayName
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultDirName={localappdata}\OpenWandInnoSmoke.$RunId
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=$Build
OutputBaseFilename=OpenWand-Inno-Smoke
PrivilegesRequired=lowest
Uninstallable=yes
CreateUninstallRegKey=yes

[Files]
Source: "$Payload"; DestDir: "{app}"; Flags: ignoreversion
"@ | Set-Content -LiteralPath $Script -Encoding UTF8

& $Compiler $Script
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Setup -PathType Leaf)) {
    throw 'Inno Setup compilation failed.'
}

$InstallArgs = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$Install`"", "/LOG=`"$InstallLog`"")
$Process = Start-Process -FilePath $Setup -ArgumentList $InstallArgs -PassThru -Wait -WindowStyle Hidden
if ($Process.ExitCode -ne 0) {
    throw "Silent install failed with exit code $($Process.ExitCode). Log: $InstallLog"
}

$InstalledPayload = Join-Path $Install 'payload.txt'
$Uninstaller = Join-Path $Install 'unins000.exe'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenWand.InnoSmoke.' + $RunId + '_is1'
$Entry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction SilentlyContinue
try {
    if (-not (Test-Path -LiteralPath $InstalledPayload -PathType Leaf)) {
        throw 'The installed payload is missing.'
    }
    if (-not (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) {
        throw 'The generated uninstaller is missing.'
    }
    if ($null -eq $Entry -or $Entry.DisplayName -ne $DisplayName) {
        throw "The Windows uninstall entry is missing or incorrect: $UninstallKey"
    }

    Set-Content -LiteralPath $Payload -Value 'OpenWand Inno Setup smoke test version 2' -Encoding UTF8
    $NextScript = (Get-Content -LiteralPath $Script -Raw).Replace('AppVersion=0.0.1', 'AppVersion=0.0.2')
    Set-Content -LiteralPath $Script -Value $NextScript -Encoding UTF8
    & $Compiler /Q $Script
    if ($LASTEXITCODE -ne 0) {
        throw 'Inno Setup upgrade compilation failed.'
    }
    $Process = Start-Process -FilePath $Setup -ArgumentList $InstallArgs -PassThru -Wait -WindowStyle Hidden
    if ($Process.ExitCode -ne 0) {
        throw "Silent upgrade failed with exit code $($Process.ExitCode). Log: $InstallLog"
    }
    $Entry = Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction SilentlyContinue
    if ($null -eq $Entry -or $Entry.DisplayVersion -ne '0.0.2') {
        throw 'The Windows uninstall entry did not update to version 0.0.2.'
    }
    if ((Get-Content -LiteralPath $InstalledPayload -Raw) -notmatch 'version 2') {
        throw 'The upgraded payload is missing.'
    }
} finally {
    if (Test-Path -LiteralPath $Uninstaller -PathType Leaf) {
        $UninstallArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
        $Process = Start-Process -FilePath $Uninstaller -ArgumentList $UninstallArgs -PassThru -Wait -WindowStyle Hidden
        if ($Process.ExitCode -ne 0) {
            throw "Silent uninstall failed with exit code $($Process.ExitCode)."
        }
    }
}

if (Test-Path -LiteralPath $InstalledPayload) {
    throw 'The payload remains after uninstall.'
}
if (Test-Path -LiteralPath $UninstallKey) {
    throw 'The Windows uninstall entry remains after uninstall.'
}

Write-Output "Inno smoke test passed: silent install, in-place upgrade, Programs entry, and silent uninstall."
Write-Output "Setup=$Setup"
