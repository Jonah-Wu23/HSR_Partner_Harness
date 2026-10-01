[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$DistPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DistPath)) {
    $scriptDir = Split-Path -Parent $PSCommandPath
    $desktopRoot = Split-Path -Parent $scriptDir
    $DistPath = Join-Path $desktopRoot "mobile\dist"
}

if (-not (Test-Path -LiteralPath $DistPath -PathType Container)) {
    throw "PWA dist directory not found: $DistPath"
}

$indexHtml = Join-Path $DistPath "index.html"
if (-not (Test-Path -LiteralPath $indexHtml -PathType Leaf)) {
    throw "PWA dist directory missing required index.html: $DistPath"
}

# The PWA directory is served to phones as-is, so it may only contain static web
# assets. Allowed file extensions (lowercase, without the leading dot):
$allowedExtensions = @(
    "html", "htm",
    "js", "mjs", "cjs", "map",
    "css",
    "webmanifest", "manifest", "json",
    "png", "jpg", "jpeg", "gif", "svg", "ico", "webp", "avif",
    "woff", "woff2", "ttf", "otf", "eot",
    "txt",
    "mp3", "wav", "ogg"
)

$files = @(Get-ChildItem -LiteralPath $DistPath -Recurse -File)
if ($files.Count -eq 0) {
    throw "PWA dist directory is empty: $DistPath"
}

$violations = @()
foreach ($file in $files) {
    $ext = $file.Extension.TrimStart(".").ToLowerInvariant()
    if ($allowedExtensions -notcontains $ext) {
        $relPath = $file.FullName.Substring($DistPath.Length).TrimStart("\", "/")
        $violations += "File extension '$ext' is not a static web asset: $relPath"
    }
}

if ($violations.Count -gt 0) {
    $msgLines = @("PWA static directory validation failed: $DistPath")
    foreach ($v in $violations) {
        $msgLines += "  - $v"
    }
    throw ($msgLines -join "`n")
}

Write-Host "PWA static directory validation passed: $($files.Count) static files in $DistPath."
