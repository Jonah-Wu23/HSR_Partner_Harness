# HTTP 回放测试夹具

> 49 nodes · cohesion 0.07

## Key Concepts

- **test_card_voice.py** (26 connections) — `tests/unit/test_card_voice.py`
- **ReplayHttpServer** (15 connections) — `tests/fixtures/replay_http.py`
- **_configure_voice()** (9 connections) — `tests/unit/test_card_voice.py`
- **SpeakerRecorder** (9 connections) — `tests/unit/test_card_voice.py`
- **test_clone_creates_voice_from_reference_audio()** (8 connections) — `tests/unit/test_card_voice.py`
- **_card_with_reference()** (7 connections) — `tests/unit/test_card_voice.py`
- **test_card_create_failure_keeps_previous_voice_id()** (7 connections) — `tests/unit/test_card_voice.py`
- **test_card_create_failure_reports_http_status_once()** (7 connections) — `tests/unit/test_card_voice.py`
- **test_card_create_rejects_duplicate_while_in_progress()** (7 connections) — `tests/unit/test_card_voice.py`
- **_profile()** (6 connections) — `tests/unit/test_card_voice.py`
- **test_unbind_resets_voice_and_keeps_reference()** (6 connections) — `tests/unit/test_card_voice.py`
- **test_bind_reference_rejects_invalid_audio()** (5 connections) — `tests/unit/test_card_voice.py`
- **_voice_created()** (5 connections) — `tests/unit/test_card_voice.py`
- **_write_wav()** (5 connections) — `tests/unit/test_card_voice.py`
- **replay_http.py** (4 connections) — `tests/fixtures/replay_http.py`
- **replay_http()** (4 connections) — `tests/fixtures/replay_http.py`
- **._handle()** (4 connections) — `tests/fixtures/replay_http.py`
- **_provision_events()** (4 connections) — `tests/unit/test_card_voice.py`
- **_rejected()** (4 connections) — `tests/unit/test_card_voice.py`
- **test_bind_reference_stores_wav_asset()** (4 connections) — `tests/unit/test_card_voice.py`
- **test_card_preview_requires_runtime_and_ready_voice()** (4 connections) — `tests/unit/test_card_voice.py`
- **test_clone_without_bound_reference_reports_missing()** (4 connections) — `tests/unit/test_card_voice.py`
- **.hold()** (3 connections) — `tests/fixtures/replay_http.py`
- **Any** (3 connections)
- **test_card_voice_applies_only_to_bound_conversation()** (3 connections) — `tests/unit/test_card_voice.py`
- *... and 24 more nodes in this community*

## Relationships

- [角色卡绑定与命令测试](角色卡绑定与命令测试.md) (21 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (2 shared connections)
- [千问音色复刻工具](千问音色复刻工具.md) (1 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (1 shared connections)

## Source Files

- `tests/fixtures/replay_http.py`
- `tests/unit/test_card_voice.py`

## Audit Trail

- EXTRACTED: 106 (97%)
- INFERRED: 3 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*