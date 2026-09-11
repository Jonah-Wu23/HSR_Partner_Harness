# storage: records.py

> 16 nodes · cohesion 0.21

## Key Concepts

- **records.py** (26 connections) — `src/pair_harness/storage/records.py`
- **MemoryStatus** (6 connections) — `src/pair_harness/storage/records.py`
- **MetricStatus** (6 connections) — `src/pair_harness/storage/records.py`
- **ProjectionKind** (6 connections) — `src/pair_harness/storage/records.py`
- **Enum** (6 connections)
- **SummaryStatus** (6 connections) — `src/pair_harness/storage/records.py`
- **str** (5 connections)
- **TurnKind** (3 connections) — `src/pair_harness/storage/records.py`
- **datetime** (2 connections)
- **_utc_now()** (2 connections) — `src/pair_harness/storage/records.py`
- **_new_id()** (1 connections) — `src/pair_harness/storage/records.py`
- **V0.3.9 存储层记录类型（contract-v1 第 1/2/4/5 节）。 本模块只定义持久化记录的结构与结构性校验，不含任何语义判断： -…** (1 connections) — `src/pair_harness/storage/records.py`
- **摘要状态（契约第 2 节：idle|running|completed|failed）。** (1 connections) — `src/pair_harness/storage/records.py`
- **长期记忆状态（契约第 2 节：active|deleted）。** (1 connections) — `src/pair_harness/storage/records.py`
- **投影条目类型（契约第 2 节：只引用 message_id/summary_id/tool_call_id）。** (1 connections) — `src/pair_harness/storage/records.py`
- **指标行状态；终态不可回退（与 TaskStatus/TurnStatus 对齐）。** (1 connections) — `src/pair_harness/storage/records.py`

## Relationships

- [委派与契约模型](委派与契约模型.md) (5 shared connections)
- [回合指标存储](回合指标存储.md) (4 shared connections)
- [存储增量缓冲与刷盘](存储增量缓冲与刷盘.md) (4 shared connections)
- [摘要与投影存储校验](摘要与投影存储校验.md) (3 shared connections)
- [配对级长期记忆存储](配对级长期记忆存储.md) (2 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [服务模式集成测试](服务模式集成测试.md) (1 shared connections)
- [test_v039_prompt_assembly_seams.py: test_v039_prompt_a…](test_v039_prompt_assembly_seams.py-_test_v039_prompt_a….md) (1 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (1 shared connections)
- [V0.3.9 存储测试](V0.3.9_存储测试.md) (1 shared connections)
- [test_v039_turn_metric_seams.py: test_v039_turn_met…](test_v039_turn_metric_seams.py-_test_v039_turn_met….md) (1 shared connections)

## Source Files

- `src/pair_harness/storage/records.py`

## Audit Trail

- EXTRACTED: 45 (92%)
- INFERRED: 4 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*