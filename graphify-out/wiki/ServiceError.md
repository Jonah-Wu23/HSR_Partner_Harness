# ServiceError

> God node · 94 connections · `src/pair_harness/desktop_backend/application_service.py`

**Community:** [角色卡管理命令处理](角色卡管理命令处理.md)

## Connections by Relation

### calls
- ._required_string() `EXTRACTED`
- ._chat_submit() `EXTRACTED`
- ._voice_preview() `EXTRACTED`
- ._current_account_conversation() `EXTRACTED`
- ._require_writable_card() `EXTRACTED`
- ._voice_card_create() `EXTRACTED`
- ._voice_provision() `EXTRACTED`
- ._conversation_scope() `EXTRACTED`
- ._canonicalize_provider_updates() `EXTRACTED`
- ._card_set_avatar() `EXTRACTED`
- ._config_set() `EXTRACTED`
- ._diagnostics_prompt_assembly() `EXTRACTED`
- ._voice_card_bind_reference() `EXTRACTED`
- ._account_switch() `EXTRACTED`
- ._card_import_png() `EXTRACTED`
- ._memory_scope_from_params() `EXTRACTED`
- ._memory_update() `EXTRACTED`
- ._project_create() `EXTRACTED`
- ._summary_regenerate() `EXTRACTED`
- ._voice_tts_play() `EXTRACTED`
- *…and 61 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- application_service.py `EXTRACTED`

### imports
- desktop_backend/__main__.py `EXTRACTED`
- router.py `EXTRACTED`

### inherits
- RuntimeError `EXTRACTED`

### method
- .__init__() `EXTRACTED`

### rationale_for
- 可直接返回给前端的业务错误。 ``details`` 可选携带结构化附加字段，随错误响应体的 ``error.details`` 下发。 `EXTRACTED`

### uses
- expect_service_error() `INFERRED`
- _run() `INFERRED`
- SidecarRouter `INFERRED`
- test_client_cannot_forge_timeout_decision() `INFERRED`
- test_timeout_is_single_terminal_state() `INFERRED`
- test_playback_guard_follows_control_lease() `INFERRED`
- test_startup_mode_resolution() `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*