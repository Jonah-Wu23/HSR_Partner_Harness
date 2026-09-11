# adapters: 距离下一次可起始还需等待的秒数（<=…

> 18 nodes · cohesion 0.13

## Key Concepts

- **_SynthesisPacer** (12 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **._interval_s()** (5 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **.mark_started()** (3 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **.note_failure()** (3 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **test_stale_success_does_not_clear_newer_failure()** (3 connections) — `tests/unit/test_qwen_event_mapping.py`
- **test_synthesis_pacer_backoff_grows_4_8_16_then_success_resets()** (3 connections) — `tests/unit/test_qwen_event_mapping.py`
- **.note_success()** (2 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **.wait_s()** (2 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **距离下一次可起始还需等待的秒数（<=0 表示现在即可起始）。** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **占用一个起始时隙，返回本次尝试的序号（用于成功/失败归账）。** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **记一次失败：下一次起始至少等一个（更长的）退避间隔。** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **记一次完整成功（上游 complete 终态）并清除失败退避。 只有比最近一次失败更新的尝试才算数：更早尝试的迟到成功不清除较新 失败的退避。只出了部分…** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **相邻两次上行合成起始的最小间隔（进程共享、线程安全）。 ``wait_s()`` 只读不占位，``mark_started()`` 在真正起始时占用时隙，…** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **.failure_streak()** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **.reset()** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **连续失败按 4/8/16s 增长（真实常量），未被“部分成功”提前压回 4s。** (1 connections) — `tests/unit/test_qwen_event_mapping.py`
- **复核确证1：旧尝试的迟到成功不得清掉较新失败的退避（按尝试时序归账）。** (1 connections) — `tests/unit/test_qwen_event_mapping.py`

## Relationships

- [千问语音合成适配器](千问语音合成适配器.md) (3 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_tts.py`
- `tests/unit/test_qwen_event_mapping.py`

## Audit Trail

- EXTRACTED: 23 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*