# desktop_backend: ._account_exists()

> 16 nodes · cohesion 0.17

## Key Concepts

- **._account_payload()** (10 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_list_payload()** (9 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_switch()** (9 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_register()** (8 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_login()** (6 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_logout()** (6 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._emit_account_changed()** (6 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_onboarding_complete()** (5 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_update_profile()** (4 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_exists()** (3 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **._account_list()** (3 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **AccountRecord 快照（不含密码派生结果与密钥）。** (1 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **注册并登录：新账号成为当前账号（账号级数据从此隔离）。** (1 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **退出当前账号：回到默认账号（登录页状态），数据不删除。** (1 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **免密切换（本地信任的多账号切换；登录仍走 _account_login）。** (1 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **V0.2 M4：首次引导完成标记——引导只在注册后由前端显式触发， 登录/注册命令本身不自动置位。** (1 connections) — `src/pair_harness/desktop_backend/application_service.py`

## Relationships

- [后端引导与快照解析](后端引导与快照解析.md) (12 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (11 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (6 shared connections)
- [语音运行时接线](语音运行时接线.md) (5 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/application_service.py`

## Audit Trail

- EXTRACTED: 54 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*