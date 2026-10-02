$ErrorActionPreference = "Stop"

# Keep this file ASCII: Windows PowerShell 5.1 reads BOM-less scripts with the
# system ANSI code page.

$desktopRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $desktopRoot
# The repository .venv must have the project installed (pip install -e ".[voice,dev]")
# so PyInstaller can collect every runtime dependency.
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
# The entry script uses absolute pair_harness imports; --paths src lets
# PyInstaller resolve the package.
$entrypoint = Join-Path $repoRoot "src\pair_harness\desktop_backend\__main__.py"
$resourceRoot = Join-Path $desktopRoot "src-tauri\resources"
$distRoot = Join-Path $resourceRoot "sidecar"
$workRoot = Join-Path $desktopRoot ".pyinstaller-work"
$specRoot = Join-Path $desktopRoot ".pyinstaller-spec"
$configRoot = Join-Path $desktopRoot ".pyinstaller-config"
$script:bundledReasonix = Join-Path $resourceRoot "reasonix\bin\reasonix.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment not found: $python"
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
    throw "PyInstaller failed to build the sidecar, exit code: $LASTEXITCODE"
}

# Bundle the Reasonix Windows native binary (reasonix.exe) that the coding
# assistant runs as "reasonix acp". Source, in this order:
#   1. PAIR_HARNESS_REASONIX_NATIVE_ROOT: a directory containing reasonix.exe;
#   2. otherwise a DeepSeek-Reasonix source checkout at <repo>\DeepSeek-Reasonix,
#      built with Go.
# Anything else fails the build.
New-Item -ItemType Directory -Path (Split-Path -Parent $script:bundledReasonix) -Force | Out-Null
$localReasonixRoot = Join-Path $repoRoot "DeepSeek-Reasonix"

if ($env:PAIR_HARNESS_REASONIX_NATIVE_ROOT) {
    $explicitReasonix = Join-Path $env:PAIR_HARNESS_REASONIX_NATIVE_ROOT "reasonix.exe"
    if (-not (Test-Path -LiteralPath $explicitReasonix -PathType Leaf)) {
        throw "PAIR_HARNESS_REASONIX_NATIVE_ROOT does not contain reasonix.exe: $explicitReasonix"
    }
    Copy-Item -LiteralPath $explicitReasonix -Destination $script:bundledReasonix -Force
    $reasonixSource = $explicitReasonix
} elseif (Test-Path -LiteralPath (Join-Path $localReasonixRoot "go.mod") -PathType Leaf) {
    $goCommand = Get-Command go -ErrorAction SilentlyContinue
    if (-not $goCommand) {
        throw "DeepSeek-Reasonix source found at $localReasonixRoot, but Go is not installed."
    }
    Push-Location $localReasonixRoot
    try {
        & $goCommand.Source build -trimpath -o $script:bundledReasonix ./cmd/reasonix
        $reasonixBuildExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($reasonixBuildExitCode -ne 0) {
        throw "Building DeepSeek-Reasonix failed with exit code $reasonixBuildExitCode."
    }
    $reasonixSource = "$localReasonixRoot (source build)"
} else {
    throw "No Reasonix source. Set PAIR_HARNESS_REASONIX_NATIVE_ROOT to a directory containing reasonix.exe, or check out DeepSeek-Reasonix at $localReasonixRoot."
}

Write-Host "Bundled Reasonix prepared from $reasonixSource`: $script:bundledReasonix"

# Build the mobile PWA and copy it into the Tauri resources: sidecar --serve
# statically serves resources/mobile-dist, so a phone that scans the pairing QR
# code reaches the page on the same 8765 port.
$mobileRoot = Join-Path $desktopRoot "mobile"

# Push-Location does not change the working directory inherited by child
# processes, so cmd /c cd /d pins npm's working directory to the mobile root.
if (-not (Test-Path -LiteralPath (Join-Path $mobileRoot "node_modules") -PathType Container)) {
    & cmd.exe /d /s /c "cd /d `"$mobileRoot`" && npm install"
    if ($LASTEXITCODE -ne 0) {
        throw "mobile npm install failed with exit code $LASTEXITCODE (cwd=$mobileRoot)."
    }
}
& cmd.exe /d /s /c "cd /d `"$mobileRoot`" && npm run build"
if ($LASTEXITCODE -ne 0) {
    throw "mobile PWA build failed with exit code $LASTEXITCODE (cwd=$mobileRoot)."
}

# The validator throws on any violation; with $ErrorActionPreference = "Stop"
# the error stops this script as well.
$validator = Join-Path $PSScriptRoot "validate-pwa-dist.ps1"
$mobileDist = Join-Path $mobileRoot "dist"
& $validator -DistPath $mobileDist

$mobileResourceRoot = Join-Path $resourceRoot "mobile-dist"
if (Test-Path -LiteralPath $mobileResourceRoot) {
    Remove-Item -LiteralPath $mobileResourceRoot -Recurse -Force
}
Copy-Item -LiteralPath $mobileDist -Destination $mobileResourceRoot -Recurse -Force
& $validator -DistPath $mobileResourceRoot

Write-Host "Bundled mobile PWA prepared and validated: $mobileResourceRoot"
