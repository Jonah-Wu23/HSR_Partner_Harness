# ApprovalMode

> God node · 93 connections · `src/pair_harness/core/contracts.py`

**Community:** [规划式评审测试夹具](规划式评审测试夹具.md)

## Connections by Relation

### calls
- _build_service() `EXTRACTED`
- ._select_conversation_context() `EXTRACTED`
- ._resolve_execution_context() `EXTRACTED`
- main() `EXTRACTED`
- ._project_update_settings() `EXTRACTED`

### contains
- contracts.py `EXTRACTED`

### imports
- application_service.py `EXTRACTED`
- orchestrator.py `EXTRACTED`
- cli.py `EXTRACTED`
- approval.py `EXTRACTED`
- context.py `EXTRACTED`

### inherits
- Enum `EXTRACTED`
- str `EXTRACTED`

### references
- .__init__() `EXTRACTED`
- .select_context() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._engine_policy() `EXTRACTED`
- .set_approval_mode() `EXTRACTED`

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- [ConversationOrchestrator](ConversationOrchestrator.md) `INFERRED`
- ApprovalManager `INFERRED`
- run_real() `INFERRED`
- ExecutionContext `INFERRED`
- _make_orchestrator() `INFERRED`
- test_native_approval_flow_sequence_contiguous() `INFERRED`
- test_request_approval_forwards_decision_via_resolve_approval() `INFERRED`
- test_review_mode_high_risk_reviewer_denies_and_replies_decline() `INFERRED`
- test_restored_orchestrator_backfills_history_and_session_ref() `INFERRED`
- test_orchestrator_delegation_card_failed_for_error_stop_reason_after_successful_tools() `INFERRED`
- _make_orchestrator() `INFERRED`
- test_full_auto_replies_accept_without_callback() `INFERRED`
- test_sandbox_deny_sequence_contiguous() `INFERRED`
- test_gate_path_user_deny_sequence_contiguous() `INFERRED`
- test_sandbox_denial_break_does_not_leak_session_subscription() `INFERRED`
- test_engine_policy_on_request_mode_maps_to_untrusted() `INFERRED`
- test_native_engine_never_synthesizes_approval_after_tool_started() `INFERRED`
- test_review_adjudicate_insufficient_info_reviewer_may_allow() `INFERRED`
- test_review_adjudicate_insufficient_info_routes_to_reviewer() `INFERRED`
- *…and 55 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*