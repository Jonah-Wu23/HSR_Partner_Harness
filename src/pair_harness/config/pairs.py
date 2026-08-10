from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class NamedSpeakerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    prompt: str
    voice_id: str


class PairTheme(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    character_text: str
    character_primary: str
    character_deep: str
    character_active: str
    assistant_primary: str
    assistant_bright: str
    assistant_shadow: str


class PairConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pair_id: str
    character: NamedSpeakerConfig
    assistant: NamedSpeakerConfig
    theme: PairTheme


class PairConfigError(RuntimeError):
    """搭档配置缺失或损坏。"""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_pair_config(pair_id: str, root: Path | None = None) -> PairConfig:
    base = root or repository_root()
    path = base / "config" / "pairs" / f"{pair_id}.yaml"
    if not path.is_file():
        raise PairConfigError(f"pair config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = PairConfig.model_validate(data)
    if config.pair_id != pair_id:
        raise PairConfigError(
            f"pair id mismatch: expected {pair_id}, got {config.pair_id}"
        )
    # 计划 A2：prompt 文件必须在加载时就校验存在，缺失直接报错
    for label, speaker in (("character", config.character), ("assistant", config.assistant)):
        prompt_path = base / speaker.prompt
        if not prompt_path.is_file():
            raise PairConfigError(f"{label} prompt file not found: {prompt_path}")
    return config


def load_prompt(relative_path: str, root: Path | None = None) -> str:
    base = root or repository_root()
    return (base / relative_path).read_text(encoding="utf-8")

