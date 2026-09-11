# 移动端音频与 ASR 会话

> 70 nodes · cohesion 0.06

## Key Concepts

- **MobileAudioError** (30 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **MobileAsrSessionManager** (28 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **test_mobile_audio.py** (24 connections) — `tests/unit/test_mobile_audio.py`
- **MobileTtsSequencer** (20 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **mobile_audio.py** (14 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **FakeRecognizer** (11 connections) — `tests/unit/test_mobile_audio.py`
- **b64()** (9 connections) — `tests/unit/test_mobile_audio.py`
- **MobileTtsInterrupted** (8 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **_AsrSession** (7 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **._live_entry()** (7 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.end_session()** (5 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **._get_session()** (5 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **._pump_async()** (5 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.start_session()** (5 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.feed()** (5 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **test_cancel_all_for_connection_is_silent_and_scoped()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **test_lifecycle_start_feed_end_returns_final()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **test_partial_callbacks_emitted()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **test_sequencer_stop_then_feed_is_interrupted_and_reuse_rejected()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **test_sequencer_stopped_ledger_counts_unique_ids()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **test_sequencer_unknown_message_still_reports_protocol_error()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **_feed_stream()** (4 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.feed_chunk()** (4 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **._on_asr_event()** (4 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.begin()** (4 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- *... and 45 more nodes in this community*

## Relationships

- [adapters: DemoSpeechRecogniz…](adapters-_DemoSpeechRecogniz….md) (7 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (4 shared connections)
- [V0.3.5 接线测试](V0.3.5_接线测试.md) (3 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (3 shared connections)
- [千问流式语音识别](千问流式语音识别.md) (3 shared connections)
- [委派与契约模型](委派与契约模型.md) (2 shared connections)
- [后端引导与快照解析](后端引导与快照解析.md) (2 shared connections)
- [desktop_backend: .cancel_all_for_co…](desktop_backend-_.cancel_all_for_co….md) (2 shared connections)
- [test_v039_s4_application_fixes.py: MonkeyPatch](test_v039_s4_application_fixes.py-_MonkeyPatch.md) (2 shared connections)
- [desktop_backend: ._prune_stopped()](desktop_backend-_._prune_stopped.md) (2 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/mobile_audio.py`
- `tests/unit/test_mobile_audio.py`
- `tests/unit/test_v035_wiring.py`

## Audit Trail

- EXTRACTED: 128 (73%)
- INFERRED: 47 (27%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*