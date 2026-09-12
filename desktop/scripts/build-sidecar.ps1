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

# Global npm root, used to fall back to an installed Reasonix native binary (see below).
$npmRoot = $null
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($npm) {
    $npmRootOutput = & $npm.Source root -g 2>$null
    if ($LASTEXITCODE -eq 0 -and $npmRootOutput) {
        $npmRoot = ($npmRootOutput | Select-Object -Last 1).ToString().Trim()
    }
}

# Copy the Reasonix CLI Windows native binary (reasonix.exe, the DeepSeek coding
# assistant) into the Tauri resources for the DeepSeek engine's reasonix acp child.
New-Item -ItemType Directory -Path (Split-Path -Parent $script:bundledReasonix) -Force | Out-Null
$reasonixSource = $null

if ($env:PAIR_HARNESS_REASONIX_NATIVE_ROOT) {
    $explicitReasonix = Join-Path $env:PAIR_HARNESS_REASONIX_NATIVE_ROOT "reasonix.exe"
    if (-not (Test-Path -LiteralPath $explicitReasonix -PathType Leaf)) {
        throw "PAIR_HARNESS_REASONIX_NATIVE_ROOT does not contain reasonix.exe: $explicitReasonix"
    }
    Copy-Item -LiteralPath $explicitReasonix -Destination $script:bundledReasonix -Force
    $reasonixSource = $explicitReasonix
} else {
    $localReasonixRoot = Join-Path $repoRoot "DeepSeek-Reasonix"
    $localReasonixModule = Join-Path $localReasonixRoot "go.mod"
    if (Test-Path -LiteralPath $localReasonixModule -PathType Leaf) {
        $goCommand = Get-Command go -ErrorAction SilentlyContinue
        if (-not $goCommand) {
            throw "Local DeepSeek-Reasonix source exists, but Go is unavailable. Install/provide Go and rebuild; refusing to bundle a stale npm binary."
        }
        Push-Location $localReasonixRoot
        try {
            & $goCommand.Source build -trimpath -o $script:bundledReasonix ./cmd/reasonix
            $reasonixBuildExitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($reasonixBuildExitCode -ne 0 -or -not (Test-Path -LiteralPath $script:bundledReasonix -PathType Leaf)) {
            throw "Building local DeepSeek-Reasonix failed with exit code $reasonixBuildExitCode."
        }
        $reasonixSource = "$localReasonixRoot (local source build)"
    } else {
        $reasonixCandidates = @()
        if ($npmRoot) {
            $reasonixCandidates += ,(Join-Path $npmRoot "reasonix\node_modules\@reasonix\cli-win32-x64\bin\reasonix.exe")
        }
        $reasonixShim = Get-Command reasonix.cmd -ErrorAction SilentlyContinue
        if ($reasonixShim) {
            $shimRoot = Split-Path -Parent $reasonixShim.Source
            if ($shimRoot) {
                $reasonixCandidates += ,(Join-Path $shimRoot "node_modules\reasonix\node_modules\@reasonix\cli-win32-x64\bin\reasonix.exe")
            }
        }
        foreach ($candidate in $reasonixCandidates) {
            if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                Copy-Item -LiteralPath $candidate -Destination $script:bundledReasonix -Force
                $reasonixSource = $candidate
                break
            }
        }
        if (-not $reasonixSource) {
            throw "Reasonix Windows native binary not found. Install it with 'npm i -g reasonix' or set PAIR_HARNESS_REASONIX_NATIVE_ROOT."
        }
    }
}

Write-Host "Bundled Reasonix prepared from $reasonixSource`: $script:bundledReasonix"

# Build the mobile PWA and copy it into the Tauri resources (V0.3.4 packaging):
# sidecar --serve statically serves resources/mobile-dist, so a phone that scans
# the pairing QR code reaches the page on the same 8765 port.
$mobileRoot = Join-Path $desktopRoot "mobile"
if ([string]::IsNullOrWhiteSpace($mobileRoot) -or -not (Test-Path -LiteralPath $mobileRoot -PathType Container)) {
    throw "Invalid mobile root: desktopRoot='$desktopRoot' mobileRoot='$mobileRoot'"
}

# Push-Location does not change the working directory inherited by child
# processes (PowerShell's Location and [Environment]::CurrentDirectory are two
# different things), so npm used to run in the desktop root and mobile-dist was
# never rebuilt. Use cmd /c cd /d to pin npm's working directory explicitly.
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

$mobileDist = Join-Path $mobileRoot "dist"
if (-not (Test-Path -LiteralPath (Join-Path $mobileDist "index.html") -PathType Leaf)) {
    throw "mobile build output missing index.html: $mobileDist"
}

# Validate mobile PWA dist directory before packaging (D7)
$validator = Join-Path $PSScriptRoot "validate-pwa-dist.ps1"
if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
    throw "PWA dist validator script not found: $validator"
}
& $validator -DistPath $mobileDist
if ($LASTEXITCODE -ne 0) {
    throw "PWA dist validation failed before bundling (exit code $LASTEXITCODE)."
}

$mobileResourceRoot = Join-Path $resourceRoot "mobile-dist"
if (Test-Path -LiteralPath $mobileResourceRoot) {
    Remove-Item -LiteralPath $mobileResourceRoot -Recurse -Force
}
Copy-Item -LiteralPath $mobileDist -Destination $mobileResourceRoot -Recurse -Force

# Validate copied mobile-dist resources (D7)
& $validator -DistPath $mobileResourceRoot
if ($LASTEXITCODE -ne 0) {
    throw "PWA resource validation failed after bundling (exit code $LASTEXITCODE)."
}

Write-Host "Bundled mobile PWA prepared and validated (D7): $mobileResourceRoot"
