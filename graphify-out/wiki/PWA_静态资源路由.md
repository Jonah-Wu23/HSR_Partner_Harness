# PWA 静态资源路由

> 9 nodes · cohesion 0.25

## Key Concepts

- **add_static_routes()** (8 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **_not_found()** (4 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **pwa_static.py** (3 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **index()** (1 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **Application** (1 connections)
- **Path** (1 connections)
- **Request** (1 connections)
- **Response** (1 connections)
- **装配 PWA 静态路由。 - static_root 为 None 时，GET / 及任意静态路径统一返回 404，如实报错、不合成页面； -…** (1 connections) — `src/pair_harness/desktop_backend/pwa_static.py`

## Relationships

- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (2 shared connections)
- [远程接入 WS 服务端](远程接入_WS_服务端.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/pwa_static.py`

## Audit Trail

- EXTRACTED: 10 (83%)
- INFERRED: 2 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*