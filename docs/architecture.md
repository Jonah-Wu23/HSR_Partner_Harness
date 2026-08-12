# 当前架构

HSR Partner Harness 由桌面进程和 Python Sidecar 组成。桌面进程负责窗口与原生文件夹选择，Sidecar 保存会话状态，也负责模型调用。

## 桌面端

Tauri 在 `desktop/src-tauri/`。React 界面位于 `desktop/src/`。

Rust 启动打包后的 Sidecar，通过标准输入输出交换 JSONL。每条请求带有独立 ID，响应按 ID 返回；运行事件通过 Tauri event 进入 React。

## Python Sidecar

入口位于 `src/pair_harness/desktop_backend/`。`DesktopApplicationService` 把桌面协议接到编排器和 SQLite 存储。

Sidecar 按请求创建并发任务，因此长时间编程任务运行时，聊天消息仍能进入后端。取消请求也走同一条通道。

## 对话与执行

角色模型通过 OpenAI 兼容接口接入。源码运行时编程任务交给本机 Codex app-server；发布构建会把 Windows 原生 Codex app-server 一起放进 Tauri resources，安装版优先使用随包版本。

角色发言与助手输出拥有明确身份。工具事件保持结构化，前端根据事件更新工作台。

## 语音

ASR 使用 `qwen-audio-3.0-asr-flash-streaming`。TTS 使用 `qwen-audio-3.0-tts-flash`。

自然语言回复可以进入播放队列。命令输出和工具记录保持静音。

## 数据

项目和聊天保存在 `%LOCALAPPDATA%\PairHarness\pair_harness.db`。每个项目绑定一个本地文件夹，审批模式也保存在项目记录中。
