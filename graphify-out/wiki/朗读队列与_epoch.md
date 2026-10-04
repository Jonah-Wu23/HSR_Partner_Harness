# 朗读队列与 epoch

> 23 nodes · cohesion 0.11

## Key Concepts

- **SpeechQueue** (32 connections) — `src/pair_harness/core/audio.py`
- **test_speech_queue.py** (6 connections) — `tests/unit/test_speech_queue.py`
- **_request()** (5 connections) — `tests/unit/test_speech_queue.py`
- **.interrupt()** (3 connections) — `src/pair_harness/core/audio.py`
- **.stop()** (3 connections) — `src/pair_harness/core/audio.py`
- **test_queue_keeps_fifo_order()** (3 connections) — `tests/unit/test_speech_queue.py`
- **test_skip_current_keeps_pending_on_new_epoch()** (3 connections) — `tests/unit/test_speech_queue.py`
- **test_stop_advances_epoch_and_clears_queue()** (3 connections) — `tests/unit/test_speech_queue.py`
- **.enqueue()** (2 connections) — `src/pair_harness/core/audio.py`
- **.pending_message_id()** (2 connections) — `src/pair_harness/core/audio.py`
- **.pop_next()** (2 connections) — `src/pair_harness/core/audio.py`
- **.skip_current()** (2 connections) — `src/pair_harness/core/audio.py`
- **待朗读语音队列（单调 epoch）。 playing 表示正在播放；播放期间暂停 VAD，停止或播完后恢复。…** (1 connections) — `src/pair_harness/core/audio.py`
- **队首待播条目的 message_id（无待播项时 None）。** (1 connections) — `src/pair_harness/core/audio.py`
- **中断：epoch 递增、清空队列、复位 playing，返回新 epoch。** (1 connections) — `src/pair_harness/core/audio.py`
- **跳过当前句：epoch 递增，待播项改挂新 epoch（不清空队列）。** (1 connections) — `src/pair_harness/core/audio.py`
- **停止播放并清空队列，VAD 随之恢复（等价于一次中断）。** (1 connections) — `src/pair_harness/core/audio.py`
- **.begin_playback()** (1 connections) — `src/pair_harness/core/audio.py`
- **.end_playback()** (1 connections) — `src/pair_harness/core/audio.py`
- **.epoch()** (1 connections) — `src/pair_harness/core/audio.py`
- **.__init__()** (1 connections) — `src/pair_harness/core/audio.py`
- **.pending()** (1 connections) — `src/pair_harness/core/audio.py`
- **.playing()** (1 connections) — `src/pair_harness/core/audio.py`

## Relationships

- [千问语音合成与识别](千问语音合成与识别.md) (9 shared connections)
- [语音抢占测试](语音抢占测试.md) (4 shared connections)
- [语音设备抢占互斥](语音设备抢占互斥.md) (3 shared connections)
- [语音运行时装配与中继](语音运行时装配与中继.md) (2 shared connections)
- [语音播放与 VAD 测试](语音播放与_VAD_测试.md) (2 shared connections)
- [语音上下行协调器](语音上下行协调器.md) (1 shared connections)

## Source Files

- `src/pair_harness/core/audio.py`
- `tests/unit/test_speech_queue.py`

## Audit Trail

- EXTRACTED: 38 (78%)
- INFERRED: 11 (22%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*