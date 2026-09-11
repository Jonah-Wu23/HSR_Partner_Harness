# 角色卡 PNG 命令测试

> 27 nodes · cohesion 0.10

## Key Concepts

- **test_card_png_commands.py** (15 connections) — `tests/unit/test_card_png_commands.py`
- **command()** (13 connections) — `tests/unit/test_card_png_commands.py`
- **service()** (4 connections) — `tests/unit/test_card_png_commands.py`
- **test_export_png_builtin_card_read_only()** (4 connections) — `tests/unit/test_card_png_commands.py`
- **test_export_png_without_avatar_fails()** (4 connections) — `tests/unit/test_card_png_commands.py`
- **test_peek_import_png_corrupted_content()** (4 connections) — `tests/unit/test_card_png_commands.py`
- **test_import_export_reimport_roundtrip()** (3 connections) — `tests/unit/test_card_png_commands.py`
- **test_import_png_as_duplicate_renames()** (3 connections) — `tests/unit/test_card_png_commands.py`
- **test_import_png_full_chain()** (3 connections) — `tests/unit/test_card_png_commands.py`
- **test_peek_import_json_alias_same_handler()** (3 connections) — `tests/unit/test_card_png_commands.py`
- **test_peek_import_json_preserves_existing_fields()** (3 connections) — `tests/unit/test_card_png_commands.py`
- **test_peek_import_png_extension_mismatch_still_png()** (3 connections) — `tests/unit/test_card_png_commands.py`
- **test_peek_import_png_fixture()** (3 connections) — `tests/unit/test_card_png_commands.py`
- **DesktopCommand** (1 connections)
- **fixture** (1 connections)
- **Path** (1 connections)
- **card.peek_import / card.import_png / card.export_png 命令测试（V0.3.7 集成波）。…** (1 connections) — `tests/unit/test_card_png_commands.py`
- **签名为 PNG 但内容损坏：如实报 card_import_failed 且 message 非空。** (1 connections) — `tests/unit/test_card_png_commands.py`
- **import_png 全链路：落库 + 头像资产真实入库 + hsr.avatar_asset 回写。** (1 connections) — `tests/unit/test_card_png_commands.py`
- **as_duplicate=True 名称追加「（副本）」；不查重不改名（契约 §1.2）。** (1 connections) — `tests/unit/test_card_png_commands.py`
- **import→export→再 import 往返：世界书 20 条、greeting 6、extensions 含 hsr。** (1 connections) — `tests/unit/test_card_png_commands.py`
- **无头像卡 export_png → card_export_failed、message 含「头像」，不合成默认图。** (1 connections) — `tests/unit/test_card_png_commands.py`
- **内置卡 export_png → card_read_only。** (1 connections) — `tests/unit/test_card_png_commands.py`
- **peek JSON 路径：format=json、既有字段不回归（契约 §1.1 别名行为）。** (1 connections) — `tests/unit/test_card_png_commands.py`
- **card.peek_import_json 是 card.peek_import 的 deprecated 别名（同一行为）。** (1 connections) — `tests/unit/test_card_png_commands.py`
- *... and 2 more nodes in this community*

## Relationships

- [桌面后端角色卡命令](桌面后端角色卡命令.md) (3 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (1 shared connections)
- [Demo 服务与队列测试](Demo_服务与队列测试.md) (1 shared connections)

## Source Files

- `tests/unit/test_card_png_commands.py`

## Audit Trail

- EXTRACTED: 39 (91%)
- INFERRED: 4 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*