param(
    [ValidateSet('install','check','restore')][string]$Mode = 'install',
    [string]$CodexHome,
    [string]$Project,
    [string]$Backup
)
$ErrorActionPreference = 'Stop'
$pythonExe = $null
$pythonPrefix = @()
foreach ($candidate in @('py','python')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($command) {
        $prefix = @()
        if ($candidate -eq 'py') { $prefix = @('-3') }
        & $command.Source @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
        if ($LASTEXITCODE -eq 0) { $pythonExe=$command.Source; $pythonPrefix=$prefix; break }
    }
}
if (-not $pythonExe) { throw 'Python 3.10+ is required. Install Python, then run this entry again.' }
$taskArgs = @('-B',(Join-Path $PSScriptRoot 'portable.py'),$Mode)
if ($CodexHome) { $taskArgs += @('--codex-home',$CodexHome) }
if ($Project) { $taskArgs += @('--project',$Project) }
if ($Backup) { $taskArgs += @('--backup',$Backup) }
& $pythonExe @pythonPrefix @taskArgs
exit $LASTEXITCODE
