#Requires -Version 5.1
<#
.SYNOPSIS
  打包 private_robot 便携版，供他人解压后「首次安装.bat → 启动桌宠.bat」

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1
  powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1 -Version 0.2.0
#>
param(
    [string]$Version = "0.2.0",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $OutDir) {
    $OutDir = Join-Path $Root "dist"
}

$StageName = "private_robot-$Version"
$Stage = Join-Path $OutDir $StageName
$ZipPath = Join-Path $OutDir "$StageName-win64.zip"

$ExcludeDirNames = @(
    ".git", ".venv", ".cursor", ".claude", ".playwright-mcp", ".ruff_cache", ".mypy_cache", ".pytest_cache",
    "node_modules", "dist", "cache", "models", "__pycache__"
)
$ExcludeFileNames = @(".env", ".install_done", "desktop.ini", "Thumbs.db")

function Should-SkipPath([string]$RelativePath) {
    $parts = $RelativePath -split "[\\/]"
    foreach ($p in $parts) {
        if ($ExcludeDirNames -contains $p) { return $true }
    }
    if ($RelativePath -match "\\\.next\\") { return $true }
    if ($RelativePath -match "\\data\\logs\\") { return $true }
    if ($RelativePath -match "\\data\\memory\\") { return $true }
    if ($RelativePath -match "\\data\\mcp\\" -and $RelativePath -notmatch "\\\.gitkeep$") { return $true }
    if ($RelativePath -match "\\data\\config\\.*\.json$") { return $true }
    if ($RelativePath -match "\\data\\presence\\") { return $true }
    if ($RelativePath -match "\\data\\reminders\\") { return $true }
    $leaf = Split-Path -Leaf $RelativePath
    if ($ExcludeFileNames -contains $leaf) { return $true }
    if ($leaf -match "\.pyc$") { return $true }
    if ($leaf -match "\.log$") { return $true }
    return $false
}

function Copy-TreeFiltered {
    param([string]$Source, [string]$Dest, [string]$Root)
    if (Test-Path $Source -PathType Leaf) {
        $rel = $Source.Substring($Root.Length).TrimStart("\", "/")
        if (Should-SkipPath $rel) { return }
        $destDir = Split-Path -Parent $Dest
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
        Copy-Item -LiteralPath $Source -Destination $Dest -Force
        return
    }
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-TreeFiltered -Source $_.FullName -Dest (Join-Path $Dest $_.Name) -Root $Root
    }
}

Write-Host "==> 清理旧目录: $Stage"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null

Write-Host "==> 复制文件到 $Stage ..."
Get-ChildItem -Path $Root -Force | ForEach-Object {
    if ($ExcludeDirNames -contains $_.Name) { return }
    Copy-TreeFiltered -Source $_.FullName -Dest (Join-Path $Stage $_.Name) -Root $Root
}

# 确保空目录结构
@(
    "data\config",
    "data\memory",
    "data\logs",
    "models\ASR\whisper",
    "models\TTS",
    "models\character"
) | ForEach-Object {
    $p = Join-Path $Stage $_
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

# 用户安装说明（复制到包根）
$UserGuide = Join-Path $Root "docs\INSTALL_FOR_USERS.md"
if (Test-Path $UserGuide) {
    Copy-Item $UserGuide (Join-Path $Stage "安装说明.md") -Force
}

Write-Host "==> 压缩 $ZipPath ..."
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path $Stage -DestinationPath $ZipPath -CompressionLevel Optimal

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "Done: $ZipPath ($sizeMb MB)"
Write-Host "Send to user: unzip, run first_run_setup.bat, then start pet."
