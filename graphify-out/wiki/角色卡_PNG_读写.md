# 角色卡 PNG 读写

> 41 nodes · cohesion 0.11

## Key Concepts

- **write_png_card()** (19 connections) — `src/pair_harness/character_cards/png.py`
- **test_character_card_png.py** (18 connections) — `tests/unit/test_character_card_png.py`
- **png.py** (16 connections) — `src/pair_harness/character_cards/png.py`
- **read_png_card()** (14 connections) — `src/pair_harness/character_cards/png.py`
- **make_avatar_png()** (13 connections) — `tests/unit/test_character_card_png.py`
- **PngCardError** (11 connections) — `src/pair_harness/character_cards/png.py`
- **test_png_errors_preserve_reasons()** (9 connections) — `tests/unit/test_character_card_png.py`
- **png_image_dimensions()** (6 connections) — `src/pair_harness/character_cards/png.py`
- **test_png_import_then_json_export_then_reimport()** (6 connections) — `tests/unit/test_character_card_png.py`
- **test_png_truncated_chunk_fails()** (6 connections) — `tests/unit/test_character_card_png.py`
- **test_write_and_read_v3_png_roundtrip()** (6 connections) — `tests/unit/test_character_card_png.py`
- **_iter_chunks()** (5 connections) — `src/pair_harness/character_cards/png.py`
- **_generate_png_fixture.py** (5 connections) — `tests/fixtures/character_cards/_generate_png_fixture.py`
- **_chunk()** (5 connections) — `tests/unit/test_character_card_png.py`
- **test_png_bad_crc_and_missing_iend_fail()** (5 connections) — `tests/unit/test_character_card_png.py`
- **test_png_image_dimensions_kept_after_write_png_card()** (5 connections) — `tests/unit/test_character_card_png.py`
- **_text_chunk()** (5 connections) — `tests/unit/test_character_card_png.py`
- **main()** (4 connections) — `tests/fixtures/character_cards/_generate_png_fixture.py`
- **make_avatar_png()** (4 connections) — `tests/fixtures/character_cards/_generate_png_fixture.py`
- **test_ccv3_preferred_over_chara()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_png_double_write_replaces_old_metadata()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_png_metadata_is_v3_json_with_avatar_card_data()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_read_v2_chara_keyword_png()** (4 connections) — `tests/unit/test_character_card_png.py`
- **_chunk_bytes()** (3 connections) — `src/pair_harness/character_cards/png.py`
- **_make_text_chunk()** (3 connections) — `src/pair_harness/character_cards/png.py`
- *... and 16 more nodes in this community*

## Relationships

- [角色卡 JSON 编解码](角色卡_JSON_编解码.md) (14 shared connections)
- [角色卡编解码与导入](角色卡编解码与导入.md) (5 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (5 shared connections)
- [角色卡导入与兼容报告](角色卡导入与兼容报告.md) (4 shared connections)
- [角色卡模型与提示装配](角色卡模型与提示装配.md) (2 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (1 shared connections)
- [角色卡管理命令处理](角色卡管理命令处理.md) (1 shared connections)

## Source Files

- `src/pair_harness/character_cards/png.py`
- `tests/fixtures/character_cards/_generate_png_fixture.py`
- `tests/unit/test_character_card_png.py`

## Audit Trail

- EXTRACTED: 113 (94%)
- INFERRED: 7 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*