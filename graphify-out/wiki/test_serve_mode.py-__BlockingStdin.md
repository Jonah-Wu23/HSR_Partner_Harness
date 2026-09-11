# test_serve_mode.py: _BlockingStdin

> 5 nodes · cohesion 0.50

## Key Concepts

- **_BlockingStdin** (6 connections) — `tests/integration/test_serve_mode.py`
- **.__init__()** (3 connections) — `tests/integration/test_serve_mode.py`
- **.readline()** (1 connections) — `tests/integration/test_serve_mode.py`
- **.release()** (1 connections) — `tests/integration/test_serve_mode.py`
- **可手动放行的 stdin：readline 阻塞到 release()。 run_stdin 在独立线程里读 stdin，阻塞读取不会卡住事件循环，…** (1 connections) — `tests/integration/test_serve_mode.py`

## Relationships

- [服务模式集成测试](服务模式集成测试.md) (2 shared connections)

## Source Files

- `tests/integration/test_serve_mode.py`

## Audit Trail

- EXTRACTED: 7 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*