# JSON-RPC 行连接夹具

> 5 nodes · cohesion 0.40

## Key Concepts

- **.receive()** (3 connections) — `tests/fixtures/jsonl_connection.py`
- **.send()** (3 connections) — `tests/fixtures/jsonl_connection.py`
- **Any** (2 connections)
- **取出客户端写出的下一条 JSON-RPC 消息。** (1 connections) — `tests/fixtures/jsonl_connection.py`
- **按 JSON-RPC 2.0 行格式写出一条子进程消息。** (1 connections) — `tests/fixtures/jsonl_connection.py`

## Relationships

- [JSONL 传输测试夹具](JSONL_传输测试夹具.md) (2 shared connections)

## Source Files

- `tests/fixtures/jsonl_connection.py`

## Audit Trail

- EXTRACTED: 6 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*