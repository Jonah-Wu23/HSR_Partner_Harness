# Demo 服务与队列测试

> 90 nodes · cohesion 0.05

## Key Concepts

- **build_demo_service()** (117 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **test_application_service.py** (58 connections) — `tests/unit/test_application_service.py`
- **asyncio** (49 connections)
- **Path** (48 connections)
- **test_queue_item_failure_presents_failed_turn_and_advances()** (11 connections) — `tests/unit/test_application_service.py`
- **test_api_key_never_appears_in_logs()** (10 connections) — `tests/unit/test_application_service.py`
- **test_config_set_failure_keeps_database_old_values()** (10 connections) — `tests/unit/test_application_service.py`
- **test_failed_turn_marks_turn_failed_and_message_failed()** (10 connections) — `tests/unit/test_application_service.py`
- **test_sidecar_restart_restores_pair_and_finishes_orphaned_delegation()** (10 connections) — `tests/unit/test_application_service.py`
- **test_voice_provision_completed_event_carries_voice_id()** (10 connections) — `tests/unit/test_application_service.py`
- **test_account_switch_failure_keeps_original_account()** (9 connections) — `tests/unit/test_application_service.py`
- **test_rebuild_runtime_for_account_switches_engine_immediately()** (8 connections) — `tests/unit/test_application_service.py`
- **test_streaming_assistant_events_reconcile_to_persisted_segments()** (8 connections) — `tests/unit/test_application_service.py`
- **test_app_reconnect_command_reports_clear_error_not_silent()** (7 connections) — `tests/unit/test_application_service.py`
- **test_bootstrap_approvals_json_serializable_with_pending()** (7 connections) — `tests/unit/test_application_service.py`
- **test_chat_submit_emits_messages_and_direct_task_tool_updates()** (7 connections) — `tests/unit/test_application_service.py`
- **test_codex_login_commands_are_removed()** (7 connections) — `tests/unit/test_application_service.py`
- **test_config_set_accepts_voice_credentials_but_locks_models()** (7 connections) — `tests/unit/test_application_service.py`
- **test_conversation_and_engine_data_isolated_per_account()** (7 connections) — `tests/unit/test_application_service.py`
- **test_explicit_cleared_api_key_blocks_environment_fallback()** (7 connections) — `tests/unit/test_application_service.py`
- **test_first_complete_reply_generates_title_from_dialogue_only_and_manual_name_wins()** (7 connections) — `tests/unit/test_application_service.py`
- **test_oauth_provider_selection_is_rejected_without_writing_config()** (7 connections) — `tests/unit/test_application_service.py`
- **test_project_commands_reject_foreign_account_ids()** (7 connections) — `tests/unit/test_application_service.py`
- **test_ptt_stop_failure_clears_listening_state_and_surfaces_error()** (7 connections) — `tests/unit/test_application_service.py`
- **test_voice_provision_rejects_assistant_speaker()** (7 connections) — `tests/unit/test_application_service.py`
- *... and 65 more nodes in this community*

## Relationships

- [语音试听声源校验测试](语音试听声源校验测试.md) (44 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (20 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (13 shared connections)
- [test_application_service.py: 角色流不走 coding busy，…](test_application_service.py-_角色流不走_coding_busy，….md) (12 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (12 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (8 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (6 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (5 shared connections)
- [test_application_service.py: __init__()](test_application_service.py-___init__.md) (5 shared connections)
- [test_application_service.py: F7：attach_voice_ru…](test_application_service.py-_F7：attach_voice_ru….md) (5 shared connections)
- [V0.3.9 B03 仅聊天补全测试](V0.3.9_B03_仅聊天补全测试.md) (5 shared connections)
- [test_v039_summary_memory_commands.py: test_v039_summary_…](test_v039_summary_memory_commands.py-_test_v039_summary_….md) (5 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/application_service.py`
- `tests/unit/test_application_service.py`
- `tests/unit/test_v039_prompt_assembly_seams.py`

## Audit Trail

- EXTRACTED: 364 (91%)
- INFERRED: 35 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*