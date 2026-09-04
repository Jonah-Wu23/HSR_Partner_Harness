# V0.3.7 Android spike 前置校验与启动脚本（契约 §9.3 清单的固化执行）。
# 用途：用户按清单配置 JDK 17 / Android SDK / NDK 后，运行本脚本一次性完成
# 环境校验与 tauri android init；任何一项不满足即以明确诊断如实失败，
# 不猜测、不降级、不伪造就绪状态。
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts/android-spike.ps1 -ValidateOnly   # 只校验
#   powershell -ExecutionPolicy Bypass -File scripts/android-spike.ps1                 # 校验 + tauri android init
[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$desktopRoot = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()

# 清单 §9.3.1：JDK 17（AGP 8 不支持 JDK 11）
if ([string]::IsNullOrWhiteSpace($env:JAVA_HOME)) {
    $failures.Add("§9.3.1 JAVA_HOME 未设置；请安装 JDK 17 并将 JAVA_HOME 指向它")
} else {
    $javaExe = Join-Path $env:JAVA_HOME "bin\java.exe"
    if (-not (Test-Path -LiteralPath $javaExe -PathType Leaf)) {
        $failures.Add("§9.3.1 JAVA_HOME 未指向有效的 JDK（当前='$($env:JAVA_HOME)'）；请安装 JDK 17 并设置 JAVA_HOME")
    } else {
        $javaVersionOutput = & $javaExe --version 2>&1 | Out-String
        $firstLine = ($javaVersionOutput -split "`r?`n")[0]
        if ($LASTEXITCODE -eq 0 -and $firstLine -match '\b(\d+)\.') {
            $javaMajor = [int]$Matches[1]
            if ($javaMajor -lt 17) {
                $failures.Add("§9.3.1 JAVA_HOME 指向的是 JDK $javaMajor（路径='$($env:JAVA_HOME)'）；Android Gradle Plugin 需要 JDK 17+")
            }
        } else {
            $failures.Add("§9.3.1 无法解析 java 版本输出：$javaVersionOutput")
        }
    }
}

# 清单 §9.3.2/§9.3.3：ANDROID_HOME（SDK 根）与 NDK_HOME（NDK 版本目录）
if ([string]::IsNullOrWhiteSpace($env:ANDROID_HOME) -or -not (Test-Path -LiteralPath $env:ANDROID_HOME -PathType Container)) {
    $failures.Add("§9.3.3 ANDROID_HOME 未设置或目录不存在（当前='$($env:ANDROID_HOME)'）")
} else {
    foreach ($required in @("platform-tools", "platforms", "build-tools")) {
        if (-not (Test-Path -LiteralPath (Join-Path $env:ANDROID_HOME $required) -PathType Container)) {
            $failures.Add("§9.3.2 ANDROID_HOME 缺少 $required 组件（Android Studio SDK Manager 或 cmdline-tools 安装）")
        }
    }
}
if ([string]::IsNullOrWhiteSpace($env:NDK_HOME) -or -not (Test-Path -LiteralPath (Join-Path $env:NDK_HOME "source.properties") -PathType Leaf)) {
    $failures.Add("§9.3.3 NDK_HOME 未设置或不是 NDK 根目录（应含 source.properties；当前='$($env:NDK_HOME)'）")
}

# 清单 §9.3.4：真机调试（真机验收 #9/#10 用；缺失仅提示，不阻断 init）
if ([string]::IsNullOrWhiteSpace($env:ANDROID_HOME)) {
    Write-Host "提示：ANDROID_HOME 未配置，跳过真机检测"
} else {
    $adb = Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
    if (Test-Path -LiteralPath $adb -PathType Leaf) {
        # adb 的启动提示走 stderr；PS5.1 在 EAP=Stop 下会把重定向的原生
        # stderr 变成终止错误——经 cmd /c 2>nul 吸收。
        $devices = & cmd.exe /c "`"$adb`" devices 2>nul" | Where-Object { $_ -match "`tdevice$|`tunauthorized$" }
        if ($devices) {
            Write-Host "已连接真机：$devices"
        } else {
            Write-Host "提示：未检测到已连接真机（真机验收 #9/#10 前需开启 USB 调试并连接）"
        }
    }
}

if ($failures.Count -gt 0) {
    Write-Host "环境校验未通过，逐项诊断：" -ForegroundColor Red
    foreach ($failure in $failures) {
        Write-Host "  - $failure" -ForegroundColor Red
    }
    exit 1
}

Write-Host "环境校验全部通过（JDK 17 / ANDROID_HOME / NDK_HOME）。" -ForegroundColor Green
if ($ValidateOnly) {
    exit 0
}

# 校验通过后执行 tauri android init（生成 gen/android 壳工程，入库）。
# 前台服务与通知插件按契约 §9.2 在 spike 中定案安装，不在本脚本内静默引入。
$tauriCli = Join-Path $desktopRoot "node_modules\.bin\tauri.cmd"
if (-not (Test-Path -LiteralPath $tauriCli -PathType Leaf)) {
    throw "未找到 Tauri CLI：$tauriCli"
}
Push-Location $desktopRoot
try {
    & $tauriCli android init
    if ($LASTEXITCODE -ne 0) {
        throw "tauri android init 失败，退出码 $LASTEXITCODE（原始输出如上，不掩盖）"
    }
} finally {
    Pop-Location
}
Write-Host "gen/android 壳工程已生成；spike 后续步骤（前台服务选型、通知插件、真机构建）按契约 §9.2 由逻辑轨继续执行。" -ForegroundColor Green
