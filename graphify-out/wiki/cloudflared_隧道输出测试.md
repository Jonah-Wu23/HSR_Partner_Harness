# cloudflared 隧道输出测试

> 6 nodes · cohesion 0.33

## Key Concepts

- **_OutputStream** (8 connections) — `tests/unit/test_tunnel.py`
- **.close()** (1 connections) — `tests/unit/test_tunnel.py`
- **.feed()** (1 connections) — `tests/unit/test_tunnel.py`
- **.__init__()** (1 connections) — `tests/unit/test_tunnel.py`
- **.readline()** (1 connections) — `tests/unit/test_tunnel.py`
- **按行回放 cloudflared 输出；进程退出后返回 EOF。** (1 connections) — `tests/unit/test_tunnel.py`

## Relationships

- [cloudflared 隧道测试](cloudflared_隧道测试.md) (1 shared connections)
- [音频播放器实现](音频播放器实现.md) (1 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (1 shared connections)

## Source Files

- `tests/unit/test_tunnel.py`

## Audit Trail

- EXTRACTED: 8 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*