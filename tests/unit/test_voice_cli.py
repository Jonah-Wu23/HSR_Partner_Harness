"""create_qwen_voice.py 纯函数测试（不触网）。"""
import importlib.util
import sys
import wave
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SPEC = importlib.util.spec_from_file_location("create_qwen_voice", SCRIPTS / "create_qwen_voice.py")
cli = importlib.util.module_from_spec(SPEC)
sys.modules["create_qwen_voice"] = cli
SPEC.loader.exec_module(cli)


def _make_wav(path: Path, frames: int, framerate: int = 48000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x01" * frames)


# ---------------------------------------------------------------- normalize_prefix

def test_normalize_prefix_lowercases_and_strips() -> None:
    assert cli.normalize_prefix("Phainon_01!") == "phainon01"


def test_normalize_prefix_truncates_to_10() -> None:
    assert cli.normalize_prefix("ancient_machine") == "ancientmac"


def test_normalize_prefix_rejects_empty() -> None:
    with pytest.raises(cli.VoiceCliError):
        cli.normalize_prefix("!!!")
    with pytest.raises(cli.VoiceCliError):
        cli.normalize_prefix("")


# ---------------------------------------------------------------- payload 构造

def test_build_clone_payload_shape() -> None:
    payload = cli.build_clone_payload("phainon", "https://example.com/a.wav")
    assert payload["model"] == "voice-enrollment"
    assert payload["input"] == {
        "action": "create_voice",
        "target_model": "qwen-audio-3.0-tts-flash",
        "prefix": "phainon",
        "url": "https://example.com/a.wav",
    }


def test_build_design_payload_voice_enrollment_form() -> None:
    payload = cli.build_design_payload(
        "ancientmachine", "中年男性声音", "试听文本", "qwen-audio-3.0-tts-flash"
    )
    assert payload["model"] == "voice-enrollment"
    assert payload["input"]["action"] == "create_voice"
    assert payload["input"]["prefix"] == "ancientmachine"
    assert payload["input"]["voice_prompt"] == "中年男性声音"
    assert payload["parameters"] == {"sample_rate": 24000, "response_format": "wav"}
    assert "preferred_name" not in payload["input"]


def test_build_design_payload_qwen_voice_design_form() -> None:
    payload = cli.build_design_payload(
        "custom", "描述", "试听", "qwen3-tts-vd-2026-01-26",
        model="qwen-voice-design", action="create",
    )
    assert payload["model"] == "qwen-voice-design"
    assert payload["input"]["action"] == "create"
    assert payload["input"]["preferred_name"] == "custom"
    assert "prefix" not in payload["input"]


# ---------------------------------------------------------------- WAV 选择与拼接

def test_pick_longest_wav(tmp_path) -> None:
    _make_wav(tmp_path / "a.wav", 100)
    _make_wav(tmp_path / "b.wav", 300)
    _make_wav(tmp_path / "c.wav", 200)
    assert cli.pick_longest_wav(tmp_path).name == "b.wav"


def test_pick_longest_wav_empty_dir_raises(tmp_path) -> None:
    with pytest.raises(cli.VoiceCliError, match="没有 .wav"):
        cli.pick_longest_wav(tmp_path)


def test_concat_wavs_inserts_silence_and_preserves_params(tmp_path) -> None:
    _make_wav(tmp_path / "a.wav", 4800)  # 0.1s @48k
    _make_wav(tmp_path / "b.wav", 4800)
    out = tmp_path / "out" / "concat.wav"

    cli.concat_wavs([tmp_path / "a.wav", tmp_path / "b.wav"], out, silence_s=0.5)

    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 48000
        # 0.1 + 0.5 + 0.1 = 0.7s
        assert w.getnframes() == 4800 + 24000 + 4800


def test_concat_wavs_mismatched_params_raises(tmp_path) -> None:
    _make_wav(tmp_path / "a.wav", 100, framerate=48000)
    _make_wav(tmp_path / "b.wav", 100, framerate=16000)
    with pytest.raises(cli.VoiceCliError, match="参数不一致"):
        cli.concat_wavs(
            [tmp_path / "a.wav", tmp_path / "b.wav"], tmp_path / "out.wav"
        )


# ---------------------------------------------------------------- data URI 与响应解析

def test_data_uri_for_wav(tmp_path) -> None:
    src = tmp_path / "x.wav"
    src.write_bytes(b"\x00\x01\x02")
    uri = cli.data_uri_for(src)
    assert uri.startswith("data:audio/wav;base64,")


def test_extract_voice_id_from_voice_enrollment() -> None:
    result = {"output": {"voice_id": "qwen-audio-3.0-tts-flash-phainon-abc"}}
    assert cli.extract_voice_id(result, "voice-enrollment") == "qwen-audio-3.0-tts-flash-phainon-abc"


def test_extract_voice_id_from_qwen_voice_design() -> None:
    result = {"output": {"voice": "qwen3-tts-vd-custom-xyz"}}
    assert cli.extract_voice_id(result, "qwen-voice-design") == "qwen3-tts-vd-custom-xyz"


def test_extract_voice_id_missing_raises() -> None:
    with pytest.raises(cli.VoiceCliError, match="voice_id"):
        cli.extract_voice_id({"output": {}}, "voice-enrollment")


def test_save_preview_audio_writes_file(tmp_path) -> None:
    import base64

    raw = b"\x52\x49\x46\x46" + b"\x00" * 100
    result = {"output": {"preview_audio": {"data": base64.b64encode(raw).decode()}}}
    out = cli.save_preview_audio(result, "ancientmachine", tmp_path)
    assert out is not None
    assert out.read_bytes() == raw


def test_save_preview_audio_none_when_absent(tmp_path) -> None:
    assert cli.save_preview_audio({"output": {}}, "x", tmp_path) is None


def test_cli_parser_has_subcommands() -> None:
    parser = cli.build_parser()
    for name in ("clone", "design", "adopt"):
        assert name in parser._subparsers._group_actions[0].choices  # noqa: SLF001
