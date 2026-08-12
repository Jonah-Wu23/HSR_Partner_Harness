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
$codexResourceRoot = Join-Path $resourceRoot "codex"
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

# 把 Codex CLI 的 Windows 原生发行目录一起放进 Tauri resources。
# 只复制原生 vendor 目录，不把 node_modules 或 Node.js 带进安装包；
# Codex app-server 由这个目录里的 codex.exe 直接启动。
$nativeRootCandidates = @()
if ($env:PAIR_HARNESS_CODEX_NATIVE_ROOT) {
    $nativeRootCandidates += ,$env:PAIR_HARNESS_CODEX_NATIVE_ROOT
}

$npmRoot = $null
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($npm) {
    $npmRootOutput = & $npm.Source root -g 2>$null
    if ($LASTEXITCODE -eq 0 -and $npmRootOutput) {
        $npmRoot = ($npmRootOutput | Select-Object -Last 1).ToString().Trim()
    }
}
if ($npmRoot) {
    $nativeRootCandidates += ,(Join-Path $npmRoot "@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc")
}

$appDataRoot = $env:APPDATA
if (-not $appDataRoot) {
    $appDataRoot = [Environment]::GetFolderPath("ApplicationData")
}
if ($appDataRoot) {
    $nativeRootCandidates += ,(Join-Path $appDataRoot "npm\node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc")
}

$codexShim = Get-Command codex.cmd -ErrorAction SilentlyContinue
if ($codexShim) {
    $shimRoot = Split-Path -Parent $codexShim.Source
    if ($shimRoot) {
        $nativeRootCandidates += ,(Join-Path $shimRoot "node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc")
    }
}

$nativeRoot = $null
foreach ($candidate in $nativeRootCandidates) {
    if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate "bin\codex.exe") -PathType Leaf)) {
        $nativeRoot = $candidate
        break
    }
}

if (-not $nativeRoot) {
    throw "Codex native Windows distribution not found. Install @openai/codex or set PAIR_HARNESS_CODEX_NATIVE_ROOT to a directory containing bin\codex.exe."
}

New-Item -ItemType Directory -Path $codexResourceRoot -Force | Out-Null
Get-ChildItem -LiteralPath $nativeRoot -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $codexResourceRoot -Recurse -Force
}

$bundledCodex = Join-Path $codexResourceRoot "bin\codex.exe"
if (-not (Test-Path -LiteralPath $bundledCodex -PathType Leaf)) {
    throw "Copying the Codex native distribution failed: $bundledCodex"
}
Write-Host "Bundled Codex prepared: $bundledCodex"
