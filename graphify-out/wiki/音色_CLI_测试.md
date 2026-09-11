# 音色 CLI 测试

> 20 nodes · cohesion 0.12

## Key Concepts

- **test_voice_cli.py** (19 connections) — `tests/unit/test_voice_cli.py`
- **extract_voice_id()** (8 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **_make_wav()** (5 connections) — `tests/unit/test_voice_cli.py`
- **test_extract_voice_id_missing_raises()** (3 connections) — `tests/unit/test_voice_cli.py`
- **test_concat_wavs_inserts_silence_and_preserves_params()** (2 connections) — `tests/unit/test_voice_cli.py`
- **test_concat_wavs_mismatched_params_raises()** (2 connections) — `tests/unit/test_voice_cli.py`
- **test_data_uri_rejects_unknown_audio_extension()** (2 connections) — `tests/unit/test_voice_cli.py`
- **test_extract_voice_id_from_voice_enrollment()** (2 connections) — `tests/unit/test_voice_cli.py`
- **test_normalize_prefix_rejects_empty()** (2 connections) — `tests/unit/test_voice_cli.py`
- **test_normalize_prefix_rejects_more_than_10_characters()** (2 connections) — `tests/unit/test_voice_cli.py`
- **test_pick_longest_wav()** (2 connections) — `tests/unit/test_voice_cli.py`
- **从成功响应提取 ``output.voice_id``；缺失即真实失败，不得合成。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **Path** (1 connections)
- **create_qwen_voice.py 纯函数测试（不触网）。** (1 connections) — `tests/unit/test_voice_cli.py`
- **test_cli_parser_has_subcommands()** (1 connections) — `tests/unit/test_voice_cli.py`
- **test_data_uri_for_wav()** (1 connections) — `tests/unit/test_voice_cli.py`
- **test_normalize_prefix_lowercases_and_strips()** (1 connections) — `tests/unit/test_voice_cli.py`
- **test_pick_longest_wav_empty_dir_raises()** (1 connections) — `tests/unit/test_voice_cli.py`
- **test_save_preview_audio_none_when_absent()** (1 connections) — `tests/unit/test_voice_cli.py`
- **test_save_preview_audio_writes_file()** (1 connections) — `tests/unit/test_voice_cli.py`

## Relationships

- [adapters: PostJson](adapters-_PostJson.md) (5 shared connections)
- [adapters: qwen_voice_customi…](adapters-_qwen_voice_customi….md) (5 shared connections)
- [adapters: customization_endp…](adapters-_customization_endp….md) (1 shared connections)
- [test_v032_m6_voice.py: test_v032_m6_voice…](test_v032_m6_voice.py-_test_v032_m6_voice….md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- `tests/unit/test_voice_cli.py`

## Audit Trail

- EXTRACTED: 31 (89%)
- INFERRED: 4 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*