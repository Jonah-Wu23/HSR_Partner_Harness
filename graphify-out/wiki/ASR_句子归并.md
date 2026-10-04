# ASR 句子归并

> 6 nodes · cohesion 0.33

## Key Concepts

- **merge_asr_sentences()** (5 connections) — `src/pair_harness/adapters/audio/qwen_asr.py`
- **test_asr_merge.py** (3 connections) — `tests/unit/test_asr_merge.py`
- **test_merge_asr_sentences_by_begin_time()** (3 connections) — `tests/unit/test_asr_merge.py`
- **Any** (1 connections)
- **把 SDK 结果事件里的 sentence 按 ``begin_time`` 归并为当前转写。 同一 ``begin_time``…** (1 connections) — `src/pair_harness/adapters/audio/qwen_asr.py`
- **parametrize** (1 connections)

## Relationships

- [千问语音合成与识别](千问语音合成与识别.md) (2 shared connections)
- [千问流式语音识别](千问流式语音识别.md) (1 shared connections)
- [手机端 ASR 会话测试](手机端_ASR_会话测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_asr.py`
- `tests/unit/test_asr_merge.py`

## Audit Trail

- EXTRACTED: 9 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*