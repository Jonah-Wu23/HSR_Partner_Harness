[CmdletBinding()]
param(
    [switch]$ResetOnly,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TauriArgs
)

$ErrorActionPreference = "Stop"

$desktopRoot = Split-Path -Parent $PSScriptRoot
$localAppData = $env:LOCALAPPDATA
if (-not $localAppData) {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
}
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw "LOCALAPPDATA is unavailable; first-run state cannot be reset."
}

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
}

function Reset-FirstRunState {
    $localRoot = Get-FullPath $localAppData
    $webViewRoot = Join-Path $localRoot "com.jonahwu.hsr-partner-harness"
    $webViewDefault = Join-Path $webViewRoot "EBWebView\Default"
    $targets = @(
        @{ Path = Join-Path $localRoot "PairHarness"; Parent = $localRoot },
        @{ Path = Join-Path $webViewDefault "Local Storage"; Parent = $webViewDefault },
        @{ Path = Join-Path $webViewDefault "Session Storage"; Parent = $webViewDefault }
    )

    $running = @(
        Get-Process -Name "hsr-partner-harness", "pair-harness-sidecar" -ErrorAction SilentlyContinue
    )
    $webviewPath = Get-FullPath $webViewRoot
    $webviewProcesses = @(
        Get-CimInstance Win32_Process -Filter "Name = 'msedgewebview2.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($webviewPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 }
    )
    if ($running.Count -gt 0 -or $webviewProcesses.Count -gt 0) {
        throw "HSR Partner Harness is still running. Close the exe before resetting first-run state."
    }

    foreach ($target in $targets) {
        $fullTarget = Get-FullPath $target.Path
        $expectedParent = Get-FullPath $target.Parent
        $parent = Get-FullPath (Split-Path -Parent $fullTarget)
        if ($parent -ne $expectedParent) {
            throw "Refusing to remove an unvalidated path: $fullTarget"
        }

        if (Test-Path -LiteralPath $fullTarget) {
            Remove-Item -LiteralPath $fullTarget -Recurse -Force
            Write-Host "Cleared: $fullTarget"
        }
    }
}

if ($ResetOnly) {
    Reset-FirstRunState
    exit 0
}

if (-not $TauriArgs -or $TauriArgs.Count -eq 0) {
    throw "Provide Tauri arguments, for example: build --no-bundle."
}

$tauriCli = Join-Path $desktopRoot "node_modules\.bin\tauri.cmd"
if (-not (Test-Path -LiteralPath $tauriCli -PathType Leaf)) {
    throw "Local Tauri CLI not found: $tauriCli"
}

$exitCode = 1
Push-Location $desktopRoot
try {
    & $tauriCli @TauriArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    exit $exitCode
}

if ($TauriArgs -contains "build") {
    Reset-FirstRunState
}

exit 0
