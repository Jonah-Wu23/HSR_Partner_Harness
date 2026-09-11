# CharacterTurn

> God node · 93 connections · `src/pair_harness/core/contracts.py`

**Community:** [规划式评审测试夹具](规划式评审测试夹具.md)

## Connections by Relation

### calls
- .parse_output() `EXTRACTED`
- test_three_assembly_points_consistency() `EXTRACTED`
- test_review_lifecycle_events_only_when_reviewer_invoked() `EXTRACTED`
- test_m41_denied_tool_run_is_persisted() `EXTRACTED`
- test_chat_mode_blocks_delegation() `EXTRACTED`
- test_collaboration_executes_delegation_with_delegation_id() `EXTRACTED`
- test_fast_accept_returns_real_message_id_before_turn() `EXTRACTED`
- test_direct_input_while_busy_becomes_user_amendment() `EXTRACTED`
- test_chat_rounds_and_amendment_during_execution() `EXTRACTED`
- test_concurrent_chat_rounds_serialized_in_arrival_order() `EXTRACTED`
- test_running_task_keeps_origin_project_and_pair_after_context_switch() `EXTRACTED`
- test_delegation_missed_auto_retry_succeeds() `EXTRACTED`
- test_failed_delegation_with_redelegate_retries_once_and_succeeds() `EXTRACTED`
- test_retry_cap_after_second_failure_stops_with_notice() `EXTRACTED`
- test_process_character_turn_sets_turn_index() `EXTRACTED`
- test_m42_delegation_correction_replaces_original_role_message() `EXTRACTED`
- test_delegation_without_assistant_final_fails_instead_of_completed() `EXTRACTED`
- test_user_message_target_and_origin() `EXTRACTED`
- test_character_amendment_while_busy_marks_character_origin() `EXTRACTED`
- test_character_delegation_while_busy_shows_visible_notice() `EXTRACTED`
- *…and 12 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- contracts.py `EXTRACTED`

### imports
- orchestrator.py `EXTRACTED`
- openai_compatible.py `EXTRACTED`
- adapters/demo.py `EXTRACTED`

### inherits
- FrozenModel `EXTRACTED`

### references
- ._retry_character_delegation() `EXTRACTED`
- ._needs_delegation_retry() `EXTRACTED`
- .__init__() `EXTRACTED`

### uses
- [ConversationOrchestrator](ConversationOrchestrator.md) `INFERRED`
- OpenAICompatibleDialogueModel `INFERRED`
- FixedDialogueModel `INFERRED`
- ScriptedDialogueModel `INFERRED`
- _make_orchestrator() `INFERRED`
- run_turn() `INFERRED`
- test_native_approval_flow_sequence_contiguous() `INFERRED`
- test_request_approval_forwards_decision_via_resolve_approval() `INFERRED`
- test_review_mode_high_risk_reviewer_denies_and_replies_decline() `INFERRED`
- test_restored_orchestrator_backfills_history_and_session_ref() `INFERRED`
- test_orchestrator_delegation_card_failed_for_error_stop_reason_after_successful_tools() `INFERRED`
- _make_orchestrator() `INFERRED`
- _final_turn() `INFERRED`
- test_full_auto_replies_accept_without_callback() `INFERRED`
- test_sandbox_deny_sequence_contiguous() `INFERRED`
- DeltaAndFinalModel `INFERRED`
- test_gate_path_user_deny_sequence_contiguous() `INFERRED`
- test_sandbox_denial_break_does_not_leak_session_subscription() `INFERRED`
- test_engine_policy_on_request_mode_maps_to_untrusted() `INFERRED`
- test_native_engine_never_synthesizes_approval_after_tool_started() `INFERRED`
- *…and 33 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*