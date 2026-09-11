# fake_codex_app_server.py: .notify()

> 6 nodes · cohesion 0.33

## Key Concepts

- **Any** (4 connections)
- **.serve_request()** (3 connections) — `tests/fixtures/fake_codex_app_server.py`
- **.notify()** (2 connections) — `tests/fixtures/fake_codex_app_server.py`
- **.receive_request()** (2 connections) — `tests/fixtures/fake_codex_app_server.py`
- **.send()** (2 connections) — `tests/fixtures/fake_codex_app_server.py`
- **应答下一个非 initialize 请求；initialize 握手透明应答不返回。 B1：引擎 open_session 现在先发 initialize…** (1 connections) — `tests/fixtures/fake_codex_app_server.py`

## Relationships

- [Codex 审批流集成测试](Codex_审批流集成测试.md) (2 shared connections)
- [Codex 传输集成测试](Codex_传输集成测试.md) (2 shared connections)

## Source Files

- `tests/fixtures/fake_codex_app_server.py`

## Audit Trail

- EXTRACTED: 9 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*