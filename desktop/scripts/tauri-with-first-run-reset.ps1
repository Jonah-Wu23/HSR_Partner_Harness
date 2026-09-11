[CmdletBinding()]
param(
    [switch]$ResetOnly,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TauriArgs
)

$ErrorActionPreference = "Stop"

# This file must stay pure ASCII with LF line endings and no UTF-8 BOM.
# Windows PowerShell 5.1 decodes a BOM-less script file with the system ANSI
# code page (CP936 on this machine). A multibyte character whose trailing byte
# is consumed together with the following LF swallows the line break and merges
# the next line into the comment, so an assignment can vanish with no syntax
# error (V039-S4-010 / V039-R1-001). Keep every comment and message ASCII, and
# do not rely on a BOM to make non-ASCII text safe here.

$desktopRoot = Split-Path -Parent $PSScriptRoot
$localAppData = $env:LOCALAPPDATA
if (-not $localAppData) {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
}
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw "LOCALAPPDATA is unavailable; first-run state cannot be reset."
}

# The Rust side writes the sidecar stderr log to %APPDATA%\<identifier>
# (app_data_dir), a different root from the WebView/business data directory
# under LOCALAPPDATA.
$appData = $env:APPDATA
if (-not $appData) {
    $appData = [Environment]::GetFolderPath("ApplicationData")
}
if ([string]::IsNullOrWhiteSpace($appData)) {
    throw "APPDATA is unavailable; the sidecar stderr log cannot be reset."
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

    # The sidecar stderr log and its rolled copies (sidecar.stderr.log / .1 ... .N).
    # Keeping them across batches leaks the previous batch traceback into the next
    # batch evidence (V039-S4-010), so a first-run reset must clear them too.
    $logRoot = Get-FullPath (Join-Path (Get-FullPath $appData) "com.jonahwu.hsr-partner-harness")
    if ((Get-FullPath (Split-Path -Parent $logRoot)) -ne (Get-FullPath $appData)) {
        throw "Refusing to clear logs from an unvalidated path: $logRoot"
    }
    if (Test-Path -LiteralPath $logRoot) {
        $logFiles = @(Get-ChildItem -LiteralPath $logRoot -File -Filter "sidecar.stderr.log*")
        foreach ($logFile in $logFiles) {
            Remove-Item -LiteralPath $logFile.FullName -Force
            Write-Host "Cleared: $($logFile.FullName)"
        }
    }
}

function Write-Failure($ErrorRecord) {
    # Report through the error stream without a terminating Write-Error: under
    # $ErrorActionPreference = "Stop" a terminating error inside the catch block
    # would abort it before it can exit non-zero.
    [Console]::Error.WriteLine("tauri-with-first-run-reset: " + $ErrorRecord.Exception.Message)
    if ($ErrorRecord.InvocationInfo) {
        [Console]::Error.WriteLine("  at " + $ErrorRecord.InvocationInfo.PositionMessage.Trim())
    }
}

# Every exit path funnels through this catch and ends in exit 1, so a failed
# reset cannot leave the wrapper - or npm run's exit code - reporting success.
$exitCode = 1
try {
    if ($ResetOnly) {
        Reset-FirstRunState
        $exitCode = 0
    }
    else {
        if (-not $TauriArgs -or $TauriArgs.Count -eq 0) {
            throw "Provide Tauri arguments, for example: build --no-bundle."
        }

        $tauriCli = Join-Path $desktopRoot "node_modules\.bin\tauri.cmd"
        if (-not (Test-Path -LiteralPath $tauriCli -PathType Leaf)) {
            throw "Local Tauri CLI not found: $tauriCli"
        }

        Push-Location $desktopRoot
        try {
            & $tauriCli @TauriArgs
            $exitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }

        if ($exitCode -ne 0) {
            throw "Tauri CLI failed with exit code $exitCode; first-run state was not reset."
        }

        if ($TauriArgs -contains "build") {
            Reset-FirstRunState
        }
        $exitCode = 0
    }
}
catch {
    Write-Failure $_
    exit 1
}

exit $exitCode
