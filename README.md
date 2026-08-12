# HSR Partner Harness

[English](README.en.md)

HSR Partner Harness 是一个 Windows 桌面应用，把角色聊天和本地 AI 编程放在同一段会话里。用户可以先和白厄讨论，再把任务交给神秘的古代机械。执行进度会回到原聊天，角色也会根据结果继续回应。

当前版本为 `v0.1.0`。桌面界面使用 Tauri 2 和 React，Python Sidecar 负责会话状态与模型调用。

## 下载

Windows x64 安装包发布在 [GitHub Releases](https://github.com/Jonah-Wu23/HSR_Partner_Harness/releases)。安装包目前没有代码签名，Windows SmartScreen 可能显示提醒。

缺少模型配置时，应用会进入 demo 模式。demo 模式可以查看界面与交互流程，不会调用真实模型。

## 当前功能

| 功能 | 说明 |
| --- | --- |
| 聊天模式 | 用户与角色进行全宽对话，编程工具保持关闭。 |
| 协作模式 | 角色对话与助手工作台同时显示，任务运行期间仍可继续聊天。 |
| 项目管理 | 一个项目对应一个本地文件夹，初始名称采用文件夹名称，之后可以手动修改。 |
| 聊天标题 | 新会话显示“新聊天”。首次完整回复结束后，助手会根据上下文生成标题。手动标题拥有更高优先级。 |
| 编程执行 | 助手通过 Codex app-server 处理文件和命令，工具过程以卡片形式显示。 |
| 审批 | 项目可以选择请求批准或自动审核，也可以完全允许运行。 |
| 语音 | DashScope 提供 ASR 与 TTS。角色回复可以朗读，工具记录保持静音。 |
| 桌面体验 | 支持深浅主题。项目路径失效后可以重新选择文件夹。 |

当前内置搭档为“白厄 + 神秘的古代机械”。

## 运行真实模式

真实编程功能需要本机安装 [OpenAI Codex](https://github.com/openai/codex)。先确认下面的命令可以运行：

```powershell
codex --version
```

复制 [.env.example](.env.example) 并填写模型配置。源码运行时可以把文件保存为仓库根目录的 `.env`。安装版会读取：

```text
%LOCALAPPDATA%\PairHarness\.env
```

也可以通过 `PAIR_HARNESS_ENV_FILE` 指定其他位置。

| 变量 | 用途 |
| --- | --- |
| `PAIR_HARNESS_DIALOGUE_BASE_URL` | 对话模型的 OpenAI 兼容地址。 |
| `PAIR_HARNESS_DIALOGUE_API_KEY` | 对话模型密钥。 |
| `PAIR_HARNESS_DIALOGUE_MODEL` | 对话模型名称。 |
| `PAIR_HARNESS_CODEX_BIN` | Codex 可执行文件路径，默认值为 `codex`。 |
| `DASHSCOPE_API_KEY` | DashScope 语音密钥。 |
| `PAIR_HARNESS_DASHSCOPE_HOST` | DashScope 工作空间域名。 |

语音 ID 保存在 [phainon_ancient_machine.yaml](config/pairs/phainon_ancient_machine.yaml)。使用自己的 DashScope 账号时，需要换成该账号下可用的声音。

## 从源码运行

开发环境需要 Python 3.11。桌面构建使用 Node.js 22 及 Rust stable。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[voice,dev]"

Set-Location desktop
npm install
npm run build:sidecar
npm run tauri:dev
```

## 测试

Python：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

React：

```powershell
Set-Location desktop
npm test -- --run
npm run typecheck
npm run build
```

Rust：

```powershell
Set-Location desktop\src-tauri
cargo test
```

## 构建安装包

```powershell
Set-Location desktop
npm run build:sidecar
npm run tauri -- build --bundles nsis
```

安装包会生成在 `desktop/src-tauri/target/release/bundle/nsis/`。

## 目录

| 路径 | 内容 |
| --- | --- |
| `desktop/` | Tauri 桌面端与 React 界面。 |
| `src/pair_harness/` | Python Sidecar 与业务代码。 |
| `config/` | 搭档配置和提示词。 |
| `assets/` | 运行时模型文件。 |
| `tests/` | Python 测试。 |
| `docs/architecture.md` | 当前桌面架构说明。 |

## 源码引用

[DeepSeek-Reasonix](https://github.com/esengine/deepseek-reasonix) 的供应商识别方式和推理档位语义用于 `src/pair_harness/config/providers.py`。相关代码已经改写为 Python，原项目采用 MIT License。完整声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

[OpenAI Codex](https://github.com/openai/codex) 是当前编程后端。应用连接用户本机安装的 Codex app-server，相关源码和二进制文件由 Codex 自己的发布渠道提供。

## 许可

项目代码采用 [Apache License 2.0](LICENSE)，版权所有 © 2026 Zonghe Wu。

角色名称与世界观相关内容归原权利人所有。本项目为非官方同人项目。
