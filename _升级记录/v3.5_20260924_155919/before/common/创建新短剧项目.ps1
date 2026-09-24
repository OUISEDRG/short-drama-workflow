param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectName,
    [string]$ShortDramaRoot = "D:\短剧制作"
)

$ErrorActionPreference = "Stop"
$CommonRoot = Join-Path $ShortDramaRoot "_通用短剧工作流"
$ProjectRoot = Join-Path $ShortDramaRoot $ProjectName

if (Test-Path $ProjectRoot) {
    Write-Warning "项目目录已存在：$ProjectRoot"
}
else {
    New-Item -ItemType Directory -Force -Path $ProjectRoot | Out-Null
}

$folders = @("人物","场景","道具","音色","成片","视频提示词")
foreach ($folder in $folders) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $folder) | Out-Null
}

$template = Join-Path $CommonRoot "项目启动说明.template.md"
$target = Join-Path $ProjectRoot "项目启动说明.md"

if (Test-Path $template) {
    Copy-Item -Force $template $target
}
else {
    Write-Warning "没有找到项目启动模板：$template"
}

Write-Host ""
Write-Host "新短剧项目骨架已创建：$ProjectRoot"
Write-Host "请把剧本和世界观文件放入项目根目录，把资产放入对应文件夹。"
Write-Host "然后编辑：$target"
