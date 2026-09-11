# adapters: ._ensure_initializ…

> 4 nodes · cohesion 0.50

## Key Concepts

- **.generation()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._ensure_initialized()** (3 connections) — `src/pair_harness/adapters/acp/engine.py`
- **.__init__()** (3 connections) — `src/pair_harness/adapters/acp/engine.py`
- **连接代次。重连后递增，旧 reader 只归属旧代次。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`

## Relationships

- [ACP 编码引擎](ACP_编码引擎.md) (3 shared connections)
- [adapters: AcpCodec](adapters-_AcpCodec.md) (1 shared connections)
- [JSONL 子进程传输](JSONL_子进程传输.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/acp/engine.py`
- `src/pair_harness/adapters/codex/transport.py`

## Audit Trail

- EXTRACTED: 6 (75%)
- INFERRED: 2 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*