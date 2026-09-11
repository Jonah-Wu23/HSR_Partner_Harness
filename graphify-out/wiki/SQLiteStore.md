# SQLiteStore

> God node · 225 connections · `src/pair_harness/storage/sqlite_store.py`

**Community:** [存储增量缓冲与刷盘](存储增量缓冲与刷盘.md)

## Connections by Relation

### calls
- _build_service() `EXTRACTED`
- run_real() `EXTRACTED`
- test_m41_denied_tool_run_is_persisted() `EXTRACTED`
- test_m42_delegation_correction_replaces_original_role_message() `EXTRACTED`
- test_migration_11_upgrades_v10_library_and_matches_fresh_schema() `EXTRACTED`
- test_immediate_save_still_durable_before_batch() `EXTRACTED`
- test_batch_same_key_keeps_last_state_and_first_position() `EXTRACTED`
- test_batch_sample_stays_within_budget() `EXTRACTED`
- test_batch_touches_conversation_updated_at_once() `EXTRACTED`
- test_burst_sample_transaction_bound() `EXTRACTED`
- test_flush_if_due_uses_50ms_window() `EXTRACTED`
- test_memory_requires_complete_scope() `EXTRACTED`
- test_memory_scope_isolation_by_project_and_assistant() `EXTRACTED`
- test_metric_null_and_zero_semantics() `EXTRACTED`
- test_metric_query_filters_and_cursor_pagination() `EXTRACTED`
- test_metric_terminal_state_cannot_regress() `EXTRACTED`
- test_migration_level_is_atomic_on_failure() `EXTRACTED`
- test_role_message_stats_since_filters_structurally() `EXTRACTED`
- test_batch_enqueue_flushes_one_transaction_and_coalesces() `EXTRACTED`
- test_flush_if_due_skips_before_deadline() `EXTRACTED`
- *…and 25 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- sqlite_store.py `EXTRACTED`

### imports
- application_service.py `EXTRACTED`
- cli.py `EXTRACTED`
- character_cards/repository.py `EXTRACTED`
- assets.py `EXTRACTED`

### inherits
- StateStore `EXTRACTED`

### method
- ._write_rows() `EXTRACTED`
- ._summary_from_row() `EXTRACTED`
- .update_memory() `EXTRACTED`
- ._memory_from_row() `EXTRACTED`
- .query_turn_metrics() `EXTRACTED`
- ._metric_from_row() `EXTRACTED`
- .get_project() `EXTRACTED`
- .get_conversation() `EXTRACTED`
- ._project_from_row() `EXTRACTED`
- ._touch_conversation() `EXTRACTED`
- .flush() `EXTRACTED`
- ._write_message_row() `EXTRACTED`
- .update_summary() `EXTRACTED`
- .close() `EXTRACTED`
- ._update_project_column() `EXTRACTED`
- .save_message() `EXTRACTED`
- .get_queue_item() `EXTRACTED`
- .create_account() `EXTRACTED`
- .get_account() `EXTRACTED`
- ._account_dict() `EXTRACTED`
- *…and 98 more `method` connection(s) not listed (lowest-degree first to go)*

### references
- .__init__() `EXTRACTED`
- .__init__() `EXTRACTED`
- .__init__() `EXTRACTED`

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- [Message](Message.md) `INFERRED`
- EngineSessionRef `INFERRED`
- _seed() `INFERRED`
- CharacterCardRepository `INFERRED`
- PairMemory `INFERRED`
- ConversationSummary `INFERRED`
- MemoryScope `INFERRED`
- TurnMetric `INFERRED`
- ToolRun `INFERRED`
- TurnMetricQuery `INFERRED`
- ProjectionEntry `INFERRED`
- CharacterAssetService `INFERRED`
- test_restored_orchestrator_backfills_history_and_session_ref() `INFERRED`
- Project `INFERRED`
- _make_orchestrator() `INFERRED`
- test_completed_demo_conversation_restores_after_reopen() `INFERRED`
- test_restore_drops_session_from_a_different_engine() `INFERRED`
- test_store_persists_core_records() `INFERRED`
- Conversation `INFERRED`
- *…and 33 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*