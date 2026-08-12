# HSR Partner Harness

[简体中文](README.md)

[![Website](https://img.shields.io/badge/website-jonah--wu23.github.io-E8B25C)](https://jonah-wu23.github.io/HSR_Partner_Harness/)
[![GitHub Pages](https://img.shields.io/github/deployments/Jonah-Wu23/HSR_Partner_Harness/github-pages?label=pages)](https://jonah-wu23.github.io/HSR_Partner_Harness/)

Project website: <https://jonah-wu23.github.io/HSR_Partner_Harness/>

HSR Partner Harness is a Windows desktop app where character chat and local AI coding happen in the same conversation. You can talk the plan through with Phainon first, hand the task to the Mysterious Ancient Machine once you agree, and the progress and results come back into the same conversation for Phainon to respond to.

The current release is `v0.1.0`. The interface is built with Tauri 2 and React, and a Python sidecar manages session state and model calls.

## Download

The Windows x64 installer is published on [GitHub Releases](https://github.com/Jonah-Wu23/HSR_Partner_Harness/releases), and it has no code signature, so Windows SmartScreen may show a warning.

When there is no model configuration, the app starts in demo mode, where the interface and interactions all work but no live models are called.

## Features

| Feature | Notes |
| --- | --- |
| Chat mode | The whole screen shows the character conversation, with the coding tools closed. |
| Collaboration mode | The character chat and the assistant workspace share the screen, and you can keep talking while a task runs. |
| Projects | Each project maps to a local folder. The name defaults to the folder name, and you can change it any time. |
| Chat titles | A new conversation shows "新聊天" first. After the first complete reply, the assistant generates a title from the content, and a manual rename is never overwritten. |
| Coding | The assistant handles files and commands through the Codex app-server, and the tool work shows up as cards. |
| Approvals | Each project picks one of three approval modes: request approval, automatic review, or full auto. |
| Voice | Voice runs on DashScope ASR and TTS. Character replies can be read aloud, while tool records stay silent. |
| UI | There are dark and light themes, and you can re-select a project folder if its path stops working. |

The bundled pair is Phainon and the Mysterious Ancient Machine.

## Live mode

Live coding depends on [OpenAI Codex](https://github.com/openai/codex) installed on this machine. Check that the command works:

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
| `PAIR_HARNESS_CODEX_BIN` | Path to the Codex executable. Defaults to `codex`. |
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

The coding backend is [OpenAI Codex](https://github.com/openai/codex). The app connects to the Codex app-server installed on your machine, and the repository contains no Codex source or binaries.

## License

The code is under the [Apache License 2.0](LICENSE). Copyright © 2026 Zonghe Wu.

Character names and related fictional settings belong to their rights holders. This is an unofficial fan project, not affiliated with or endorsed by miHoYo or HoYoverse.
