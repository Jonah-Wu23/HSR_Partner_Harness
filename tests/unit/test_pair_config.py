import pytest
from pair_harness.config.pairs import (
    PAIR_CATALOG_IDS,
    PairConfigError,
    adopt_voice_id,
    list_pair_configs,
    load_pair_config,
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


def test_pair_catalog_loads_public_pairs_in_order() -> None:
    configs = list_pair_configs()

    assert [config.pair_id for config in configs] == list(PAIR_CATALOG_IDS)
    assert [config.character.name for config in configs] == ["流萤", "三月七", "白厄"]
    assert [config.assistant.name for config in configs] == [
        "萨姆",
        "第四面镜",
        "神秘的古代机械",
    ]


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

@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_adopt_voice_id_replaces_only_target_line_and_keeps_newlines(tmp_path, newline) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair, newline=newline)

    old = adopt_voice_id(pair, "character", "qwen-audio-3.0-tts-flash-phainon-abc123")

    assert old == "demo-phainon"
    # 读原始字节，避开 read_text 的换行转换
    text = pair.read_bytes().decode("utf-8")
    assert f"voice_id: qwen-audio-3.0-tts-flash-phainon-abc123{newline}" in text
    assert "voice_id: demo-ancient-machine" in text
    assert "name: 白厄" in text
    assert text.count(newline) == text.count("\n")
    assert "\r" not in text.replace(newline, "")


def test_adopt_voice_id_overwrites_real_id_only_with_force(tmp_path) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    _write_pair_yaml(pair)
    adopt_voice_id(pair, "character", "qwen-audio-3.0-tts-flash-phainon-abc123")

    with pytest.raises(PairConfigError, match="--force"):
        adopt_voice_id(pair, "character", "qwen-audio-3.0-tts-flash-phainon-new456")

    old = adopt_voice_id(
        pair, "character", "qwen-audio-3.0-tts-flash-phainon-new456", force=True
    )

    assert old == "qwen-audio-3.0-tts-flash-phainon-abc123"
    text = pair.read_text(encoding="utf-8")
    assert "voice_id: qwen-audio-3.0-tts-flash-phainon-new456\n" in text


@pytest.mark.parametrize(
    ("body", "role", "voice_id", "message"),
    [
        (None, "narrator", "qwen-any-id", "character 或 assistant"),
        (None, "character", "  ", "voice_id 不能为空"),
        ("pair_id: demo_pair\ncharacter:\n  id: phainon\n", "assistant", "qwen-any-id", "未找到"),
    ],
)
def test_adopt_voice_id_rejects_invalid_input(tmp_path, body, role, voice_id, message) -> None:
    pair = tmp_path / "config" / "pairs" / "demo_pair.yaml"
    if body is None:
        _write_pair_yaml(pair)
    else:
        pair.parent.mkdir(parents=True)
        pair.write_text(body, encoding="utf-8")
    original = pair.read_bytes()

    with pytest.raises(PairConfigError, match=message):
        adopt_voice_id(pair, role, voice_id)
    assert pair.read_bytes() == original
