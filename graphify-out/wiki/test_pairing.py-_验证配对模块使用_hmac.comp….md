# test_pairing.py: 验证配对模块使用 hmac.comp…

> 6 nodes · cohesion 0.33

## Key Concepts

- **TestSecurity** (5 connections) — `tests/unit/test_pairing.py`
- **.test_authorize_is_real_failure()** (2 connections) — `tests/unit/test_pairing.py`
- **.test_uses_hmac_compare_digest()** (2 connections) — `tests/unit/test_pairing.py`
- **.test_uses_secrets_not_random()** (2 connections) — `tests/unit/test_pairing.py`
- **验证配对模块使用 hmac.compare_digest 而非 == 比较 token。** (1 connections) — `tests/unit/test_pairing.py`
- **验证整个模块使用 secrets 而非 random。** (1 connections) — `tests/unit/test_pairing.py`

## Relationships

- [配对与鉴权服务](配对与鉴权服务.md) (2 shared connections)
- [test_pairing.py: test_pairing.py](test_pairing.py-_test_pairing.py.md) (1 shared connections)

## Source Files

- `tests/unit/test_pairing.py`

## Audit Trail

- EXTRACTED: 7 (88%)
- INFERRED: 1 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*