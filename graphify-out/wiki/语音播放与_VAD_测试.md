# 语音播放与 VAD 测试

> 40 nodes · cohesion 0.12

## Key Concepts

- **test_voice_runtime.py** (35 connections) — `tests/unit/test_voice_runtime.py`
- **make_runtime()** (32 connections) — `tests/unit/test_voice_runtime.py`
- **FakeVad** (18 connections) — `tests/voice_helpers.py`
- **FakeRecognizer** (16 connections) — `tests/voice_helpers.py`
- **FakeSynthesizer** (14 connections) — `tests/voice_helpers.py`
- **test_push_to_talk_stops_playback_then_commits()** (10 connections) — `tests/unit/test_voice_runtime.py`
- **_stop_playback()** (9 connections) — `tests/unit/test_voice_runtime.py`
- **test_push_to_talk_stop_does_not_wait_for_model_turn()** (8 connections) — `tests/unit/test_voice_runtime.py`
- **test_skip_playing_aborts_current_and_continues_next()** (8 connections) — `tests/unit/test_voice_runtime.py`
- **test_skip_playing_with_empty_queue_stops()** (8 connections) — `tests/unit/test_voice_runtime.py`
- **test_tts_playing_waits_for_audio_output_to_drain()** (8 connections) — `tests/unit/test_voice_runtime.py`
- **FakeRecognizer** (7 connections)
- **test_on_message_plays_character_only_and_filters_assistant_and_others()** (7 connections) — `tests/unit/test_voice_runtime.py`
- **test_playback_pauses_vad_feeding_and_resumes()** (7 connections) — `tests/unit/test_voice_runtime.py`
- **test_replay_message_reads_user_text_with_character_voice()** (7 connections) — `tests/unit/test_voice_runtime.py`
- **test_false_trigger_not_committed()** (6 connections) — `tests/unit/test_voice_runtime.py`
- **test_on_message_skips_punctuation_only_text()** (6 connections) — `tests/unit/test_voice_runtime.py`
- **test_push_to_talk_works_when_vad_is_disabled()** (6 connections) — `tests/unit/test_voice_runtime.py`
- **test_vad_full_flow_commits_character_input()** (6 connections) — `tests/unit/test_voice_runtime.py`
- **test_vad_unavailable_falls_back_to_push_to_talk()** (5 connections) — `tests/unit/test_voice_runtime.py`
- **test_empty_final_not_committed()** (4 connections) — `tests/unit/test_voice_runtime.py`
- **test_skip_playing_when_idle_is_noop()** (4 connections) — `tests/unit/test_voice_runtime.py`
- **test_enqueue_text_preview_defaults_to_character_voice()** (3 connections) — `tests/unit/test_voice_runtime.py`
- **test_shutdown_closes_capture_player_and_background_tasks()** (3 connections) — `tests/unit/test_voice_runtime.py`
- **test_stop_speaking_stops_player_and_clears_queue()** (3 connections) — `tests/unit/test_voice_runtime.py`
- *... and 15 more nodes in this community*

## Relationships

- [千问语音合成与识别](千问语音合成与识别.md) (17 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (12 shared connections)
- [语音设备抢占互斥](语音设备抢占互斥.md) (6 shared connections)
- [对话供应商与搭档配置](对话供应商与搭档配置.md) (5 shared connections)
- [语音运行时测试替身](语音运行时测试替身.md) (5 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (5 shared connections)
- [语音抢占测试](语音抢占测试.md) (4 shared connections)
- [语音运行态 TTS 失败恢复](语音运行态_TTS_失败恢复.md) (3 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (3 shared connections)
- [麦克风采集测试替身](麦克风采集测试替身.md) (2 shared connections)
- [朗读队列与 epoch](朗读队列与_epoch.md) (2 shared connections)
- [语音测试辅助替身](语音测试辅助替身.md) (2 shared connections)

## Source Files

- `tests/unit/test_voice_runtime.py`
- `tests/voice_helpers.py`

## Audit Trail

- EXTRACTED: 143 (87%)
- INFERRED: 21 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*