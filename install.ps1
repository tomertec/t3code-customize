# Run from an extracted Windows package, or download this bootstrap after publication.
$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows is required.' }
$entry = Join-Path $PSScriptRoot 't3code-customize.ps1'
if (-not (Test-Path -LiteralPath $entry)) {
    $checkout = Join-Path $env:LOCALAPPDATA 't3code-customize\repo'
    if (Test-Path -LiteralPath (Join-Path $checkout '.git')) {
        & git -C $checkout pull --ff-only
    } else {
        & git clone https://github.com/tomertec/t3code-customize.git $checkout
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not download t3code-customize.' }
    $entry = Join-Path $checkout 't3code-customize.ps1'
    if (-not (Test-Path -LiteralPath $entry)) { throw 'The downloaded branch does not contain Windows support yet. Use the prepared Windows package.' }
}
$installerArgs = @($args)
$bundles = Join-Path $PSScriptRoot 'customized-bundles.zip'
if ($installerArgs.Count -eq 0 -and (Test-Path -LiteralPath $bundles)) {
    $installerArgs = @('install', '--bundles', $bundles, '--no-pull')
}
& $entry @installerArgs
exit $LASTEXITCODE
