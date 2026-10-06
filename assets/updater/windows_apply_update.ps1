param(
    [string]$Archive = '',
    [string]$InstallRoot = '',
    [string]$Candidate = '',
    [string]$RestartTarget = '',
    [string]$BackupRoot = '',
    [string]$WorkRoot = '',
    [string]$SingleInstanceLock = '',
    [switch]$Deferred
)

$ErrorActionPreference = "Stop"
if ($Deferred) {
    $Archive = $env:OPENWAND_BRIDGE_ARCHIVE
    $InstallRoot = $env:OPENWAND_BRIDGE_INSTALL_ROOT
    $Candidate = $env:OPENWAND_BRIDGE_CANDIDATE
    $RestartTarget = $env:OPENWAND_BRIDGE_RESTART_TARGET
    $BackupRoot = $env:OPENWAND_BRIDGE_BACKUP_ROOT
    $WorkRoot = $env:OPENWAND_BRIDGE_WORK_ROOT
    $SingleInstanceLock = $env:OPENWAND_BRIDGE_SINGLE_INSTANCE_LOCK
}
foreach ($required in @($Archive, $InstallRoot, $Candidate, $RestartTarget, $BackupRoot, $WorkRoot)) {
    if (-not $required) { throw 'The bridge update helper is missing a required path.' }
}
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$BackupRoot = [System.IO.Path]::GetFullPath($BackupRoot).TrimEnd('\')
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot).TrimEnd('\')
if ($BackupRoot -ine "$InstallRoot.previous-update" -or
    $WorkRoot -ieq $InstallRoot -or
    $InstallRoot.StartsWith($WorkRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
    $WorkRoot.StartsWith($InstallRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The bridge update helper received unsafe backup or work paths.'
}
$ArchiveParent = [System.IO.Path]::GetDirectoryName($Archive)
$RestartParent = [System.IO.Path]::GetDirectoryName($RestartTarget)
$ErrorLog = Join-Path $ArchiveParent "apply-bridge-error.log"
$Phase = 'waiting for the old updater to close'
$BackupComplete = $false
$UninstallBatch = 'Uninstall OpenWand.bat'

if (-not $Deferred) {
    try {
        # The released ZIP updater runs this helper synchronously from inside
        # the portable app. Wait for it to exit before replacing packaged files.
        $worker = Join-Path $ArchiveParent ("apply-bridge-worker-" + [guid]::NewGuid().ToString('N') + '.ps1')
        Copy-Item -LiteralPath $PSCommandPath -Destination $worker -Force
        $env:OPENWAND_BRIDGE_ARCHIVE = $Archive
        $env:OPENWAND_BRIDGE_INSTALL_ROOT = $InstallRoot
        $env:OPENWAND_BRIDGE_CANDIDATE = $Candidate
        $env:OPENWAND_BRIDGE_RESTART_TARGET = $RestartTarget
        $env:OPENWAND_BRIDGE_BACKUP_ROOT = $BackupRoot
        $env:OPENWAND_BRIDGE_WORK_ROOT = $WorkRoot
        $env:OPENWAND_BRIDGE_SINGLE_INSTANCE_LOCK = $SingleInstanceLock
        Start-Process -FilePath 'powershell.exe' -ArgumentList @(
            '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', "`"$worker`"", '-Deferred'
        ) -WorkingDirectory $ArchiveParent -WindowStyle Hidden -ErrorAction Stop | Out-Null
        exit 0
    } catch {
        "Could not start deferred bridge update.`n$($_ | Out-String)" | Set-Content -LiteralPath $ErrorLog
        exit 1
    }
}

Set-Location -LiteralPath $ArchiveParent

function Wait-ForPortableProcessesToExit {
    $expected = [System.IO.Path]::GetFullPath($RestartTarget)
    $deadline = (Get-Date).AddMinutes(2)
    do {
        $running = @(
            Get-Process -Name OpenWand -ErrorAction SilentlyContinue | Where-Object {
                try {
                    $_.Path -and [System.IO.Path]::GetFullPath($_.Path) -ieq $expected
                } catch {
                    $false
                }
            }
        )
        if ($running.Count -eq 0) {
            Start-Sleep -Seconds 1
            return
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for old OpenWand processes to exit: $(($running | ForEach-Object Id) -join ', ')."
}

function Copy-PackagedDirectory {
    param([string]$Source, [string]$Destination)
    & robocopy.exe $Source $Destination /MIR /XJ /R:5 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Could not copy packaged files from '$Source' to '$Destination' (robocopy exit code $LASTEXITCODE)."
    }
}

function Restore-Backup {
    if ($BackupComplete) {
        Copy-PackagedDirectory -Source (Join-Path $BackupRoot '_internal') -Destination (Join-Path $InstallRoot '_internal')
        Copy-Item -LiteralPath (Join-Path $BackupRoot 'OpenWand.exe') -Destination (Join-Path $InstallRoot 'OpenWand.exe') -Force
        $oldBatch = Join-Path $BackupRoot $UninstallBatch
        $installedBatch = Join-Path $InstallRoot $UninstallBatch
        if (Test-Path -LiteralPath $oldBatch) {
            Copy-Item -LiteralPath $oldBatch -Destination $installedBatch -Force
        } elseif (Test-Path -LiteralPath $installedBatch) {
            Remove-Item -LiteralPath $installedBatch -Force
        }
    }
}

function Invoke-InstallerMigration {
    # v0.11.1 can only apply a ZIP. The bridge completes the same update with
    # the signed installer so the user does not need a second Settings action.
    $installerHelper = Join-Path $InstallRoot '_internal\assets\updater\windows_apply_installer.ps1'
    if (-not (Test-Path -LiteralPath $installerHelper -PathType Leaf)) { return $false }

    $manifestUrl = $env:OPENWAND_UPDATE_MANIFEST_URL
    if (-not $manifestUrl) {
        $manifestUrl = 'https://github.com/SunnyLich/OpenWand/releases/latest/download/openwand-release-manifest.json'
    }
    $manifestUri = [uri]$manifestUrl
    if ($manifestUri.Scheme -eq 'file') {
        $manifest = Get-Content -LiteralPath $manifestUri.LocalPath -Raw | ConvertFrom-Json
    } elseif ($manifestUri.Scheme -eq 'https') {
        $manifest = Invoke-RestMethod -Uri $manifestUri -TimeoutSec 30
    } else {
        throw 'The update manifest must use HTTPS or a local test file.'
    }
    $bridgeHash = [string]$manifest.assets.'windows-x64'.sha256
    if ($bridgeHash -notmatch '^[0-9a-fA-F]{64}$' -or
        (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ine $bridgeHash) {
        return $false
    }
    $asset = $manifest.assets.'windows-x64-installer'
    if (-not $asset) { return $false }
    $name = [string]$asset.name
    $expectedHash = [string]$asset.sha256
    $assetUrl = [string]$asset.url
    if (-not $name.EndsWith('.exe', [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($name) -cne $name -or
        $expectedHash -notmatch '^[0-9a-fA-F]{64}$') {
        throw 'The release manifest has an invalid Windows installer entry.'
    }
    $assetUri = [uri]$assetUrl
    if ($assetUri.Scheme -notin @('https', 'file')) {
        throw 'The Windows installer URL must use HTTPS or a local test file.'
    }
    $installer = Join-Path $ArchiveParent $name
    $verified = (Test-Path -LiteralPath $installer -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ieq $expectedHash)
    if (-not $verified) {
        $partial = "$installer.partial"
        $client = $null
        try {
            $client = New-Object System.Net.WebClient
            $client.DownloadFile($assetUri, $partial)
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ine $expectedHash) {
                throw 'The downloaded installer does not match the release manifest.'
            }
            Move-Item -LiteralPath $partial -Destination $installer -Force
        } finally {
            Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
            if ($client) { $client.Dispose() }
        }
    }
    $status = Join-Path $ArchiveParent 'apply-installer-status.txt'
    $addons = Join-Path ([IO.Path]::GetDirectoryName($ArchiveParent)) 'addons'
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $installerHelper `
        -Installer $installer -ExpectedSha256 $expectedHash -WaitPid 0 `
        -CurrentExecutable $RestartTarget -SingleInstanceLock $SingleInstanceLock `
        -StatusPath $status -PortableRoot $InstallRoot -UserAddonsRoot $addons
    if ($LASTEXITCODE -ne 0) { throw "The signed installer failed. See $status" }
    return $true
}

try {
    # The released wrapper reports completion and exits after this helper returns.
    # Its current directory can keep packaged files open until that final exit.
    Start-Sleep -Seconds 2
    $Phase = 'checking extracted update'
    if (-not (Test-Path -LiteralPath $Candidate)) {
        throw "Could not find the extracted OpenWand app folder."
    }
    foreach ($requiredItem in @('OpenWand.exe', '_internal')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Candidate $requiredItem))) {
            throw "The extracted update is missing $requiredItem."
        }
    }
    $unexpected = @(Get-ChildItem -LiteralPath $Candidate -Force | Where-Object {
        $_.Name -notin @('OpenWand.exe', $UninstallBatch, '_internal')
    })
    if ($unexpected.Count) {
        throw "The extracted update contains unexpected top-level items: $(($unexpected | ForEach-Object Name) -join ', ')."
    }
    $Phase = 'waiting for old processes'
    Wait-ForPortableProcessesToExit
    $Phase = 'backing up packaged files'
    if (Test-Path -LiteralPath $BackupRoot) {
        throw "An earlier update backup still exists at $BackupRoot."
    }
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
    Copy-PackagedDirectory -Source (Join-Path $InstallRoot '_internal') -Destination (Join-Path $BackupRoot '_internal')
    Copy-Item -LiteralPath (Join-Path $InstallRoot 'OpenWand.exe') -Destination (Join-Path $BackupRoot 'OpenWand.exe')
    $oldBatch = Join-Path $InstallRoot $UninstallBatch
    if (Test-Path -LiteralPath $oldBatch) {
        Copy-Item -LiteralPath $oldBatch -Destination (Join-Path $BackupRoot $UninstallBatch)
    }
    $BackupComplete = $true
    $Phase = 'copying new packaged files'
    Copy-PackagedDirectory -Source (Join-Path $Candidate '_internal') -Destination (Join-Path $InstallRoot '_internal')
    $newBatch = Join-Path $Candidate $UninstallBatch
    if (Test-Path -LiteralPath $newBatch) {
        Copy-Item -LiteralPath $newBatch -Destination $oldBatch -Force
    } elseif (Test-Path -LiteralPath $oldBatch) {
        Remove-Item -LiteralPath $oldBatch -Force
    }
    Copy-Item -LiteralPath (Join-Path $Candidate 'OpenWand.exe') -Destination $RestartTarget -Force
    $Phase = 'finishing update'
    Get-ChildItem Env:OPENWAND_BRIDGE_* -ErrorAction SilentlyContinue | Remove-Item
    # The Settings worker inherited its old supervisor identity. A restarted
    # app must create a new identity or its workers immediately exit.
    Remove-Item -Path @('Env:OPENWAND_SUPERVISOR_PID', 'Env:OPENWAND_SUPERVISOR_CREATE_TIME') -ErrorAction SilentlyContinue
    $migrated = $false
    try {
        $migrated = Invoke-InstallerMigration
    } catch {
        # The ZIP is already usable. Preserve diagnostics and reopen that copy
        # if the installer download, signature, or installation fails.
        "Automatic installer migration failed; portable OpenWand was reopened.`n$($_ | Out-String)" |
            Set-Content -LiteralPath (Join-Path $ArchiveParent 'apply-installer-migration-error.log')
    }
    if (-not $migrated) {
        Start-Process -FilePath $RestartTarget -WorkingDirectory $RestartParent
    }
    Start-Sleep -Seconds 5
    Remove-Item -LiteralPath $BackupRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
    exit 0
} catch {
    $failure = "Bridge update failed while $Phase.`n$($_ | Out-String)"
    try {
        Restore-Backup
        if ($BackupComplete) {
            Remove-Item -LiteralPath $BackupRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    } catch {
        $failure += "`nRollback also failed:`n$($_ | Out-String)"
    }
    $failure | Set-Content -LiteralPath $ErrorLog
    exit 1
}
