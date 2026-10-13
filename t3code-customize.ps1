# Pass arguments unchanged to the shared CLI; no global execution-policy changes.
$ErrorActionPreference = 'Stop'
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Python 3.9+ is required. Install Python and run this command again.' }
& $python.Source (Join-Path $PSScriptRoot 't3code-customize') @args
exit $LASTEXITCODE
