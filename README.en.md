# HSR Partner Harness

[简体中文](README.md)

HSR Partner Harness is a Windows desktop application that keeps character conversation and local AI coding in one chat. You can discuss a task with Phainon, delegate it to the Mysterious Ancient Machine, watch the coding work as it happens, and continue talking while the task runs.

The current release is `v0.1.0`. The desktop client uses Tauri 2 and React. A Python sidecar owns conversation state and model integration.

## Download

The Windows x64 installer is available from [GitHub Releases](https://github.com/Jonah-Wu23/HSR_Partner_Harness/releases). The installer is currently unsigned, so Windows SmartScreen may show a warning.

When no model configuration is available, the application starts in demo mode. Demo mode shows the interface and interaction flow without calling live models.

## Features

| Feature | Details |
| --- | --- |
| Chat mode | Full-width character conversation with coding tools disabled. |
| Collaboration mode | Character chat and the assistant workspace remain visible together. Chat stays responsive during long coding tasks. |
| Projects | Each project maps to a local folder. Its initial name comes from the folder and can be renamed later. |
| Chat titles | New conversations begin as “新聊天”. After the first complete reply, the assistant generates a short title from the conversation. A manual rename always wins. |
| Coding | The assistant uses Codex app-server for file and command work. Tool activity appears as structured cards. |
| Approvals | Projects support request approval, automatic review, and full-auto execution modes. |
| Voice | DashScope provides ASR and TTS. Spoken replies are eligible for playback; tool records stay silent. |
| Desktop UI | Dark and light themes are included. Missing project folders can be selected again. |

The bundled pair is Phainon and the Mysterious Ancient Machine.

## Live mode

Live coding requires [OpenAI Codex](https://github.com/openai/codex) on the same machine. Confirm that it is available:

```powershell
codex --version
```

Copy [.env.example](.env.example) and fill in your provider settings. For a source checkout, save it as `.env` in the repository root. The installed application reads:

```text
%LOCALAPPDATA%\PairHarness\.env
```

Set `PAIR_HARNESS_ENV_FILE` to use another location.

| Variable | Purpose |
| --- | --- |
| `PAIR_HARNESS_DIALOGUE_BASE_URL` | OpenAI-compatible endpoint for character dialogue. |
| `PAIR_HARNESS_DIALOGUE_API_KEY` | Dialogue provider API key. |
| `PAIR_HARNESS_DIALOGUE_MODEL` | Dialogue model name. |
| `PAIR_HARNESS_CODEX_BIN` | Path to the Codex executable. Defaults to `codex`. |
| `DASHSCOPE_API_KEY` | DashScope API key for voice. |
| `PAIR_HARNESS_DASHSCOPE_HOST` | DashScope workspace host. |

Voice IDs live in [phainon_ancient_machine.yaml](config/pairs/phainon_ancient_machine.yaml). Replace them with voices available to your DashScope account.

## Run from source

Python 3.11 is required. Desktop builds use Node.js 22 and Rust stable.

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

React:

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

The installer is written to `desktop/src-tauri/target/release/bundle/nsis/`.

## Repository layout

| Path | Contents |
| --- | --- |
| `desktop/` | Tauri desktop client and React UI. |
| `src/pair_harness/` | Python sidecar and application logic. |
| `config/` | Pair configuration and prompts. |
| `assets/` | Runtime model assets. |
| `tests/` | Python tests. |
| `docs/architecture.md` | Current desktop architecture. |

## Source acknowledgements

The provider detection and reasoning-effort semantics in `src/pair_harness/config/providers.py` are adapted from [DeepSeek-Reasonix](https://github.com/esengine/deepseek-reasonix), licensed under the MIT License. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the complete notice.

[OpenAI Codex](https://github.com/openai/codex) is the current coding backend. The application connects to a locally installed Codex app-server. Codex source and binaries are not included in this repository.

## License

Project code is licensed under the [Apache License 2.0](LICENSE). Copyright © 2026 Zonghe Wu.

Character names and related fictional settings belong to their respective rights holders. This is an unofficial fan project and is not affiliated with or endorsed by miHoYo or HoYoverse.
