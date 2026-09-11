# V039-S4-010 复验证据：首次运行清理脚本的 sidecar stderr 日志清理未生效

## 现场

`npm run tauri -- build --no-bundle`（经 `tauri-with-first-run-reset.ps1` 包装）结束后：

- `%LOCALAPPDATA%\PairHarness` 已被删除，WebView 的 Local/Session Storage 也被删除（三条 `Cleared:` 输出）；
- **`%APPDATA%\com.jonahwu.hsr-partner-harness\sidecar.stderr.log` 原样残留**（时间戳 2026-09-10 18:46，即上一批次 `batch-2026-09-10` 的日志，72,790 B），本批次要求的干净日志起点未达成。

## 复现

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/tauri-with-first-run-reset.ps1 -ResetOnly
# -> 无法将参数绑定到参数"Path"，因为该参数是空值。
#    FullyQualifiedErrorId : ParameterArgumentValidationErrorNullNotAllowed
#    在 Reset-FirstRunState 中: 第 70 行
```

稳定复现三次；残留文件两次均未被删除。

## 根因（已用 .NET 解码确证）

脚本以 **UTF-8 无 BOM + LF 行尾 + 中文注释**保存：

| 事实 | 值 |
| --- | --- |
| 文件字节数 | 4018 |
| UTF-8 BOM | 无 |
| CRLF | 无（LF 行尾） |
| `[Text.Encoding]::UTF8` 解码行数 | 116 |
| `[Text.Encoding]::Default`（CP936）解码行数 | **114** |

Windows PowerShell 5.1 对无 BOM 脚本按系统 ANSI 代码页（CP936）解码。UTF-8 中文的三字节序列在 CP936 下错位，
末字节与行尾 LF 被当作一个双字节字符消费，**共吞掉 2 个换行**，注释行与下一行代码被合并：

```
ansi_line 69:     # 璁╀笂涓€鎵规＄�?traceback 娣疯繘鏈鎵规¤瘉鎹锛圴039-S4-010锛夛紝棣栨¤繍琛屽繀椤讳竴骞舵竻绌恒€?    $logRoot = Get-FullPath (Join-Path (Get-FullPath $appData) "com.jonahwu.hsr-partner-harness")
```

第 70 行注释与第 71 行 `$logRoot = ...` 合并后，整条赋值变成注释的一部分，`$logRoot` 从未被赋值。
第 72 行 `if ((Get-FullPath (Split-Path -Parent $logRoot)) -ne ...)` 因此向 `Split-Path -Parent` 传入 null，
抛参数绑定异常；日志删除的 `foreach` 从未执行。原始 PowerShell 输出见同目录 `reset-script-decode-probe.txt`。

> 注：Python 的 `gbk` 解码器与 .NET CP936 在遇到无效次字节时前进字节数不同（Python 得 116 行，.NET 得 114 行），
> 因此该类缺陷只能用 PowerShell/.NET 观察，不能用 Python 复现。

## 受控变量实验

| 变体 | 结果 |
| --- | --- |
| 原文件（UTF-8 无 BOM，含中文） | 稳定失败，日志残留 |
| 加 UTF-8 BOM | 成功，日志被清除 |
| 中文注释替换为 ASCII（无 BOM，同 LF） | 成功，日志被清除 |

## 影响

- 首次运行清理未达成设计目标：跨批次 `sidecar.stderr.log` 会混入下一批次证据，直接威胁复测计划 §3.3/§13.2.2 要求的
  「全量落盘、不按级别过滤」取证（该文件是 019 归因与 018 抢占路径的唯一证据源）。
- 失败在打包流程里**静默**：`npm run tauri -- build --no-bundle` 仍以 exit 0 结束，构建日志里只有一行 PowerShell 错误文本。
- 与本批次的关系：复测开测前必须自行清除该文件才能得到干净起点（本批次已手工执行并留证）。
