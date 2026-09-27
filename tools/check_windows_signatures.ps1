# Audit the final bundle, prepare Azure's signing catalog, or gate publication.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BundlePath,
    [ValidateSet('Audit', 'Prepare', 'Verify')][string]$Mode = 'Audit',
    [string]$CatalogPath,
    [string]$ReportPath
)

$ErrorActionPreference = 'Stop'
$BundleRoot = (Resolve-Path -LiteralPath $BundlePath).Path
if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot 'OpenWand.exe') -PathType Leaf)) {
    throw 'BundlePath must contain OpenWand.exe.'
}
if ($Mode -eq 'Prepare' -and -not $CatalogPath) {
    throw 'Prepare requires CatalogPath.'
}

# Python extension modules are DLLs even though their extension is .pyd.
# Batch files cannot be Authenticode-signed; the optional uninstall .bat is
# separate from the executable launch path and is not covered by this gate.
$CodeFiles = @(Get-ChildItem -LiteralPath $BundleRoot -Recurse -File |
    Where-Object { $_.Extension -in '.exe', '.dll', '.pyd', '.ps1', '.psm1' } |
    Sort-Object FullName)
$Unsigned = @()
$Rejected = @()
$Rows = @(foreach ($CodeFile in $CodeFiles) {
    $Signature = Get-AuthenticodeSignature -LiteralPath $CodeFile.FullName
    $RelativePath = $CodeFile.FullName.Substring($BundleRoot.TrimEnd('\').Length + 1)
    $Status = [string]$Signature.Status
    $KeyAlgorithm = if ($Signature.SignerCertificate) { $Signature.SignerCertificate.PublicKey.Oid.Value } else { '' }
    if ($Status -eq 'NotSigned') {
        $Unsigned += $CodeFile.FullName
    } elseif ($Status -ne 'Valid' -or $KeyAlgorithm -ne '1.2.840.113549.1.1.1') {
        # Do not conceal a damaged/untrusted vendor signature by signing over it.
        $Rejected += "$RelativePath ($Status, key algorithm: $KeyAlgorithm)"
    }
    [pscustomobject]@{
        Path = $RelativePath
        Status = $Status
        Signer = if ($Signature.SignerCertificate) { $Signature.SignerCertificate.Subject } else { '' }
        KeyAlgorithm = $KeyAlgorithm
    }
})
if ($ReportPath) {
    $Rows | Export-Csv -LiteralPath $ReportPath -NoTypeInformation -Encoding UTF8
}
Write-Host "Checked $($Rows.Count) code files: $($Unsigned.Count) unsigned, $($Rejected.Count) invalid or unsupported signatures."
if ($Mode -eq 'Audit') {
    $Rows
    return
}
if ($Rejected.Count) {
    throw "Invalid or non-RSA signatures in bundle:`n$($Rejected -join "`n")"
}
if ($Mode -eq 'Verify') {
    if ($Unsigned.Count) {
        throw "Unsigned code in release bundle:`n$($Unsigned -join "`n")"
    }
    return
}

# Azure resolves catalog entries relative to the catalog's directory.
$CatalogFullPath = [System.IO.Path]::GetFullPath($CatalogPath)
$CatalogDirectory = Split-Path -Parent $CatalogFullPath
$CatalogEntries = @($Unsigned | ForEach-Object {
    [System.IO.Path]::GetRelativePath($CatalogDirectory, $_)
})
[System.IO.File]::WriteAllLines($CatalogFullPath, [string[]]$CatalogEntries)
if ($env:GITHUB_OUTPUT) {
    "unsigned-count=$($Unsigned.Count)" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
}
