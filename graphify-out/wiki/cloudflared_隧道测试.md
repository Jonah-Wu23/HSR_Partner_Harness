# cloudflared 隧道测试

> 11 nodes · cohesion 0.24

## Key Concepts

- **_FakeCloudflared** (11 connections) — `tests/unit/test_tunnel.py`
- **.exit()** (3 connections) — `tests/unit/test_tunnel.py`
- **.serve_metrics()** (3 connections) — `tests/unit/test_tunnel.py`
- **.arg()** (2 connections) — `tests/unit/test_tunnel.py`
- **.__init__()** (2 connections) — `tests/unit/test_tunnel.py`
- **.kill()** (2 connections) — `tests/unit/test_tunnel.py`
- **.terminate()** (2 connections) — `tests/unit/test_tunnel.py`
- **.close()** (1 connections) — `tests/unit/test_tunnel.py`
- **quicktunnel()** (1 connections) — `tests/unit/test_tunnel.py`
- **.wait()** (1 connections) — `tests/unit/test_tunnel.py`
- **按 cloudflared 协议回放的子进程：在 --metrics 地址提供 /quicktunnel，输出按行回放。 hostname 为 None…** (1 connections) — `tests/unit/test_tunnel.py`

## Relationships

- [隧道进程与事件出口](隧道进程与事件出口.md) (1 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (1 shared connections)
- [cloudflared 隧道输出测试](cloudflared_隧道输出测试.md) (1 shared connections)

## Source Files

- `tests/unit/test_tunnel.py`

## Audit Trail

- EXTRACTED: 15 (94%)
- INFERRED: 1 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*