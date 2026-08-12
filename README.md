# HSR Partner Harness

[English](README.en.md)

[![Website](https://img.shields.io/badge/website-jonah--wu23.github.io-E8B25C)](https://jonah-wu23.github.io/HSR_Partner_Harness/)
[![GitHub Pages](https://img.shields.io/github/deployments/Jonah-Wu23/HSR_Partner_Harness/github-pages?label=pages)](https://jonah-wu23.github.io/HSR_Partner_Harness/)

介绍网站：<https://jonah-wu23.github.io/HSR_Partner_Harness/>

HSR Partner Harness 是一个 Windows 桌面应用，角色聊天和本地 AI 编程在同一场会话里进行。你可以先和白厄商量思路，谈妥了把任务交给神秘的古代机械，执行的进度和结果会回到这场对话里，白厄再根据结果接着聊。

当前版本 `v0.1.0`，界面用 Tauri 2 和 React 实现，Python Sidecar 管理会话状态和模型调用。

## 下载

Windows x64 安装包发布在 [GitHub Releases](https://github.com/Jonah-Wu23/HSR_Partner_Harness/releases)，安装包没有代码签名，Windows SmartScreen 可能会弹出提醒。

模型配置没填的时候，应用会进入 demo 模式，界面和交互照常可以体验，只是不会调用真实模型。

## 当前功能

| 功能 | 说明 |
| --- | --- |
| 聊天模式 | 整个界面只显示角色对话，编程工具都关闭。 |
| 协作模式 | 角色对话和助手工作台一起显示，任务跑着的时候也能继续聊天。 |
| 项目管理 | 一个项目对应一个本地文件夹，名字默认取文件夹名，之后随时能改。 |
| 聊天标题 | 新会话先显示“新聊天”，第一次完整回复结束后，助手会根据内容生成标题。手动改过的名字不会被自动标题覆盖。 |
| 编程执行 | 助手通过 Codex app-server 处理文件和命令，工具的执行过程显示为卡片。 |
| 审批 | 每个项目单独选择审批方式，有请求批准、自动审核、完全允许三档。 |
| 语音 | 语音用 DashScope 的 ASR 和 TTS，角色回复可以朗读，工具记录保持静音。 |
| 界面 | 有深色和浅色两套主题，项目文件夹失效之后可以重新选择路径。 |

内置搭档是白厄和神秘的古代机械。

## 运行真实模式

真实的编程功能要靠本机装好的 [OpenAI Codex](https://github.com/openai/codex)，先确认命令可用：

```powershell
codex --version
```

再复制一份 [.env.example](.env.example) 填上模型配置。从源码运行的话，把文件存成仓库根目录的 `.env` 就行，安装版读取的是 `%LOCALAPPDATA%\PairHarness\.env`。想把配置文件放在别的位置，就用 `PAIR_HARNESS_ENV_FILE` 指定。

找到配置文件的时候，应用默认进入真实模式，也可以用 `PAIR_HARNESS_REAL=1` 强制真实模式，或者 `PAIR_HARNESS_DEMO=1` 强制 demo 模式。

对话模型支持 DeepSeek 和 OpenAI 兼容的地址，相关变量如下。

| 变量 | 用途 |
| --- | --- |
| `PAIR_HARNESS_DIALOGUE_BASE_URL` | 对话模型的 OpenAI 兼容地址。 |
| `PAIR_HARNESS_DIALOGUE_API_KEY` | 对话模型的密钥。 |
| `PAIR_HARNESS_DIALOGUE_MODEL` | 对话模型的名称。 |
| `PAIR_HARNESS_CODEX_BIN` | Codex 可执行文件的路径，默认是 `codex`。 |
| `DASHSCOPE_API_KEY` | DashScope 的语音密钥。 |
| `PAIR_HARNESS_DASHSCOPE_HOST` | DashScope 工作空间的域名。 |

声音 ID 写在 [phainon_ancient_machine.yaml](config/pairs/phainon_ancient_machine.yaml) 里，如果用的是自己的 DashScope 账号，要换成这个账号下能用的声音。

## 从源码运行

开发环境需要 Python 3.11，桌面构建需要 Node.js 22 和 Rust stable。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[voice,dev]"

Set-Location desktop
npm install
npm run build:sidecar
npm run tauri:dev
```

## 测试

Python 测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

前端的测试和构建都在 `desktop` 目录下：

```powershell
Set-Location desktop
npm test -- --run
npm run typecheck
npm run build
```

Rust 测试：

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

生成的安装包在 `desktop/src-tauri/target/release/bundle/nsis/` 下面。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `desktop/` | Tauri 桌面端和 React 界面。 |
| `src/pair_harness/` | Python Sidecar 和业务代码。 |
| `config/` | 搭档配置和提示词。 |
| `assets/` | 运行时模型文件。 |
| `tests/` | Python 测试。 |
| `docs/architecture.md` | 桌面架构说明。 |

## 外部代码

`src/pair_harness/config/providers.py` 里的供应商识别方式和推理档位语义是从 [DeepSeek-Reasonix](https://github.com/esengine/deepseek-reasonix) 改写来的，原项目用 MIT License，完整声明在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

编程后端用的是 [OpenAI Codex](https://github.com/openai/codex)，应用连接的是你本机装好的 Codex app-server，仓库里不包含 Codex 的源码和二进制文件。

## 许可

代码采用 [Apache License 2.0](LICENSE)，版权所有 © 2026 Zonghe Wu。

角色名称和世界观相关的内容归原权利人所有，本项目是非官方的同人作品。
