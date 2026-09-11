# test_pair_config.py: adopt_voice_id()

> 15 nodes · cohesion 0.30

## Key Concepts

- **adopt_voice_id()** (12 connections) — `src/pair_harness/config/pairs.py`
- **test_pair_config.py** (12 connections) — `tests/unit/test_pair_config.py`
- **PairConfigError** (10 connections) — `src/pair_harness/config/pairs.py`
- **_write_pair_yaml()** (7 connections) — `tests/unit/test_pair_config.py`
- **test_adopt_voice_id_refuses_to_overwrite_real_id_without_force()** (4 connections) — `tests/unit/test_pair_config.py`
- **test_adopt_voice_id_rejects_empty_voice_id()** (4 connections) — `tests/unit/test_pair_config.py`
- **test_adopt_voice_id_rejects_invalid_role()** (4 connections) — `tests/unit/test_pair_config.py`
- **test_adopt_voice_id_force_rebuilds_real_id()** (3 connections) — `tests/unit/test_pair_config.py`
- **test_adopt_voice_id_missing_section_raises()** (3 connections) — `tests/unit/test_pair_config.py`
- **test_adopt_voice_id_preserves_crlf()** (3 connections) — `tests/unit/test_pair_config.py`
- **test_adopt_voice_id_replaces_only_voice_id_line_lf()** (3 connections) — `tests/unit/test_pair_config.py`
- **test_missing_prompt_file_raises_pair_config_error()** (3 connections) — `tests/unit/test_pair_config.py`
- **test_public_pair_catalog_loads_two_new_pairs_and_excludes_reviewer()** (2 connections) — `tests/unit/test_pair_config.py`
- **RuntimeError** (1 connections)
- **把 ``voice_id`` 写回 pair YAML 的 character/assistant 块，只改那一行。 保留文件其余内容与换行符原样（不经过…** (1 connections) — `src/pair_harness/config/pairs.py`

## Relationships

- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (8 shared connections)
- [音色创建 CLI](音色创建_CLI.md) (2 shared connections)

## Source Files

- `src/pair_harness/config/pairs.py`
- `tests/unit/test_pair_config.py`

## Audit Trail

- EXTRACTED: 35 (85%)
- INFERRED: 6 (15%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*