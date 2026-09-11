# desktop_backend: _CodeEntry

> 7 nodes · cohesion 0.29

## Key Concepts

- **_CodeEntry** (4 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.issue_code()** (4 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.load_state()** (4 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **._evict_expired_codes()** (2 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.__init__()** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **生成一个 6 位数字配对码（000000–999999 均匀分布）。 一次性，TTL 默认 300 秒。** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **从状态快照恢复。 替换当前全部状态。恢复后 ``authorize`` 行为与导出前一致。** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`

## Relationships

- [配对与鉴权服务](配对与鉴权服务.md) (3 shared connections)
- [desktop_backend: pairing.py](desktop_backend-_pairing.py.md) (1 shared connections)
- [desktop_backend: ._audit_log()](desktop_backend-_._audit_log.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/pairing.py`

## Audit Trail

- EXTRACTED: 11 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*