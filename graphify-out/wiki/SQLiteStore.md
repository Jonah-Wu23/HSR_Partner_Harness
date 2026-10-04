# SQLiteStore

> God node · 175 connections · `src/pair_harness/storage/sqlite_store.py`

**Community:** [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md)

## Connections by Relation

### calls
- run_real() `EXTRACTED`
- store() `EXTRACTED`
- _build_service() `EXTRACTED`
- test_latest_summary_follows_coverage_end_time() `EXTRACTED`
- test_store_persists_core_records() `EXTRACTED`
- test_memory_scope_isolation_by_project_and_assistant() `EXTRACTED`
- test_metric_null_and_zero_semantics() `EXTRACTED`
- test_metric_query_filters_and_cursor_pagination() `EXTRACTED`
- test_metric_upsert_keeps_one_row_per_turn() `EXTRACTED`
- test_summary_failure_keeps_real_error() `EXTRACTED`
- test_summary_upsert_is_idempotent_by_range() `EXTRACTED`
- test_message_source_kind_columns_store_enum_values() `EXTRACTED`
- test_message_with_lone_surrogates_can_be_persisted() `EXTRACTED`
- test_metric_terminal_state_cannot_regress() `EXTRACTED`
- test_summary_rejects_unknown_status_and_missing_row() `EXTRACTED`
- service() `EXTRACTED`
- repo() `EXTRACTED`
- test_legacy_db_upgrade_rebuilds_card_tables_and_preserves_data() `EXTRACTED`
- test_memory_assistant_identity_unique_key_and_mutation_scope() `EXTRACTED`
- test_memory_delete_is_soft_and_recreatable() `EXTRACTED`
- *…and 16 more `calls` connection(s) not listed (lowest-degree first to go)*

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
- ._update_existing() `EXTRACTED`
- ._summary_from_row() `EXTRACTED`
- .update_memory() `EXTRACTED`
- ._memory_from_row() `EXTRACTED`
- .query_turn_metrics() `EXTRACTED`
- ._metric_from_row() `EXTRACTED`
- ._update_project_column() `EXTRACTED`
- .get_project() `EXTRACTED`
- .get_conversation() `EXTRACTED`
- .get_queue_item() `EXTRACTED`
- ._project_from_row() `EXTRACTED`
- ._derive_password() `EXTRACTED`
- .create_account() `EXTRACTED`
- .get_account() `EXTRACTED`
- ._account_dict() `EXTRACTED`
- ._write_message_row() `EXTRACTED`
- .latest_completed_summary() `EXTRACTED`
- .delete_memory() `EXTRACTED`
- .get_memory() `EXTRACTED`
- .list_memories() `EXTRACTED`
- *…and 68 more `method` connection(s) not listed (lowest-degree first to go)*

### references
- .__init__() `EXTRACTED`
- .__init__() `EXTRACTED`
- .__init__() `EXTRACTED`

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- [Message](Message.md) `INFERRED`
- EngineSessionRef `INFERRED`
- CharacterCardRepository `INFERRED`
- ConversationSummary `INFERRED`
- ConversationSummary `INFERRED`
- PairMemory `INFERRED`
- ToolRun `INFERRED`
- MemoryScope `INFERRED`
- TurnMetricQuery `INFERRED`
- ConversationSnapshot `INFERRED`
- Conversation `INFERRED`
- TurnMetric `INFERRED`
- CharacterAssetService `INFERRED`
- test_restored_orchestrator_backfills_history_and_session_ref() `INFERRED`
- Project `INFERRED`
- _seed() `INFERRED`
- test_release_database_upgrades_to_fresh_schema() `INFERRED`
- test_v0_4_1_messages_and_tools_are_renumbered_on_one_timeline() `INFERRED`
- test_user_deny_finishes_tool_as_denied_and_persists_it() `INFERRED`
- *…and 22 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*