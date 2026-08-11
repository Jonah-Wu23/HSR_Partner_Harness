from __future__ import annotations

import sys
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
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
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


# 占位音色（尚未 enroll/design 时的 demo 值），adopt 时视为未启用
PLACEHOLDER_VOICE_PREFIX = "demo-"


def adopt_voice_id(path: Path, role: str, voice_id: str, *, force: bool = False) -> str:
    """把 ``voice_id`` 写回 pair YAML 的 character/assistant 块，只改那一行。

    保留文件其余内容与换行符原样（不经过 yaml 重新序列化）。
    默认拒绝覆盖已启用的真实 voice_id；``force=True`` 时允许重建。
    返回被替换的旧行文本。
    """
    if role not in ("character", "assistant"):
        raise PairConfigError(f"role 必须是 character 或 assistant，得到: {role!r}")
    voice_id = str(voice_id or "").strip()
    if not voice_id:
        raise PairConfigError("voice_id 不能为空")

    # newline="" 关闭换行转换：Windows 下默认会把 \r\n 转成 \n，导致无法保留原换行
    with path.open("r", encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines(keepends=True)
    section_marker = f"{role}:"
    in_section = False
    old_line = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == section_marker:
            in_section = True
            continue
        if in_section and stripped and not line[0].isspace():
            break  # 离开该块（下一个顶层键）
        if in_section and "voice_id:" in stripped:
            old_line = line
            current = stripped.split(":", 1)[1].strip()
            if current and not current.startswith(PLACEHOLDER_VOICE_PREFIX) and not force:
                raise PairConfigError(
                    f"{role}.voice_id 已是真实音色 {current!r}，如需覆盖请加 --force"
                )
            indent = line[: len(line) - len(line.lstrip())]
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines[index] = f"{indent}voice_id: {voice_id}{newline}"
            path.write_text("".join(lines), encoding="utf-8", newline="")
            return old_line
    raise PairConfigError(f"pair YAML 中未找到 {role}.voice_id 行: {path}")

