# Codex 登录状态测试

> 32 nodes · cohesion 0.12

## Key Concepts

- **test_codex_auth.py** (16 connections) — `tests/unit/test_codex_auth.py`
- **make_service()** (15 connections) — `tests/unit/test_codex_auth.py`
- **Path** (13 connections)
- **_RecordingPopen** (8 connections) — `tests/unit/test_codex_auth.py`
- **test_start_login_quotes_cmd_shim_path_with_spaces()** (7 connections) — `tests/unit/test_codex_auth.py`
- **test_repeated_start_login_terminates_and_waits_old_process()** (6 connections) — `tests/unit/test_codex_auth.py`
- **test_start_login_surfaces_process_start_failure()** (5 connections) — `tests/unit/test_codex_auth.py`
- **test_waiting_is_not_cleared_until_token_complete_and_process_terminal()** (5 connections) — `tests/unit/test_codex_auth.py`
- **test_api_login_writes_atomically_without_temp_leftovers()** (4 connections) — `tests/unit/test_codex_auth.py`
- **test_corrupt_auth_reports_auth_corrupt_and_preserves_file()** (4 connections) — `tests/unit/test_codex_auth.py`
- **MonkeyPatch** (3 connections)
- **test_accounts_do_not_share_codex_home()** (3 connections) — `tests/unit/test_codex_auth.py`
- **test_api_login_writes_auth_json_and_status()** (3 connections) — `tests/unit/test_codex_auth.py`
- **test_cancel_login_returns_to_logged_out()** (3 connections) — `tests/unit/test_codex_auth.py`
- **test_initial_state_is_logged_out()** (3 connections) — `tests/unit/test_codex_auth.py`
- **test_logout_clears_credentials()** (3 connections) — `tests/unit/test_codex_auth.py`
- **record_popen()** (3 connections) — `tests/unit/test_codex_auth.py`
- **test_start_login_waiting_then_api_login_clears_waiting()** (3 connections) — `tests/unit/test_codex_auth.py`
- **record_popen()** (2 connections) — `tests/unit/test_codex_auth.py`
- **V0.2 M3：Codex 登录状态服务（方案 §M3-4，账号隔离）。** (1 connections) — `tests/unit/test_codex_auth.py`
- **M3.4：重复 start_login 必须先终止并等待旧登录进程，再创建新进程。** (1 connections) — `tests/unit/test_codex_auth.py`
- **M3.4：.cmd/.bat 登录命令对含空格路径使用 Windows 正确引用。** (1 connections) — `tests/unit/test_codex_auth.py`
- **M3.4：waiting 只在完整 token 可读且登录进程终态明确后清除。** (1 connections) — `tests/unit/test_codex_auth.py`
- **M3.4：auth.json 经同目录临时文件原子替换，不残留半写临时文件。** (1 connections) — `tests/unit/test_codex_auth.py`
- **M3.4：auth.json 解析失败必须报告 auth_corrupt，不能静默变 logged_out。** (1 connections) — `tests/unit/test_codex_auth.py`
- *... and 7 more nodes in this community*

## Relationships

- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [Codex 鉴权服务](Codex_鉴权服务.md) (1 shared connections)

## Source Files

- `tests/unit/test_codex_auth.py`

## Audit Trail

- EXTRACTED: 59 (95%)
- INFERRED: 3 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*