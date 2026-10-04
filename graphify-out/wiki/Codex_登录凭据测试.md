# Codex 登录凭据测试

> 7 nodes · cohesion 0.62

## Key Concepts

- **test_codex_auth.py** (6 connections) — `tests/unit/test_codex_auth.py`
- **make_service()** (6 connections) — `tests/unit/test_codex_auth.py`
- **Path** (4 connections)
- **test_logout_clears_credentials()** (4 connections) — `tests/unit/test_codex_auth.py`
- **test_corrupt_auth_reports_auth_corrupt_and_preserves_file()** (3 connections) — `tests/unit/test_codex_auth.py`
- **test_initial_state_is_logged_out()** (3 connections) — `tests/unit/test_codex_auth.py`
- **write_legacy_auth()** (3 connections) — `tests/unit/test_codex_auth.py`

## Relationships

- [遗留登录与引擎装配](遗留登录与引擎装配.md) (3 shared connections)

## Source Files

- `tests/unit/test_codex_auth.py`

## Audit Trail

- EXTRACTED: 15 (94%)
- INFERRED: 1 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*