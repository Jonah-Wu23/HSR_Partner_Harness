# HSR Partner Harness

[简体中文](README.md)

[![Website](https://img.shields.io/badge/website-jonah--wu23.github.io-E8B25C)](https://jonah-wu23.github.io/HSR_Partner_Harness/)
[![GitHub Pages](https://img.shields.io/github/deployments/Jonah-Wu23/HSR_Partner_Harness/github-pages?label=pages)](https://jonah-wu23.github.io/HSR_Partner_Harness/)
[![Version](https://img.shields.io/badge/version-v0.2.0-E8B25C)](https://github.com/Jonah-Wu23/HSR_Partner_Harness/releases)
[![CI](https://github.com/Jonah-Wu23/HSR_Partner_Harness/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Jonah-Wu23/HSR_Partner_Harness/actions/workflows/ci.yml)

Project website: <https://jonah-wu23.github.io/HSR_Partner_Harness/>

HSR Partner Harness is a Windows desktop app where character chat and local AI coding happen in the same conversation. You can talk the plan through with Phainon first, hand the task to the Mysterious Ancient Machine once you agree, and the progress and results come back into the same conversation for Phainon to respond to.

The current release is `v0.2.0`. The interface is built with Tauri 2 and React, and a Python sidecar manages session state and model calls.

The product is a local Windows workspace for development and research prototypes, with character-driven interaction built into the workflow. It keeps planning and execution in one session. The current release focuses on local Windows workflows, with model requests sent to the provider configured by you.

## Quality gates

GitHub Actions runs Python tests, frontend tests and builds, plus Rust formatting and tests on a Windows runner. Pull requests trigger dependency review, while CodeQL checks the Python and TypeScript code.

## Product focus

| Focus | What it means |
| --- | --- |
| One session, two work tracks | Chat mode keeps the character conversation focused. Collaboration mode opens the assistant workspace while the conversation stays available. |
| GPT-5.6 Sol coding assistant | Coding turns use [gpt-5.6-sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol). Composer has five reasoning levels; see the mapping table below. |
| Visible task control | Codex app-server tool activity appears as structured cards, and each project can save an approval policy. |
| Local project binding | Each project maps to a local folder, while the Python sidecar owns session state and SQLite stores local data. |

| Composer level | API effort |
| --- | --- |
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra high | `xhigh` |
| Maximum | `max` |

## How it works

```mermaid
flowchart LR
    A[Character chat] --> B{Collaboration mode}
    B --> C[Structured task]
    C --> D[Codex app-server]
    D --> E[Files and commands]
    E --> F[Structured result]
    F --> A
```

See the [product website](https://jonah-wu23.github.io/HSR_Partner_Harness/) for the visual walkthrough.

## Download

The Windows x64 installer is published on [GitHub Releases](https://github.com/Jonah-Wu23/HSR_Partner_Harness/releases). First-time installation may trigger a Windows SmartScreen warning.

The app includes a demo mode for the interface and interaction experience. Add model settings to run live models.

## Features

| Feature | Notes |
| --- | --- |
| Chat mode | The whole screen shows the character conversation, with the coding tools closed. |
| Collaboration mode | The character chat and the assistant workspace share the screen, and you can keep talking while a task runs. |
| Projects | Each project maps to a local folder. The name defaults to the folder name, and you can change it any time. |
| Chat titles | A new conversation shows "新聊天" first. After the first complete reply, the assistant generates a title from the content, and manual renames take priority. |
| Coding | The assistant handles files and commands through the Codex app-server, and the tool work shows up as cards. |
| Reasoning levels | The coding assistant uses GPT-5.6 Sol. Composer maps five interface levels to the API effort values in the table above. |
| Approvals | Each project can save an approval policy for tool execution. |
| Voice | Voice runs on DashScope ASR and TTS. Character replies can be read aloud, while tool records stay silent. |
| UI | There are dark and light themes, and you can reselect a project folder at any time. |

The bundled pair is Phainon and the Mysterious Ancient Machine.

## Live mode

When running from source, live coding depends on [OpenAI Codex](https://github.com/openai/codex) installed on this machine. Check that the command works:

```powershell
codex --version
```

Then copy [.env.example](.env.example) and fill in the model settings. Running from source reads `.env` in the repository root, while the installed application reads `%LOCALAPPDATA%\PairHarness\.env`. To keep the config somewhere else, set `PAIR_HARNESS_ENV_FILE` to that path.

When a config file is found, the app starts in live mode by default. `PAIR_HARNESS_REAL=1` forces live mode, and `PAIR_HARNESS_DEMO=1` forces demo mode.

The dialogue model works with DeepSeek and OpenAI-compatible endpoints. The variables are:

| Variable | Purpose |
| --- | --- |
| `PAIR_HARNESS_DIALOGUE_BASE_URL` | OpenAI-compatible endpoint for the dialogue model. |
| `PAIR_HARNESS_DIALOGUE_API_KEY` | Dialogue model API key. |
| `PAIR_HARNESS_DIALOGUE_MODEL` | Dialogue model name. |
| `PAIR_HARNESS_CODEX_BIN` | Override for the Codex executable. Installed builds use the bundled Codex by default. |
| `DASHSCOPE_API_KEY` | DashScope API key for voice. |
| `PAIR_HARNESS_DASHSCOPE_HOST` | DashScope workspace host. |

Voice IDs are set in [phainon_ancient_machine.yaml](config/pairs/phainon_ancient_machine.yaml). If you use your own DashScope account, replace them with voices that account can use.

## Run from source

Development needs Python 3.11, and desktop builds need Node.js 22 and Rust stable.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[voice,dev]"

Set-Location desktop
npm install
npm run build:sidecar
npm run tauri:dev
```

Release builds copy the native Windows Codex app-server into the installer. The build machine
needs `@openai/codex` installed, or `PAIR_HARNESS_CODEX_NATIVE_ROOT` set to a native release
directory containing `bin\codex.exe`:

```powershell
npm install -g @openai/codex
Set-Location desktop
npm run tauri:build
```

The installer is written to `desktop/src-tauri/target/release/bundle/nsis/`, and the directly
runnable GUI executable is `desktop/src-tauri/target/release/hsr-partner-harness.exe`. Normal
launches hide the console window. For development diagnostics, run
`hsr-partner-harness.exe --debug-console` (`--console` is an alias) to keep a console and see
Sidecar logs.

## Tests

Python:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Frontend tests and builds, all in `desktop`:

```powershell
Set-Location desktop
npm test -- --run
npm run typecheck
npm run build
```

Rust:

```powershell
Set-Location desktop\src-tauri
cargo test
```

## Build the installer

```powershell
Set-Location desktop
npm run build:sidecar
npm run tauri -- build --bundles nsis
```

The finished installer is written to `desktop/src-tauri/target/release/bundle/nsis/`.

## Repository layout

| Path | Contents |
| --- | --- |
| `desktop/` | Tauri desktop client and React UI. |
| `src/pair_harness/` | Python sidecar and application logic. |
| `config/` | Pair configuration and prompts. |
| `assets/` | Runtime model files. |
| `tests/` | Python tests. |
| `docs/architecture.md` | Desktop architecture notes. |

## Third-party code

The provider detection and reasoning-effort semantics in `src/pair_harness/config/providers.py` are rewritten from [DeepSeek-Reasonix](https://github.com/esengine/deepseek-reasonix), which uses the MIT License. The full notice is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The coding assistant connects to [OpenAI Codex](https://github.com/openai/codex) through the
local Codex app-server, which handles files and commands.

## License

The code is under the [Apache License 2.0](LICENSE). Copyright © 2026 Zonghe Wu.

This project is a fan project. Character names and related fictional settings belong to their rights holders.
