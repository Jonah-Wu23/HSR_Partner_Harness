# adapters: incremental_json.p…

> 19 nodes · cohesion 0.13

## Key Concepts

- **IncrementalJsonSpeechParser** (17 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **incremental_json.py** (4 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **._extract()** (4 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **.feed()** (4 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **._scan_value()** (3 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **._try_complete()** (3 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **test_parser_extracts_clean_speech_across_chunk_boundaries()** (3 connections) — `tests/unit/test_incremental_json.py`
- **test_parser_plain_text_output_emits_raw_as_speech()** (3 connections) — `tests/unit/test_incremental_json.py`
- **.full_object()** (2 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **._skip_ws()** (2 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **Any** (2 connections)
- **.__init__()** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **.speech()** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **增量 JSON 解析：从 DeepSeek 流式输出中提取干净的 speech 字段（V0.2 M2）。 角色适配器的流式输出是 JSON…** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **扫描 speech 字符串值；只返回已确认属于值的字符。** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **流式 JSON 输出中的增量 speech 提取器。** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **喂入一段 content 分片，返回新增的干净 speech 文本。** (1 connections) — `src/pair_harness/adapters/dialogue/incremental_json.py`
- **parametrize** (1 connections)
- **非 JSON 输出（角色卡降级/纯台词）：整段增量作为台词。** (1 connections) — `tests/unit/test_incremental_json.py`

## Relationships

- [增量 JSON 解析测试](增量_JSON_解析测试.md) (4 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (2 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (2 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/dialogue/incremental_json.py`
- `tests/unit/test_incremental_json.py`

## Audit Trail

- EXTRACTED: 28 (88%)
- INFERRED: 4 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*