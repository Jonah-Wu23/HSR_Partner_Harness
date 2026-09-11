# 复现脚本与 ACP 链路

> 128 nodes · cohesion 0.03

## Key Concepts

- **application_service.py** (189 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **openai_compatible.py** (50 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **cli.py** (42 connections) — `src/pair_harness/cli.py`
- **_build_service()** (32 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **load_pair_config()** (31 connections) — `src/pair_harness/config/pairs.py`
- **voice_runtime.py** (28 connections) — `src/pair_harness/core/voice_runtime.py`
- **run_real()** (22 connections) — `src/pair_harness/cli.py`
- **load_reasoning_preset()** (22 connections) — `src/pair_harness/config/providers.py`
- **voice_factory.py** (21 connections) — `src/pair_harness/desktop_backend/voice_factory.py`
- **Settings** (21 connections) — `src/pair_harness/settings.py`
- **pairs.py** (20 connections) — `src/pair_harness/config/pairs.py`
- **build_real_voice_runtime()** (20 connections) — `src/pair_harness/desktop_backend/voice_factory.py`
- **load_prompt()** (17 connections) — `src/pair_harness/config/pairs.py`
- **PairConfig** (17 connections) — `src/pair_harness/config/pairs.py`
- **providers.py** (17 connections) — `src/pair_harness/config/providers.py`
- **detect_provider()** (15 connections) — `src/pair_harness/config/providers.py`
- **deepseek_request_extras()** (14 connections) — `src/pair_harness/config/providers.py`
- **load_dotenv()** (12 connections) — `src/pair_harness/cli.py`
- **voices.py** (12 connections) — `src/pair_harness/config/voices.py`
- **build_configured_service()** (12 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **resolve_effective_voice_profile()** (12 connections) — `src/pair_harness/desktop_backend/voice_factory.py`
- **AppPaths** (11 connections) — `src/pair_harness/app_paths.py`
- **auth.py** (10 connections) — `src/pair_harness/adapters/codex/auth.py`
- **main()** (10 connections) — `src/pair_harness/cli.py`
- **list_pair_configs()** (10 connections) — `src/pair_harness/config/pairs.py`
- *... and 103 more nodes in this community*

## Relationships

- [Codex 对话模型](Codex_对话模型.md) (31 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (28 shared connections)
- [委派与契约模型](委派与契约模型.md) (23 shared connections)
- [desktop_backend: DiagnosticCallback](desktop_backend-_DiagnosticCallback.md) (17 shared connections)
- [语音运行时接线](语音运行时接线.md) (16 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (13 shared connections)
- [角色上下文窗口与摘要](角色上下文窗口与摘要.md) (11 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (10 shared connections)
- [会话编排器](会话编排器.md) (10 shared connections)
- [音色绑定与参考音](音色绑定与参考音.md) (10 shared connections)
- [摘要事件载荷与身份](摘要事件载荷与身份.md) (10 shared connections)
- [千问音频实网测试](千问音频实网测试.md) (9 shared connections)

## Source Files

- `scripts/repro_acp_engine.py`
- `scripts/repro_acp_raw.py`
- `scripts/repro_character_reply.py`
- `scripts/repro_onboarding_flow.py`
- `src/pair_harness/__main__.py`
- `src/pair_harness/adapters/codex/auth.py`
- `src/pair_harness/adapters/dialogue/openai_compatible.py`
- `src/pair_harness/app_paths.py`
- `src/pair_harness/cli.py`
- `src/pair_harness/config/pairs.py`
- `src/pair_harness/config/providers.py`
- `src/pair_harness/config/voices.py`
- `src/pair_harness/core/voice_runtime.py`
- `src/pair_harness/desktop_backend/application_service.py`
- `src/pair_harness/desktop_backend/voice_factory.py`
- `src/pair_harness/settings.py`
- `tests/unit/test_dialogue_provider_presets.py`
- `tests/unit/test_pair_config.py`

## Audit Trail

- EXTRACTED: 658 (95%)
- INFERRED: 33 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*