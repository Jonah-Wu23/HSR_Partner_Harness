# Tauri M8 真实联调记录

日期：2026-08-11

## 配置边界

- 配置来源：仓库根目录 `.env`；密钥只注入测试进程环境，不写入日志或文档。
- 角色对话端点：DeepSeek 官方端点（`api.deepseek.com`）。
- 角色对话模型：`deepseek-v4-flash`。
- 语音：DashScope Qwen 流式 ASR/TTS，使用 pair 配置中已登记的真实 voice id。
- Tauri 入口：项目根存在 `.env` 时自动启动 sidecar `--real`；无 `.env` 时保持 `--demo`。`PAIR_HARNESS_REAL` 与 `PAIR_HARNESS_DEMO` 可显式覆盖。

## 验收结果

| 链路 | 结果 |
| --- | --- |
| DeepSeek 角色边界（闲聊、结构化委派、失败结果） | `1 passed` |
| B1 DeepSeek + Codex app-server（创建、恢复追加、新会话隔离） | `2 passed`，156.95 s |
| B2 Qwen ASR/TTS live | `2 passed`，12.88 s |
| PyInstaller sidecar `--real` | `BackendDemo=false`、真实闲聊成功、`voice.supported=true`、退出码 0 |
| Tauri release 真实入口 | 子进程实际为 `--real --project ...`，无 Python fallback、优雅退出、无残留 |
| NSIS 安装版无 `.env` 回退 | packaged sidecar `--demo` 正常启动，项目/聊天 SQLite 恢复通过 |

## 可复现命令

在 PowerShell 中先把根 `.env` 的非空 `KEY=VALUE` 行注入当前进程，再执行：

```powershell
$env:PYTHONPATH = (Get-Location).Path + '\src'
.\.venv\Scripts\python.exe -m pytest -q -m live tests\integration\test_text_loop_live.py

$env:RUN_LIVE_QWEN = '1'
.\.venv\Scripts\python.exe -m pytest -q -m live_qwen tests\integration\test_qwen_audio_live.py
```

## 已知基线

完整 Python 回归为 `341 passed, 5 skipped, 1 failed`；唯一失败仍是既有 PyQt `test_theme_preference_roundtrip`（测试期望 `light`，当前项目默认主题锁定为 `dark`），与本次 Tauri/M8 接线无关。
