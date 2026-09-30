# Apply a signed Inno release after all OpenWand processes have exited.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][int]$WaitPid,
    [Parameter(Mandatory = $true)][string]$CurrentExecutable,
    [Parameter(Mandatory = $true)][string]$SingleInstanceLock,
    [Parameter(Mandatory = $true)][string]$StatusPath,
    [string]$PortableRoot = '',
    [string]$UserAddonsRoot = ''
)

$ErrorActionPreference = 'Stop'

function Test-OpenWandLockReleased {
    $stream = $null
    try {
        $parent = [System.IO.Path]::GetDirectoryName($SingleInstanceLock)
        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        $stream = [System.IO.File]::Open(
            $SingleInstanceLock,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::ReadWrite
        )
        $stream.Lock(0, 1)
        $stream.Unlock(0, 1)
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

function Wait-For-OpenWandExit {
    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) -and (Test-OpenWandLockReleased)) {
            Start-Sleep -Seconds 1
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'Timed out waiting for OpenWand to close.'
}

function Copy-PortableAddons {
    if (-not $PortableRoot) { return }
    $source = Join-Path $PortableRoot 'addons'
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { return }
    New-Item -ItemType Directory -Path $UserAddonsRoot -Force | Out-Null
    $conflicts = New-Object System.Collections.Generic.List[string]
    foreach ($item in Get-ChildItem -LiteralPath $source -Force) {
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { continue }
        $target = Join-Path $UserAddonsRoot $item.Name
        if (Test-Path -LiteralPath $target) {
            $conflicts.Add($item.Name)
            continue
        }
        Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
    }
    if ($conflicts.Count) {
        Add-Content -LiteralPath $StatusPath -Value (
            'Existing add-ons kept in user data; portable copies remain in the old folder: ' +
            ($conflicts -join ', ')
        )
    }
}

try {
    $statusDir = [System.IO.Path]::GetDirectoryName($StatusPath)
    New-Item -ItemType Directory -Path $statusDir -Force | Out-Null
    Set-Content -LiteralPath $StatusPath -Value 'Waiting for OpenWand to close.'
    Wait-For-OpenWandExit

    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
        throw 'The downloaded installer is missing.'
    }
    $actualHash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
    if ($actualHash -ine $ExpectedSha256) {
        throw 'The downloaded installer no longer matches the release manifest.'
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Installer
    if ($signature.Status -ne 'Valid') {
        throw "The installer signature is not valid: $($signature.Status)."
    }

    if ($PortableRoot) {
        $portablePath = [System.IO.Path]::GetFullPath($PortableRoot).TrimEnd('\')
        $defaultInstall = [System.IO.Path]::GetFullPath(
            (Join-Path $env:LOCALAPPDATA 'Programs\OpenWand')
        ).TrimEnd('\')
        if ($portablePath -ieq $defaultInstall) {
            throw 'The portable copy is in the installer destination. Move the portable folder before switching so it can remain as a backup.'
        }
    }

    Copy-PortableAddons
    Add-Content -LiteralPath $StatusPath -Value 'Running signed installer.'
    $installLog = Join-Path $statusDir 'inno-update.log'
    $arguments = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$installLog`"")
    $process = Start-Process -FilePath $Installer -ArgumentList $arguments -PassThru -Wait -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Installer failed with exit code $($process.ExitCode). See $installLog"
    }

    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenWand.Desktop_is1'
    $entry = Get-ItemProperty -LiteralPath $uninstallKey -ErrorAction Stop
    $installedExe = Join-Path $entry.InstallLocation 'OpenWand.exe'
    $marker = Join-Path $entry.InstallLocation '.openwand-installed'
    if (-not (Test-Path -LiteralPath $installedExe -PathType Leaf) -or
        -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw 'Installer finished but the registered OpenWand copy is incomplete.'
    }
    Add-Content -LiteralPath $StatusPath -Value "Installed: $installedExe"
    if ($PortableRoot) {
        try {
            Set-Content -LiteralPath (Join-Path $PortableRoot '.openwand-migrated-to-installer') `
                -Value "Installed OpenWand: $installedExe`nUse the installed copy to uninstall; both copies share user data."
        } catch {
            Add-Content -LiteralPath $StatusPath -Value ("Could not mark portable backup: " + $_.Exception.Message)
        }
    }
    Start-Process -FilePath $installedExe -WorkingDirectory ([System.IO.Path]::GetDirectoryName($installedExe))
    exit 0
} catch {
    Add-Content -LiteralPath $StatusPath -Value ("Installer update failed: " + $_.Exception.Message)
    exit 1
}
