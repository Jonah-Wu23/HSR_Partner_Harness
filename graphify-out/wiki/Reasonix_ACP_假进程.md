# Reasonix ACP 假进程

> 16 nodes · cohesion 0.17

## Key Concepts

- **FakeReasonixAcp** (24 connections) — `tests/unit/test_acp_engine.py`
- **engine()** (5 connections) — `tests/unit/test_acp_engine.py`
- **.connect()** (5 connections) — `tests/unit/test_acp_engine.py`
- **._serve()** (5 connections) — `tests/unit/test_acp_engine.py`
- **._answer()** (4 connections) — `tests/unit/test_acp_engine.py`
- **._run_prompt()** (3 connections) — `tests/unit/test_acp_engine.py`
- **._spawn()** (3 connections) — `tests/unit/test_acp_engine.py`
- **reasonix()** (3 connections) — `tests/unit/test_acp_engine.py`
- **fixture** (2 connections)
- **.aclose()** (1 connections) — `tests/unit/test_acp_engine.py`
- **.exit()** (1 connections) — `tests/unit/test_acp_engine.py`
- **.__init__()** (1 connections) — `tests/unit/test_acp_engine.py`
- **.replies()** (1 connections) — `tests/unit/test_acp_engine.py`
- **.requests()** (1 connections) — `tests/unit/test_acp_engine.py`
- **内存中的 reasonix acp 进程，经 JsonlProcessTransport 按 ACP v1 JSON-RPC 行协议应答。…** (1 connections) — `tests/unit/test_acp_engine.py`
- **transport 的 connection_factory，每次调用相当于启动一个新进程。** (1 connections) — `tests/unit/test_acp_engine.py`

## Relationships

- [ACP 回合生命周期测试](ACP_回合生命周期测试.md) (10 shared connections)
- [JSONL 传输测试夹具](JSONL_传输测试夹具.md) (5 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (2 shared connections)
- [JSONL JSON-RPC 传输](JSONL_JSON-RPC_传输.md) (1 shared connections)
- [测试替身与集成夹具](测试替身与集成夹具.md) (1 shared connections)

## Source Files

- `tests/unit/test_acp_engine.py`

## Audit Trail

- EXTRACTED: 38 (95%)
- INFERRED: 2 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*