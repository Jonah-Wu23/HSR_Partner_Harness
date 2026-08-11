$ErrorActionPreference = "Stop"

$desktopRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $desktopRoot
$workspaceRoot = $repoRoot
while (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot ".venv\Scripts\python.exe"))) {
    $parent = Split-Path -Parent $workspaceRoot
    if ($parent -eq $workspaceRoot) {
        break
    }
    $workspaceRoot = $parent
}
$python = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $repoRoot "src\pair_harness\desktop_backend\__main__.py"
$resourceRoot = Join-Path $desktopRoot "src-tauri\resources"
$distRoot = Join-Path $resourceRoot "sidecar"
$workRoot = Join-Path $desktopRoot ".pyinstaller-work"
$specRoot = Join-Path $desktopRoot ".pyinstaller-spec"
$configRoot = Join-Path $desktopRoot ".pyinstaller-config"

if (-not (Test-Path -LiteralPath $python)) {
    throw "项目虚拟环境不存在：$python"
}

New-Item -ItemType Directory -Path $resourceRoot -Force | Out-Null
New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
$env:PYINSTALLER_CONFIG_DIR = $configRoot

& $python -m PyInstaller `
    --noconfirm `
    --onedir `
    --name "pair-harness-sidecar" `
    --paths (Join-Path $repoRoot "src") `
    --distpath $distRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    --add-data "$(Join-Path $repoRoot 'config');config" `
    --add-data "$(Join-Path $repoRoot 'assets');assets" `
    --add-data "$(Join-Path $repoRoot 'src\pair_harness\storage\schema.sql');pair_harness\storage" `
    $entrypoint

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建 Sidecar 失败，退出码：$LASTEXITCODE"
}
