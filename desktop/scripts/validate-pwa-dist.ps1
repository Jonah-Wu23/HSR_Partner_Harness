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

# Whitelist of allowed static asset file extensions (lowercase, without leading dot)
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

# Explicit forbidden extension patterns (immediate failure)
$forbiddenExtensions = @(
    "db", "sqlite", "sqlite3", "db-shm", "db-wal",
    "env", "key", "pem", "crt", "p12", "token", "tokens",
    "tmp", "bak", "swp", "log",
    "ts", "tsx", "py", "rs", "go", "sh", "ps1", "bat", "cmd",
    "zip", "tar", "gz", "7z"
)

# Forbidden filename tokens (case-insensitive regex matches)
$forbiddenNamePatterns = @(
    "account",
    "user_data",
    "userdata",
    "credential",
    "secret",
    "token",
    "password",
    "id_rsa",
    "pairing_state",
    "history",
    "session",
    "\.env",
    "private"
)

# Sensitive content markers for text/json files
$forbiddenContentKeywords = @(
    "password_hash",
    "api_key",
    "device_token",
    "secret_key",
    "private_key"
)

$violations = @()
$files = @(Get-ChildItem -LiteralPath $DistPath -Recurse -File)

if ($files.Count -eq 0) {
    throw "PWA dist directory is empty: $DistPath"
}

foreach ($file in $files) {
    $relPath = $file.FullName.Substring($DistPath.Length).TrimStart("\", "/")
    $ext = $file.Extension.TrimStart(".").ToLowerInvariant()
    $name = $file.Name.ToLowerInvariant()

    # 1. Forbidden extension check first, so leaks are reported with the
    #    explicit forbidden reason instead of a generic whitelist rejection.
    if ($forbiddenExtensions -contains $ext) {
        $violations += "Forbidden file extension '$ext': $relPath"
        continue
    }

    # 2. Whitelist extension check
    if ($allowedExtensions -notcontains $ext) {
        $violations += "Unrecognized/unauthorized file extension '$ext': $relPath"
        continue
    }

    # 3. Forbidden filename pattern check
    foreach ($pat in $forbiddenNamePatterns) {
        if ($name -match $pat) {
            $violations += "File name matches forbidden pattern '$pat': $relPath"
            break
        }
    }

    # 4. Content check for text-based artifacts. The dist is mostly minified
    #    JS/CSS/HTML, so those must be scanned too, not only json/txt.
    if ($ext -in @("json", "txt", "webmanifest", "js", "mjs", "cjs", "css", "html", "htm", "map")) {
        $content = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
        if ($content) {
            foreach ($kw in $forbiddenContentKeywords) {
                if ($content.ToLowerInvariant().Contains($kw)) {
                    $violations += "File content contains sensitive keyword '$kw': $relPath"
                    break
                }
            }
        }
    }
}

if ($violations.Count -gt 0) {
    $msgLines = @("=== PWA STATIC DIRECTORY VALIDATION FAILED (D7) ===")
    foreach ($v in $violations) {
        $msgLines += "  - $v"
    }
    $msgLines += "PWA static directory ($DistPath) contains $($violations.Count) security violation(s). Packaging aborted."
    $fullMsg = ($msgLines -join "`n")
    [Console]::Error.WriteLine($fullMsg)
    throw $fullMsg
}

Write-Host "PWA static directory validation passed (D7): $($files.Count) valid static files in $DistPath."
