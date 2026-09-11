# ServiceError

> God node · 139 connections · `src/pair_harness/desktop_backend/application_service.py`

**Community:** [桌面后端角色卡命令](桌面后端角色卡命令.md)

## Connections by Relation

### calls
- ._required_string() `EXTRACTED`
- .bootstrap() `EXTRACTED`
- ._select_conversation_context() `EXTRACTED`
- ._chat_submit() `EXTRACTED`
- ._voice_card_create() `EXTRACTED`
- ._build_runtime_candidate() `EXTRACTED`
- ._voice_preview() `EXTRACTED`
- ._conversation_scope() `EXTRACTED`
- ._current_account_project() `EXTRACTED`
- ._require_writable_card() `EXTRACTED`
- ._voice_provision() `EXTRACTED`
- ._canonicalize_provider_updates() `EXTRACTED`
- ._current_account_conversation() `EXTRACTED`
- .handle_command() `EXTRACTED`
- ._resolve_execution_context() `EXTRACTED`
- ._card_import_png() `EXTRACTED`
- ._card_set_avatar() `EXTRACTED`
- ._config_set() `EXTRACTED`
- ._diagnostics_prompt_assembly() `EXTRACTED`
- ._memory_scope_from_params() `EXTRACTED`
- *…and 65 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- application_service.py `EXTRACTED`

### imports
- router.py `EXTRACTED`
- desktop_backend/__main__.py `EXTRACTED`

### inherits
- RuntimeError `EXTRACTED`

### method
- .__init__() `EXTRACTED`

### rationale_for
- 可直接返回给前端的业务错误。 ``details``（V0.3.5）可选携带结构化附加字段，随错误响应体的 ``error.details`` 下发；不改变… `EXTRACTED`

### uses
- SidecarRouter `INFERRED`
- expect_service_error() `INFERRED`
- _run() `INFERRED`
- test_voice_tts_play_rejects_assistant_message() `INFERRED`
- test_voice_tts_play_skip_and_preview_commands() `INFERRED`
- test_config_set_failure_keeps_database_old_values() `INFERRED`
- test_voice_preview_allows_character_but_rejects_assistant_speakers() `INFERRED`
- test_client_cannot_forge_timeout_decision() `INFERRED`
- test_account_switch_failure_keeps_original_account() `INFERRED`
- test_playback_guard_allows_desktop_after_lease_released() `INFERRED`
- test_late_resolve_returns_real_terminal_details() `INFERRED`
- test_timeout_broadcasts_single_terminal_event() `INFERRED`
- test_playback_guard_rejects_desktop_and_other_remote() `INFERRED`
- test_app_reconnect_command_reports_clear_error_not_silent() `INFERRED`
- test_codex_login_commands_are_removed() `INFERRED`
- test_config_set_accepts_voice_credentials_but_locks_models() `INFERRED`
- test_conversation_and_engine_data_isolated_per_account() `INFERRED`
- test_oauth_provider_selection_is_rejected_without_writing_config() `INFERRED`
- test_project_commands_reject_foreign_account_ids() `INFERRED`
- test_voice_provision_rejects_assistant_speaker() `INFERRED`
- *…and 28 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*