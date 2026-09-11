# desktop_backend: ._audit_log()

> 11 nodes · cohesion 0.22

## Key Concepts

- **.authorize()** (5 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.claim()** (5 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **._lookup_token()** (5 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **_TokenEntry** (5 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **._audit_log()** (4 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.revoke()** (4 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **使用配对码换取 token。 Parameters ---------- code : str 配对码。 device_name : str 设备名称。…** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **鉴权单条请求。 token 有效且未撤销 → allowed=True； method 在 ``UNAUTHENTICATED_METHODS`` 白名单内…** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **恒定时间查找 token（hmac.compare_digest 比较）。** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **撤销指定 token。 撤销后 ``authorize`` 立即拒绝，并通知所有撤销监听器（如 WS 服务器 断开该 token 的已建立连接）。…** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.__init__()** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`

## Relationships

- [配对与鉴权服务](配对与鉴权服务.md) (5 shared connections)
- [desktop_backend: pairing.py](desktop_backend-_pairing.py.md) (2 shared connections)
- [PWA 静态资源路由](PWA_静态资源路由.md) (1 shared connections)
- [desktop_backend: _CodeEntry](desktop_backend-__CodeEntry.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/pairing.py`

## Audit Trail

- EXTRACTED: 21 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*