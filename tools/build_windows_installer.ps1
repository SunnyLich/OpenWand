# Build the offline Inno installer around Azure's separate Authenticode signing steps.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Prepare', 'Complete')][string]$Phase,
    [string]$CompilerPath = ''
)

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Bundle = Join-Path $Repo 'dist\OpenWand'
$Output = Join-Path $Repo 'dist\installer'
$Signing = Join-Path $Repo 'dist\installer-signing'
$UninstallerForAzure = Join-Path $Signing 'openwand-uninstaller.exe'
$Script = Join-Path $Repo 'packaging\windows\OpenWand.iss'
$Version = (& python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])').Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { throw 'Could not read the OpenWand version.' }
if (-not (Test-Path -LiteralPath (Join-Path $Bundle 'OpenWand.exe') -PathType Leaf)) {
    throw 'The signed PyInstaller bundle is missing.'
}
New-Item -ItemType Directory -Path $Output, $Signing -Force | Out-Null

if (-not $CompilerPath) {
    $InnoDir = Join-Path $env:RUNNER_TEMP 'OpenWand-Inno-6.7.3'
    $CompilerPath = Join-Path $InnoDir 'ISCC.exe'
    if ($Phase -eq 'Prepare' -and -not (Test-Path -LiteralPath $CompilerPath -PathType Leaf)) {
        $Download = Join-Path $env:RUNNER_TEMP 'innosetup-6.7.3.exe'
        Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $Download
        $Expected = '9C73C3BAE7ED48D44112A0F48E66742C00090BDB5BEF71D9D3C056C66E97B732'
        if ((Get-FileHash -LiteralPath $Download -Algorithm SHA256).Hash -ne $Expected) {
            throw 'Inno Setup 6.7.3 download does not match the pinned SHA256.'
        }
        $Installer = Start-Process -FilePath $Download -ArgumentList @(
            '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$InnoDir`""
        ) -PassThru -Wait -WindowStyle Hidden
        if ($Installer.ExitCode -ne 0) { throw "Inno Setup bootstrap failed: $($Installer.ExitCode)" }
    }
}
$Compiler = (Resolve-Path -LiteralPath $CompilerPath).Path
$UninstallerCache = Join-Path $Output 'signed-uninstaller'
$CompilerArgs = @(
    '/Q', "/DOpenWandBundle=$Bundle", "/DOpenWandVersion=$Version", "/DOpenWandOutput=$Output", $Script
)

if ($Phase -eq 'Prepare') {
    & $Compiler @CompilerArgs
    if ($LASTEXITCODE -ne 2) {
        throw "Expected Inno's request to sign the generated uninstaller (exit 2); got $LASTEXITCODE."
    }
    $Generated = @(Get-ChildItem -LiteralPath $UninstallerCache -Filter 'uninst-*.e32' -File)
    if ($Generated.Count -ne 1) { throw "Expected one generated uninstaller; got $($Generated.Count)." }
    Copy-Item -LiteralPath $Generated[0].FullName -Destination $UninstallerForAzure -Force
    Write-Host "Prepared uninstaller for Azure signing: $UninstallerForAzure"
    exit 0
}

if ((Get-AuthenticodeSignature -LiteralPath $UninstallerForAzure).Status -ne 'Valid') {
    throw 'Azure did not produce a valid signed uninstaller.'
}
$Generated = @(Get-ChildItem -LiteralPath $UninstallerCache -Filter 'uninst-*.e32' -File)
if ($Generated.Count -ne 1) { throw "Expected one generated uninstaller; got $($Generated.Count)." }
Copy-Item -LiteralPath $UninstallerForAzure -Destination $Generated[0].FullName -Force
& $Compiler @CompilerArgs
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed: $LASTEXITCODE" }
$Setup = Join-Path $Output "OpenWand-v$Version-windows-x64-setup.exe"
if (-not (Test-Path -LiteralPath $Setup -PathType Leaf)) { throw 'Inno Setup produced no installer.' }
if ($env:GITHUB_ENV) {
    "OPENWAND_INSTALLER_PATH=$Setup" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
}
Write-Host "Installer ready for Azure signing: $Setup"
