param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectName,
    [string]$ShortDramaRoot = ""
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ShortDramaRoot)) {
    $ShortDramaRoot = Split-Path -Parent $PSScriptRoot
}
$script = Join-Path $PSScriptRoot "tools\init_project.py"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "缺少初始化工具：$script"
}
$python = Get-Command python -ErrorAction Stop
& $python.Source $script --root $ShortDramaRoot --project-name $ProjectName
if ($LASTEXITCODE -ne 0) {
    throw "初始化未完成，退出码：$LASTEXITCODE。原有项目文件不会被覆盖。"
}
