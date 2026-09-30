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
$ArchiveParent = [System.IO.Path]::GetDirectoryName($Archive)
$RestartParent = [System.IO.Path]::GetDirectoryName($RestartTarget)
$InstallRootLeaf = [System.IO.Path]::GetFileName($InstallRoot)
$BackupRootLeaf = [System.IO.Path]::GetFileName($BackupRoot)
$ErrorLog = Join-Path $ArchiveParent "apply-bridge-error.log"
$Phase = 'waiting for the old updater to close'

if (-not $Deferred) {
    try {
        # The released ZIP updater runs this helper synchronously from a PowerShell
        # process whose current directory is inside the portable app. That process
        # must exit before Windows will rename the app folder.
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

function Move-OldRootToBackup {
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        try {
            Rename-Item -LiteralPath $InstallRoot -NewName $BackupRootLeaf -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq 120) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Restore-Backup {
    if (Test-Path -LiteralPath $BackupRoot) {
        if (Test-Path -LiteralPath $InstallRoot) {
            Remove-Item -LiteralPath $InstallRoot -Recurse -Force
        }
        Rename-Item -LiteralPath $BackupRoot -NewName $InstallRootLeaf
    }
}

try {
    # The released wrapper reports completion and exits after this helper returns.
    # Its current directory keeps the old folder open until that final exit.
    Start-Sleep -Seconds 2
    $Phase = 'checking extracted update'
    if (-not (Test-Path -LiteralPath $Candidate)) {
        throw "Could not find the extracted OpenWand app folder."
    }
    $Phase = 'waiting for old processes'
    Wait-ForPortableProcessesToExit
    $Phase = 'replacing portable files'
    if (Test-Path -LiteralPath $BackupRoot) {
        Remove-Item -LiteralPath $BackupRoot -Recurse -Force
    }
    Move-OldRootToBackup
    Move-Item -LiteralPath $Candidate -Destination $InstallRoot
    $Phase = 'reopening OpenWand'
    Get-ChildItem Env:OPENWAND_BRIDGE_* -ErrorAction SilentlyContinue | Remove-Item
    Start-Process -FilePath $RestartTarget -WorkingDirectory $RestartParent
    Start-Sleep -Seconds 5
    Remove-Item -LiteralPath $BackupRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
    exit 0
} catch {
    $failure = "Bridge update failed while $Phase.`n$($_ | Out-String)"
    try {
        Restore-Backup
    } catch {
        $failure += "`nRollback also failed:`n$($_ | Out-String)"
    }
    $failure | Set-Content -LiteralPath $ErrorLog
    exit 1
}
