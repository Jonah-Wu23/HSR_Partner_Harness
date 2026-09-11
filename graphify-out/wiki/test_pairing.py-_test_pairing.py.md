# test_pairing.py: test_pairing.py

> 9 nodes · cohesion 0.22

## Key Concepts

- **test_pairing.py** (13 connections) — `tests/unit/test_pairing.py`
- **TestIntegration** (5 connections) — `tests/unit/test_pairing.py`
- **TestIssueCode** (4 connections) — `tests/unit/test_pairing.py`
- **.test_codes_are_unique()** (3 connections) — `tests/unit/test_pairing.py`
- **.test_concurrent_sessions()** (2 connections) — `tests/unit/test_pairing.py`
- **.test_full_pair_and_authorize_flow()** (2 connections) — `tests/unit/test_pairing.py`
- **.test_returns_6_digit_string()** (2 connections) — `tests/unit/test_pairing.py`
- **配对与鉴权纯逻辑模块测试。 覆盖 workplan 4.3 全部场景：配对码一次性、过期、错误码、 token 撤销后立即拒绝、list_devices…** (1 connections) — `tests/unit/test_pairing.py`
- **连续签发多个码不应重复（概率极低，运行多次验证）。** (1 connections) — `tests/unit/test_pairing.py`

## Relationships

- [配对与鉴权服务](配对与鉴权服务.md) (8 shared connections)
- [desktop_backend: pairing.py](desktop_backend-_pairing.py.md) (2 shared connections)
- [test_pairing.py: _FakeClock](test_pairing.py-__FakeClock.md) (2 shared connections)
- [PWA 静态资源路由](PWA_静态资源路由.md) (1 shared connections)
- [test_pairing.py: list_devices 返回 De…](test_pairing.py-_list_devices_返回_De….md) (1 shared connections)
- [test_pairing.py: export_state 不含 AP…](test_pairing.py-_export_state_不含_AP….md) (1 shared connections)
- [test_pairing.py: 审计条目不含消息正文与密钥（仅含方法…](test_pairing.py-_审计条目不含消息正文与密钥（仅含方法….md) (1 shared connections)
- [test_pairing.py: 验证配对模块使用 hmac.comp…](test_pairing.py-_验证配对模块使用_hmac.comp….md) (1 shared connections)

## Source Files

- `tests/unit/test_pairing.py`

## Audit Trail

- EXTRACTED: 22 (88%)
- INFERRED: 3 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*