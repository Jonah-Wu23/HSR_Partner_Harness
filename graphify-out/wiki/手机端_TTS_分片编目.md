# 手机端 TTS 分片编目

> 19 nodes · cohesion 0.11

## Key Concepts

- **MobileTtsSequencer** (13 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **TtsStream** (8 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.begin()** (4 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.finish()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.chunk()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **test_sequencer_stop_marks_handle_and_frees_message_id()** (3 connections) — `tests/unit/test_mobile_audio.py`
- **.__init__()** (2 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.__init__()** (2 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.stop()** (2 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.end_payload()** (2 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **Any** (1 connections)
- **一条下行 TTS 消息的分片编目。 ``stopped`` 由 :meth:`MobileTtsSequencer.stop` 置位；生产者在下发每个分片…** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **返回 ``voice.mobile_tts_chunk`` 载荷，``seq`` 从 0 递增。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **返回 ``voice.mobile_tts_end`` 载荷。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **按 message_id 登记进行中的下行 TTS 消息，供手机端停止与新回复抢占时中断。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **登记并返回句柄；同一 message_id 仍在下发时抛 ``voice_tts_message_exists``。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **中断进行中的消息；未知或已结束的 message_id 直接返回。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **生产者结束（完成、失败或被中断）后注销句柄。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **stop 把生产者持有的句柄置为 stopped；同一 id 之后可以重新登记，旧句柄不受影响。** (1 connections) — `tests/unit/test_mobile_audio.py`

## Relationships

- [手机端 ASR 会话测试](手机端_ASR_会话测试.md) (4 shared connections)
- [手机语音分片会话协议](手机语音分片会话协议.md) (2 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (2 shared connections)
- [手机音频转写会话](手机音频转写会话.md) (2 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (2 shared connections)
- [语音运行时装配与中继](语音运行时装配与中继.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/mobile_audio.py`
- `tests/unit/test_mobile_audio.py`

## Audit Trail

- EXTRACTED: 26 (81%)
- INFERRED: 6 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*