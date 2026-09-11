# build_demo_service()

> God node · 117 connections · `src/pair_harness/desktop_backend/application_service.py`

**Community:** [Demo 服务与队列测试](Demo_服务与队列测试.md)

## Connections by Relation

### calls
- _build_service() `EXTRACTED`
- test_voice_commands_only_exchange_state_with_attached_runtime() `EXTRACTED`
- test_mobile_tts_begin_failure_is_reported_not_swallowed() `EXTRACTED`
- test_voice_tts_play_rejects_assistant_message() `EXTRACTED`
- test_voice_tts_play_skip_and_preview_commands() `EXTRACTED`
- service() `EXTRACTED`
- test_mobile_tts_preemption_is_not_reported_as_failure() `EXTRACTED`
- test_queue_item_failure_presents_failed_turn_and_advances() `EXTRACTED`
- test_role_turn_same_conversation_is_queued_while_streaming() `EXTRACTED`
- test_voice_runtime_receives_created_messages_via_listener_wiring() `EXTRACTED`
- test_provider_switch_is_no_longer_rejected_by_responses() `EXTRACTED`
- test_failed_turn_metric_carries_real_failure_reason() `EXTRACTED`
- test_api_key_never_appears_in_logs() `EXTRACTED`
- test_config_set_failure_keeps_database_old_values() `EXTRACTED`
- test_failed_turn_marks_turn_failed_and_message_failed() `EXTRACTED`
- test_sidecar_restart_restores_pair_and_finishes_orphaned_delegation() `EXTRACTED`
- test_voice_preview_allows_character_but_rejects_assistant_speakers() `EXTRACTED`
- test_voice_provision_completed_event_carries_voice_id() `EXTRACTED`
- test_auto_summary_failure_preserves_real_error() `EXTRACTED`
- _start_probe_service() `EXTRACTED`
- *…and 91 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- application_service.py `EXTRACTED`

### imports
- desktop_backend/__init__.py `EXTRACTED`

### rationale_for
- 创建不需要外部凭据、不执行真实文件操作的 Sidecar 服务。 `EXTRACTED`

### references
- [DesktopApplicationService](DesktopApplicationService.md) `EXTRACTED`
- Path `EXTRACTED`
- EventSink `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*