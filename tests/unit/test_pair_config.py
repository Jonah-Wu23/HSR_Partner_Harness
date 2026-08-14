import pytest
from pair_harness.config.pairs import (
    PAIR_CATALOG_IDS,
    PairConfigError,
    adopt_voice_id,
    list_pair_configs,
    load_pair_config,
    load_prompt,
)


def _write_pair_yaml(path, *, newline="\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "pair_id: demo_pair\n"
        "character:\n"
        "  id: phainon\n"
        "  name: 白厄\n"
        "  prompt: config/prompts/characters/phainon.md\n"
        "  voice_id: demo-phainon\n"
        "assistant:\n"
        "  id: ancient_machine\n"
        "  name: 神秘的古代机械\n"
        "  prompt: config/prompts/assistants/ancient_machine.md\n"
        "  voice_id: demo-ancient-machine\n"
        "theme:\n"
        "  character_text: '#C7D4E3'\n"
    )
    path.write_text(body.replace("\n", newline), encoding="utf-8", newline="")


def test_phainon_pair_config_loads_names_colors_and_prompts() -> None:
    config = load_pair_config("phainon_ancient_machine")

    assert config.character.name == "白厄"
    assert config.assistant.name == "神秘的古代机械"
    assert config.theme.character_active == "#296CE1"
    assert config.theme.assistant_primary == "#B08D57"
    assert "文件和命令都没有执行权" in load_prompt(config.character.prompt)


def test_public_pair_catalog_loads_two_new_pairs_and_excludes_reviewer() -> None:
    configs = list_pair_configs()

    assert [config.pair_id for config in configs] == list(PAIR_CATALOG_IDS)
    assert [config.character.name for config in configs] == ["流萤", "三月七", "白厄"]
    assert [config.assistant.name for config in configs] == [
        "萨姆",
        "第四面镜",
        "神秘的古代机械",
    ]
    assert all(config.pair_id != "reviewer" for config in configs)


def test_missing_prompt_file_raises_pair_config_error(tmp_path) -> None:
    pair_dir = tmp_path / "config" / "pairs"
    pair_dir.mkdir(parents=True)
    (pair_dir / "broken.yaml").write_text(
        "pair_id: broken\n"
        "character:\n"
        "  id: c\n"
        "  name: 角色\n"
        "  prompt: config/prompts/missing.md\n"
        "  voice_id: demo\n"
        "assistant:\n"
        "  id: a\n"
        "  name: 助手\n"
        "  prompt: config/prompts/missing.md\n"
        "  voice_id: demo\n"
        "theme:\n"
        "  character_text: '#C7D4E3'\n"
        "  character_primary: '#8AA4D4'\n"
        "  character_deep: '#3A548C'\n"
        "  character_active: '#296CE1'\n"
        "  assistant_primary: '#B08D57'\n"
        "  assistant_bright: '#C5A059'\n"
        "  assistant_shadow: '#8C6B3F'\n",
        encoding="utf-8",
    )
    with pytest.raises(PairConfigError, match="prompt file not found"):
        load_pair_config("broken", root=tmp_path)


# ---------------------------------------------------------------- adopt_voice_id

def test_adopt_voice_id_replaces_only_voice_id_line_lf(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair, newline="\n")

    old = adopt_voice_id(pair, "character", "qwen-audio-3.0-tts-flash-phainon-abc123")

    assert old.strip() == "voice_id: demo-phainon"
    text = pair.read_text(encoding="utf-8")
    assert "voice_id: qwen-audio-3.0-tts-flash-phainon-abc123\n" in text
    assert "voice_id: demo-ancient-machine" in text  # assistant 行未动
    assert "name: 白厄" in text
    assert "pair_id: demo_pair" in text
    assert "\r\n" not in text  # 保留 LF


def test_adopt_voice_id_preserves_crlf(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair, newline="\r\n")

    adopt_voice_id(pair, "assistant", "qwen-audio-3.0-tts-flash-machine-xyz789")

    # 用原始字节验证，避免 read_text 的 universal newline 转换
    text = pair.read_bytes().decode("utf-8")
    assert "voice_id: qwen-audio-3.0-tts-flash-machine-xyz789\r\n" in text
    assert "voice_id: demo-phainon" in text  # character 行未动
    assert text.count("\r\n") == text.count("\n")  # 全部行仍是 CRLF


def test_adopt_voice_id_refuses_to_overwrite_real_id_without_force(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair)
    adopt_voice_id(pair, "character", "qwen-audio-3.0-tts-flash-phainon-abc123")

    with pytest.raises(PairConfigError, match="--force"):
        adopt_voice_id(pair, "character", "qwen-audio-3.0-tts-flash-phainon-new456")


def test_adopt_voice_id_force_rebuilds_real_id(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair)
    adopt_voice_id(pair, "character", "qwen-audio-3.0-tts-flash-phainon-abc123")

    old = adopt_voice_id(
        pair, "character", "qwen-audio-3.0-tts-flash-phainon-new456", force=True
    )

    assert old.strip() == "voice_id: qwen-audio-3.0-tts-flash-phainon-abc123"
    text = pair.read_text(encoding="utf-8")
    assert "voice_id: qwen-audio-3.0-tts-flash-phainon-new456\n" in text


def test_adopt_voice_id_rejects_invalid_role(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair)
    with pytest.raises(PairConfigError, match="character 或 assistant"):
        adopt_voice_id(pair, "narrator", "qwen-any-id")


def test_adopt_voice_id_rejects_empty_voice_id(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair)
    with pytest.raises(PairConfigError, match="voice_id 不能为空"):
        adopt_voice_id(pair, "character", "  ")


def test_adopt_voice_id_missing_section_raises(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    pair.parent.mkdir(parents=True)
    pair.write_text("pair_id: demo_pair\ncharacter:\n  id: phainon\n", encoding="utf-8")
    with pytest.raises(PairConfigError, match="未找到"):
        adopt_voice_id(pair, "assistant", "qwen-any-id")
