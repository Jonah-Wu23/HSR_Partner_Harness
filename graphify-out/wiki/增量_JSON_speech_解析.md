# 增量 JSON speech 解析

> 9 nodes · cohesion 0.22

## Key Concepts

- **IncrementalJsonSpeechParser** (10 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **incremental_json.py** (3 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **test_parser_extracts_clean_speech_across_chunk_boundaries()** (3 connections) — `tests/unit/test_incremental_json.py`
- **.feed()** (2 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **.speech()** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **喂入一段 content 分片，返回新增的 speech 文本。** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **从流式 content 分片中提取 speech 预览增量。 输出按部分 JSON 解析，只取顶层 speech 字符串值，转义序列解码后上屏。…** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **parametrize** (1 connections)

## Relationships

- [增量 JSON 流解析测试](增量_JSON_流解析测试.md) (3 shared connections)
- [OpenAI 兼容对话解析](OpenAI_兼容对话解析.md) (2 shared connections)
- [OpenAI 兼容对话模型](OpenAI_兼容对话模型.md) (2 shared connections)

## Source Files

- `src/pair_harness/adapters/dialogue/incremental_json.py`
- `tests/unit/test_incremental_json.py`

## Audit Trail

- EXTRACTED: 12 (80%)
- INFERRED: 3 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*