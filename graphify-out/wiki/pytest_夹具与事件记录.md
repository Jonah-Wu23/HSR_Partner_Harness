# pytest 夹具与事件记录

> 39 nodes · cohesion 0.10

## Key Concepts

- **service_helpers.py** (35 connections) — `tests/service_helpers.py`
- **test_tunnel.py** (25 connections) — `tests/unit/test_tunnel.py`
- **EventLog** (22 connections) — `tests/service_helpers.py`
- **test_summary_memory_commands.py** (17 connections) — `tests/unit/test_summary_memory_commands.py`
- **_manager()** (11 connections) — `tests/unit/test_tunnel.py`
- **test_character_turn_memory_drafts_persist_in_conversation_scope()** (10 connections) — `tests/unit/test_summary_memory_commands.py`
- **Path** (9 connections)
- **_wait_state()** (9 connections) — `tests/unit/test_tunnel.py`
- **test_downloaded_binary_failing_hash_check_is_deleted()** (8 connections) — `tests/unit/test_tunnel.py`
- **command()** (7 connections) — `tests/service_helpers.py`
- **test_output_keeps_draining_after_ready()** (7 connections) — `tests/unit/test_tunnel.py`
- **test_process_exit_before_hostname_fails()** (7 connections) — `tests/unit/test_tunnel.py`
- **conftest.py** (6 connections) — `tests/conftest.py`
- **test_download_failure_fails_tunnel()** (6 connections) — `tests/unit/test_tunnel.py`
- **_offline_network()** (5 connections) — `tests/conftest.py`
- **service()** (5 connections) — `tests/conftest.py`
- **Any** (5 connections)
- **test_external_kill_after_ready_fails()** (5 connections) — `tests/unit/test_tunnel.py`
- **test_start_reads_hostname_from_metrics_and_stop_terminates()** (5 connections) — `tests/unit/test_tunnel.py`
- **test_verify_file_hash()** (3 connections) — `tests/unit/test_tunnel.py`
- **_is_local()** (2 connections) — `tests/conftest.py`
- **getaddrinfo()** (2 connections) — `tests/conftest.py`
- **fixture** (2 connections)
- **.__call__()** (2 connections) — `tests/service_helpers.py`
- **.payloads()** (2 connections) — `tests/service_helpers.py`
- *... and 14 more nodes in this community*

## Relationships

- [角色卡绑定与命令测试](角色卡绑定与命令测试.md) (17 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (11 shared connections)
- [隧道进程与事件出口](隧道进程与事件出口.md) (10 shared connections)
- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (5 shared connections)
- [供应商配置热切换](供应商配置热切换.md) (5 shared connections)
- [审批终态裁决测试](审批终态裁决测试.md) (4 shared connections)
- [测试替身与集成夹具](测试替身与集成夹具.md) (4 shared connections)
- [演示模型与对话契约](演示模型与对话契约.md) (3 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (2 shared connections)
- [账号语音服务测试](账号语音服务测试.md) (2 shared connections)
- [语音设备抢占互斥](语音设备抢占互斥.md) (2 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (2 shared connections)

## Source Files

- `tests/conftest.py`
- `tests/service_helpers.py`
- `tests/unit/test_summary_memory_commands.py`
- `tests/unit/test_tunnel.py`

## Audit Trail

- EXTRACTED: 146 (91%)
- INFERRED: 15 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*