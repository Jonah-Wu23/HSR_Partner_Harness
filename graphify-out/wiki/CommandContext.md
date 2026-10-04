# CommandContext

> God node · 91 connections · `src/pair_harness/desktop_backend/commands.py`

**Community:** [角色卡管理命令处理](角色卡管理命令处理.md)

## Connections by Relation

### calls
- ._submit_voice_input() `EXTRACTED`
- .context() `EXTRACTED`

### contains
- commands.py `EXTRACTED`

### imports
- application_service.py `EXTRACTED`

### rationale_for
- 传输层注入的调用方身份，handler 只从这里读取，不信任 params 里的同名字段。 `EXTRACTED`

### references
- ._chat_submit() `EXTRACTED`
- ._voice_preview() `EXTRACTED`
- ._conversation_open() `EXTRACTED`
- ._voice_card_create() `EXTRACTED`
- ._voice_provision() `EXTRACTED`
- ._card_set_avatar() `EXTRACTED`
- ._config_set() `EXTRACTED`
- ._conversation_create() `EXTRACTED`
- ._diagnostics_prompt_assembly() `EXTRACTED`
- ._voice_card_bind_reference() `EXTRACTED`
- ._account_switch() `EXTRACTED`
- ._card_import_png() `EXTRACTED`
- ._memory_update() `EXTRACTED`
- ._project_create() `EXTRACTED`
- ._summary_regenerate() `EXTRACTED`
- ._voice_tts_play() `EXTRACTED`
- ._account_register() `EXTRACTED`
- ._card_export_png() `EXTRACTED`
- ._conversation_set_mode() `EXTRACTED`
- ._memory_create() `EXTRACTED`
- *…and 64 more `references` connection(s) not listed (lowest-degree first to go)*

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- test_lease_expiry_reclaims_and_restores_desktop() `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*