import pytest

from pair_harness.config.pairs import PairConfigError, load_pair_config, load_prompt


def test_phainon_pair_config_loads_names_colors_and_prompts() -> None:
    config = load_pair_config("phainon_ancient_machine")

    assert config.character.name == "白厄"
    assert config.assistant.name == "神秘的古代机械"
    assert config.theme.character_active == "#296CE1"
    assert config.theme.assistant_primary == "#B08D57"
    assert "文件和命令都没有执行权" in load_prompt(config.character.prompt)


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

