# PNG 角色卡读写

> 43 nodes · cohesion 0.10

## Key Concepts

- **test_character_card_png.py** (21 connections) — `tests/unit/test_character_card_png.py`
- **write_png_card()** (20 connections) — `src/pair_harness/character_cards/png.py`
- **png.py** (18 connections) — `src/pair_harness/character_cards/png.py`
- **read_png_card()** (18 connections) — `src/pair_harness/character_cards/png.py`
- **make_avatar_png()** (13 connections) — `tests/unit/test_character_card_png.py`
- **PngCardError** (9 connections) — `src/pair_harness/character_cards/png.py`
- **png_image_dimensions()** (7 connections) — `src/pair_harness/character_cards/png.py`
- **test_png_errors_preserve_reasons()** (7 connections) — `tests/unit/test_character_card_png.py`
- **test_png_image_dimensions_kept_after_write_png_card()** (7 connections) — `tests/unit/test_character_card_png.py`
- **test_png_import_then_json_export_then_reimport()** (6 connections) — `tests/unit/test_character_card_png.py`
- **test_write_and_read_v3_png_roundtrip()** (6 connections) — `tests/unit/test_character_card_png.py`
- **_iter_chunks()** (5 connections) — `src/pair_harness/character_cards/png.py`
- **_chunk()** (5 connections) — `tests/unit/test_character_card_png.py`
- **test_png_truncated_chunk_fails()** (5 connections) — `tests/unit/test_character_card_png.py`
- **_text_chunk()** (5 connections) — `tests/unit/test_character_card_png.py`
- **_png_image_bytes()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_ccv3_preferred_over_chara()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_png_bad_crc_and_missing_iend_fail()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_png_double_write_replaces_old_metadata()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_png_image_dimensions_malformed_returns_none()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_png_metadata_is_v3_json_with_avatar_card_data()** (4 connections) — `tests/unit/test_character_card_png.py`
- **test_read_v2_chara_keyword_png()** (4 connections) — `tests/unit/test_character_card_png.py`
- **_chunk_bytes()** (3 connections) — `src/pair_harness/character_cards/png.py`
- **_make_text_chunk()** (3 connections) — `src/pair_harness/character_cards/png.py`
- **_png_with_ihdr()** (3 connections) — `tests/unit/test_character_card_png.py`
- *... and 18 more nodes in this community*

## Relationships

- [角色卡编解码与兼容报告](角色卡编解码与兼容报告.md) (18 shared connections)
- [世界书深度注入激活](世界书深度注入激活.md) (6 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (5 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (4 shared connections)
- [角色卡模型与 HSR 扩展](角色卡模型与_HSR_扩展.md) (2 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (1 shared connections)
- [character_cards: _generate_png_fixt…](character_cards-__generate_png_fixt….md) (1 shared connections)

## Source Files

- `src/pair_harness/character_cards/png.py`
- `tests/unit/test_character_card_png.py`

## Audit Trail

- EXTRACTED: 110 (89%)
- INFERRED: 14 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*