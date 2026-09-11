# test_accounts_store.py: test_accounts_stor…

> 16 nodes · cohesion 0.13

## Key Concepts

- **test_accounts_store.py** (12 connections) — `tests/unit/test_accounts_store.py`
- **make_store()** (4 connections) — `tests/unit/test_accounts_store.py`
- **test_migration_assigns_existing_projects_to_default_account()** (4 connections) — `tests/unit/test_accounts_store.py`
- **test_password_hash_is_derived_never_plaintext()** (4 connections) — `tests/unit/test_accounts_store.py`
- **Path** (3 connections)
- **test_default_account_exists_after_migration()** (3 connections) — `tests/unit/test_accounts_store.py`
- **test_account_config_and_secret_roundtrip()** (2 connections) — `tests/unit/test_accounts_store.py`
- **test_change_password_requires_old_password()** (2 connections) — `tests/unit/test_accounts_store.py`
- **test_projects_isolated_by_account()** (2 connections) — `tests/unit/test_accounts_store.py`
- **test_register_login_and_password_verification()** (2 connections) — `tests/unit/test_accounts_store.py`
- **test_update_profile_and_login_timestamp()** (2 connections) — `tests/unit/test_accounts_store.py`
- **V0.2 M3：本地账号与账号级配置的存储层（方案 §M3）。** (1 connections) — `tests/unit/test_accounts_store.py`
- **模拟 v4 旧库：projects 无 account_id 列 → 升级后归入默认账号。** (1 connections) — `tests/unit/test_accounts_store.py`
- **旧库升级：自动创建默认账号，未设置密码（空密码可登录）。** (1 connections) — `tests/unit/test_accounts_store.py`
- **F6：密码本地派生——存储值必须不是明文，且同密码不同账号不同散列。 ``get_account`` 刻意不暴露派生字段，这里直查库表验证存储值： 若…** (1 connections) — `tests/unit/test_accounts_store.py`
- **stored_hash()** (1 connections) — `tests/unit/test_accounts_store.py`

## Relationships

- [存储增量缓冲与刷盘](存储增量缓冲与刷盘.md) (9 shared connections)
- [V0.3.9 存储测试](V0.3.9_存储测试.md) (3 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)

## Source Files

- `tests/unit/test_accounts_store.py`

## Audit Trail

- EXTRACTED: 22 (76%)
- INFERRED: 7 (24%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*