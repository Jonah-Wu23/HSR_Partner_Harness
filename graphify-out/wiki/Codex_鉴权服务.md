# Codex 鉴权服务

> 29 nodes · cohesion 0.10

## Key Concepts

- **CodexAuthService** (38 connections) — `src/pair_harness/adapters/codex/auth.py`
- **.status()** (7 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._load_auth_data()** (5 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._terminate_login_process()** (5 connections) — `src/pair_harness/adapters/codex/auth.py`
- **.api_login()** (4 connections) — `src/pair_harness/adapters/codex/auth.py`
- **.cancel_login()** (3 connections) — `src/pair_harness/adapters/codex/auth.py`
- **.start_login()** (3 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._tokens_complete()** (3 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._write_auth_file()** (3 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._set_current_account()** (3 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **.auth_file()** (2 connections) — `src/pair_harness/adapters/codex/auth.py`
- **.env_overrides()** (2 connections) — `src/pair_harness/adapters/codex/auth.py`
- **.__init__()** (2 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._logged_in_payload()** (2 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._login_process_terminal()** (2 connections) — `src/pair_harness/adapters/codex/auth.py`
- **.logout()** (2 connections) — `src/pair_harness/adapters/codex/auth.py`
- **._read_tokens()** (2 connections) — `src/pair_harness/adapters/codex/auth.py`
- **Path** (2 connections)
- **启动 Codex 官方浏览器 OAuth；未传可执行文件时只进入等待态。 重复调用会先终止并等待旧登录进程退出，再创建新进程，避免多个 OAuth…** (1 connections) — `src/pair_harness/adapters/codex/auth.py`
- **OpenAI API Key 登录：写 auth.json（保留现有 chatgpt token）。** (1 connections) — `src/pair_harness/adapters/codex/auth.py`
- **同目录临时文件写入后原子替换，避免 auth.json 半写。** (1 connections) — `src/pair_harness/adapters/codex/auth.py`
- **终止旧登录进程并等待其退出；普通 terminate 无效时强制结束。** (1 connections) — `src/pair_harness/adapters/codex/auth.py`
- **取消 waiting 态（浏览器流程放弃后回到 logged_out）。** (1 connections) — `src/pair_harness/adapters/codex/auth.py`
- **读取 auth.json；解析失败时返回空 dict 和保留的错误说明。** (1 connections) — `src/pair_harness/adapters/codex/auth.py`
- **每个本地账号独立的 Codex 认证状态（状态机）。** (1 connections) — `src/pair_harness/adapters/codex/auth.py`
- *... and 4 more nodes in this community*

## Relationships

- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (5 shared connections)
- [desktop_backend: _atomic_write_text…](desktop_backend-__atomic_write_text….md) (5 shared connections)
- [语音运行时接线](语音运行时接线.md) (2 shared connections)
- [desktop_backend: DiagnosticCallback](desktop_backend-_DiagnosticCallback.md) (2 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (2 shared connections)
- [test_v038_t4_delegation_chain.py: _FakeCodexAuth](test_v038_t4_delegation_chain.py-__FakeCodexAuth.md) (2 shared connections)
- [后端引导与快照解析](后端引导与快照解析.md) (1 shared connections)
- [Codex 登录状态测试](Codex_登录状态测试.md) (1 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (1 shared connections)
- [子进程启动与终止](子进程启动与终止.md) (1 shared connections)
- [记忆命令处理](记忆命令处理.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/auth.py`
- `src/pair_harness/desktop_backend/application_service.py`

## Audit Trail

- EXTRACTED: 50 (81%)
- INFERRED: 12 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*