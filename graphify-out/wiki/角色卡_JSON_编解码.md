# 角色卡 JSON 编解码

> 41 nodes · cohesion 0.11

## Key Concepts

- **load_card_json()** (34 connections) — `src/pair_harness/character_cards/codec.py`
- **load_card_payload()** (31 connections) — `src/pair_harness/character_cards/codec.py`
- **test_character_card_codec.py** (25 connections) — `tests/unit/test_character_card_codec.py`
- **dump_card_v3()** (24 connections) — `src/pair_harness/character_cards/codec.py`
- **_extend_compat_report()** (10 connections) — `src/pair_harness/character_cards/codec.py`
- **CompatReport** (9 connections) — `src/pair_harness/character_cards/codec.py`
- **NotExecutedItem** (9 connections) — `src/pair_harness/character_cards/codec.py`
- **_extend_runtime_trigger_not_run()** (8 connections) — `src/pair_harness/character_cards/codec.py`
- **_load_sample()** (8 connections) — `tests/unit/test_character_card_codec.py`
- **_collect_runtime_trigger_paths()** (5 connections) — `src/pair_harness/character_cards/codec.py`
- **test_hsr_extension_roundtrip_and_fixed_model()** (5 connections) — `tests/unit/test_character_card_codec.py`
- **_book_report()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_baiyu_roundtrip_import_export_import()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_export_writes_root_compat_copies()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_import_failures_preserve_reasons()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_report_lists_world_book_fields_not_run()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_unknown_data_field_and_zero_insertion_order_preserved()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_unknown_third_party_extension_preserved()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_world_book_unknown_entry_fields_preserved()** (4 connections) — `tests/unit/test_character_card_codec.py`
- **test_export_drops_local_asset_references()** (3 connections) — `tests/unit/test_character_card_codec.py`
- **test_export_writes_st_position_for_depth_entries()** (3 connections) — `tests/unit/test_character_card_codec.py`
- **test_import_baiyu_sample_core_fields()** (3 connections) — `tests/unit/test_character_card_codec.py`
- **test_import_baiyu_sample_extensions_and_root_extras()** (3 connections) — `tests/unit/test_character_card_codec.py`
- **test_import_baiyu_sample_five_alternate_greetings()** (3 connections) — `tests/unit/test_character_card_codec.py`
- **test_import_baiyu_sample_world_book()** (3 connections) — `tests/unit/test_character_card_codec.py`
- *... and 16 more nodes in this community*

## Relationships

- [角色卡编解码与导入](角色卡编解码与导入.md) (21 shared connections)
- [角色卡 PNG 读写](角色卡_PNG_读写.md) (14 shared connections)
- [角色卡仓储与归档](角色卡仓储与归档.md) (8 shared connections)
- [角色卡导入与兼容报告](角色卡导入与兼容报告.md) (7 shared connections)
- [角色卡模型与提示装配](角色卡模型与提示装配.md) (5 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (4 shared connections)
- [角色卡管理命令处理](角色卡管理命令处理.md) (3 shared connections)
- [世界书条目激活匹配](世界书条目激活匹配.md) (2 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (1 shared connections)
- [角色卡宏扫描与展开](角色卡宏扫描与展开.md) (1 shared connections)
- [千问音色复刻工具](千问音色复刻工具.md) (1 shared connections)

## Source Files

- `src/pair_harness/character_cards/codec.py`
- `tests/unit/test_character_card_codec.py`

## Audit Trail

- EXTRACTED: 147 (94%)
- INFERRED: 9 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*