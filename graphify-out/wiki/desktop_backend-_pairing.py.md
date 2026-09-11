# desktop_backend: pairing.py

> 12 nodes · cohesion 0.17

## Key Concepts

- **pairing.py** (11 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **PairingError** (9 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **DeviceInfo** (4 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.list_devices()** (3 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.__init__()** (2 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **.__init__()** (2 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **RuntimeError** (1 connections)
- **配对码与 token 鉴权纯逻辑模块。 实现 RemoteAuthenticator Protocol，处理配对码生成/验证、token 签发/鉴权/撤销，…** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **配对码操作错误。 code 取值： - "expired"：配对码已过期 - "used"：配对码已被使用 - "invalid"：配对码不存在或格式错误** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **返回所有已签发 token 的设备元数据。 不含 token 明文。** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **已签发 token 的设备元数据（不含 token 明文）。** (1 connections) — `src/pair_harness/desktop_backend/pairing.py`
- **TypedDict** (1 connections)

## Relationships

- [PWA 静态资源路由](PWA_静态资源路由.md) (3 shared connections)
- [配对与鉴权服务](配对与鉴权服务.md) (3 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (2 shared connections)
- [test_pairing.py: test_pairing.py](test_pairing.py-_test_pairing.py.md) (2 shared connections)
- [desktop_backend: ._audit_log()](desktop_backend-_._audit_log.md) (2 shared connections)
- [desktop_backend: _CodeEntry](desktop_backend-__CodeEntry.md) (1 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (1 shared connections)
- [test_pairing.py: _FakeClock](test_pairing.py-__FakeClock.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/pairing.py`

## Audit Trail

- EXTRACTED: 23 (88%)
- INFERRED: 3 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*