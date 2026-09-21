[CmdletBinding()]
param(
    [string]$BatchDir = 'data_submissions/wechat_mp/2026-09-21_wechatmp02',
    [ValidateSet('auto', 'csv', 'jsonl')]
    [string]$Source = 'auto',
    [string]$Config = '',
    [string]$PythonExe = '',
    [switch]$ConvertOnly,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not [IO.Path]::IsPathRooted($BatchDir)) {
    $BatchDir = Join-Path $repoRoot $BatchDir
}
if (-not (Test-Path -LiteralPath $BatchDir -PathType Container)) {
    throw 'Batch directory does not exist. Supply -BatchDir with an existing batch.'
}
if (-not $PythonExe) {
    $PythonExe = Join-Path $repoRoot '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw 'Python environment not found. Supply -PythonExe with the project Python executable.'
}
if ($Config -and -not [IO.Path]::IsPathRooted($Config)) {
    $Config = Join-Path $repoRoot $Config
}
if (-not $ConvertOnly -and -not $DryRun) {
    if (-not $env:POMS_URL -or -not $env:POMS_API_KEY) {
        throw 'Set POMS_URL and POMS_API_KEY in the local environment before uploading.'
    }
}
$pythonArgs = @(
    (Join-Path $PSScriptRoot 'upload_wechat_mp_poms.py'),
    '--batch-dir', $BatchDir, '--convert', '--source', $Source,
    '--samples-dir', (Join-Path $repoRoot 'batch_test_samples')
)
if ($Config) { $pythonArgs += @('--config', $Config) }
if ($ConvertOnly) { $pythonArgs += '--convert-only' }
if ($DryRun) { $pythonArgs += '--dry-run' }
& $PythonExe @pythonArgs
if ($LASTEXITCODE -ne 0) {
    throw "POMS conversion/upload failed (exit $LASTEXITCODE). No automatic retry."
}
