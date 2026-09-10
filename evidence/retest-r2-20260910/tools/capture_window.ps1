param(
    [Parameter(Mandatory = $true)][string]$ProcessName,
    [Parameter(Mandatory = $true)][string]$OutPath,
    [int]$DelaySeconds = 2
)

# 该应用的 MainWindowHandle 在部分状态下拿不到有效矩形（GetWindowRect 返回 0,0,0,0），
# 因此改为整屏截图：调用前用 MCP 的 open_application(activate=true) 把目标窗口置于前台。
# 证据里保存的是整屏图，含窗口与任务栏，便于核对前台归属。

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$proc = Get-Process -Name $ProcessName -ErrorAction Stop | Select-Object -First 1
Start-Sleep -Seconds $DelaySeconds

$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
if ($bounds.Width -le 0 -or $bounds.Height -le 0) { throw "invalid screen bounds" }

$bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bitmap.Size)
$dir = Split-Path -Parent $OutPath
if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$bitmap.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()

[pscustomobject]@{
    process = $ProcessName
    pid = $proc.Id
    screen = @{ left = $bounds.Left; top = $bounds.Top; width = $bounds.Width; height = $bounds.Height }
    out = $OutPath
    bytes = (Get-Item -LiteralPath $OutPath).Length
} | ConvertTo-Json -Compress
