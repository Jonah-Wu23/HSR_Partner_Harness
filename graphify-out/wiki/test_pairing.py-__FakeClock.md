# test_pairing.py: _FakeClock

> 16 nodes · cohesion 0.15

## Key Concepts

- **TestClaim** (11 connections) — `tests/unit/test_pairing.py`
- **_FakeClock** (10 connections) — `tests/unit/test_pairing.py`
- **.test_expired_code_evicted_on_issue()** (4 connections) — `tests/unit/test_pairing.py`
- **.test_ttl_boundary_not_expired()** (4 connections) — `tests/unit/test_pairing.py`
- **.test_expired_code_raises_expired()** (3 connections) — `tests/unit/test_pairing.py`
- **.test_ttl_seconds_constructor_parameter()** (3 connections) — `tests/unit/test_pairing.py`
- **.test_claim_records_connect_audit()** (2 connections) — `tests/unit/test_pairing.py`
- **.test_nonexistent_code_raises_invalid()** (2 connections) — `tests/unit/test_pairing.py`
- **.test_same_code_twice_raises_used()** (2 connections) — `tests/unit/test_pairing.py`
- **.test_valid_code_returns_token()** (2 connections) — `tests/unit/test_pairing.py`
- **.advance()** (1 connections) — `tests/unit/test_pairing.py`
- **.__call__()** (1 connections) — `tests/unit/test_pairing.py`
- **.__init__()** (1 connections) — `tests/unit/test_pairing.py`
- **刚好在 TTL 边界内（≤ TTL）应成功。** (1 connections) — `tests/unit/test_pairing.py`
- **可手动推进的假时钟，用于测试 TTL 过期。** (1 connections) — `tests/unit/test_pairing.py`
- **过期码在 issue_code 时被清理，claim 应报 invalid。** (1 connections) — `tests/unit/test_pairing.py`

## Relationships

- [配对与鉴权服务](配对与鉴权服务.md) (10 shared connections)
- [test_pairing.py: test_pairing.py](test_pairing.py-_test_pairing.py.md) (2 shared connections)
- [desktop_backend: pairing.py](desktop_backend-_pairing.py.md) (1 shared connections)

## Source Files

- `tests/unit/test_pairing.py`

## Audit Trail

- EXTRACTED: 29 (94%)
- INFERRED: 2 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*