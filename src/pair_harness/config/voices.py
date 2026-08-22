"""参考音色 manifest 加载（V0.3.2 M6，计划 3.8 / 5.15 节）。

``config/voices/reference_voice_manifest.json`` 记录 6 个说话方的
speaker_id、安装包本地素材路径、可选公开 URL、prefix 和固定
target_model。复刻默认把安装包内音频转为 data URI 直接提交；公开 URL
只保留为素材来源记录和人工排查备用。

加载即校验（Let It Fail）：

- 恰好 6 项、speaker_id 集合与固定顺序一致；
- 每项 ``target_model`` 必须等于 ``VOICE_TTS_MODEL``；
- prefix 为 1~10 位小写字母数字且互不重复；
- 复刻项：本地参考音频存在；public_url 为空或 HTTP(S) 地址；
- 设计项：仅古代机械一项，本地提示词文件存在。

运行时资源缺少任一文件时直接抛 :class:`VoiceManifestError`，不用空
条目或合成 URL 掩盖。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pair_harness.config.pairs import list_pair_configs, repository_root
from pair_harness.voice_models import VOICE_TTS_MODEL

MANIFEST_RELATIVE_PATH = Path("config") / "voices" / "reference_voice_manifest.json"

# 固定执行顺序：5 个复刻 + 1 个设计（计划 5.15）
REFERENCE_SPEAKER_ORDER: tuple[str, ...] = (
    "phainon",
    "firefly",
    "sam",
    "march7",
    "fourth_mirror",
    "ancient_machine",
)
DESIGN_SPEAKER_IDS = frozenset({"ancient_machine"})

# 古代机械声音设计固定试听文本（与 scripts/create_qwen_voice.py 的真实
# 生成流程一致；改文本视为换音色素材，需按正式版本处理）
ANCIENT_MACHINE_PREVIEW_TEXT = "你好，我是神秘的古代机械。核心模块已启动，正在等待指令。"


def assistant_speaker_ids(*, root: Path | None = None) -> frozenset[str]:
    """运行时从配对目录推导全部助手侧说话方 id 集合（V0.3.3）。

    助手永不使用 TTS。provision / preview 对助手侧说话方的拒绝判定以
    此集合为唯一依据，禁止在代码里硬编码说话方名单——说话方随
    ``config/pairs/*.yaml`` 的 ``assistant.id`` 推导。
    """
    return frozenset(pair.assistant.id for pair in list_pair_configs(root=root))

_PREFIX_RE = re.compile(r"^[a-z0-9]{1,10}$")


class VoiceManifestError(RuntimeError):
    """manifest 缺失、结构不符或本地素材文件缺失。"""


@dataclass(frozen=True)
class ReferenceVoiceEntry:
    speaker_id: str
    display_name: str
    method: Literal["clone", "design"]
    local_path: Path
    public_url: str
    prefix: str
    target_model: str

    @property
    def profile_key(self) -> str:
        """账号级音色映射键（provider_configs）。"""
        return f"voice.profile.{self.speaker_id}.voice_id"


def load_reference_voice_manifest(
    root: Path | None = None,
) -> tuple[ReferenceVoiceEntry, ...]:
    base = root or repository_root()
    path = base / MANIFEST_RELATIVE_PATH
    if not path.is_file():
        raise VoiceManifestError(f"参考音色 manifest 不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceManifestError(f"参考音色 manifest 无法解析: {path}: {exc}") from exc

    items = data.get("speakers") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise VoiceManifestError(f"manifest 缺少 speakers 数组: {path}")

    entries: list[ReferenceVoiceEntry] = []
    prefixes: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise VoiceManifestError(f"manifest 条目不是对象: {raw!r}")
        speaker_id = str(raw.get("speaker_id") or "")
        if not speaker_id:
            raise VoiceManifestError(f"manifest 条目缺少 speaker_id: {raw!r}")
        method = str(raw.get("method") or "")
        if method not in ("clone", "design"):
            raise VoiceManifestError(
                f"{speaker_id}: method 必须是 clone 或 design，得到 {method!r}"
            )
        if (method == "design") != (speaker_id in DESIGN_SPEAKER_IDS):
            raise VoiceManifestError(
                f"{speaker_id}: 声音设计项固定为 ancient_machine，与 method={method} 不一致"
            )
        target_model = str(raw.get("target_model") or "")
        if target_model != VOICE_TTS_MODEL:
            raise VoiceManifestError(
                f"{speaker_id}: target_model 必须固定为 {VOICE_TTS_MODEL}，"
                f"得到 {target_model!r}"
            )
        prefix = str(raw.get("prefix") or "")
        if not _PREFIX_RE.match(prefix):
            raise VoiceManifestError(
                f"{speaker_id}: prefix 必须是 1~10 位小写字母数字，得到 {prefix!r}"
            )
        if prefix in prefixes:
            raise VoiceManifestError(f"prefix 重复: {prefix}")
        prefixes.add(prefix)

        local_value = str(raw.get("local_path") or "")
        local_path = base / local_value
        if not local_path.is_file():
            raise VoiceManifestError(f"{speaker_id}: 本地素材不存在: {local_path}")

        public_url = str(raw.get("public_url") or "")
        if method == "clone":
            if public_url and not public_url.startswith(("http://", "https://")):
                raise VoiceManifestError(
                    f"{speaker_id}: 复刻项 public_url 必须为空或 HTTP(S) 地址，"
                    f"得到 {public_url!r}"
                )
        elif public_url:
            raise VoiceManifestError(
                f"{speaker_id}: 声音设计项不使用 public_url，得到 {public_url!r}"
            )

        entries.append(
            ReferenceVoiceEntry(
                speaker_id=speaker_id,
                display_name=str(raw.get("display_name") or speaker_id),
                method=method,  # type: ignore[arg-type]
                local_path=local_path,
                public_url=public_url,
                prefix=prefix,
                target_model=target_model,
            )
        )

    if tuple(entry.speaker_id for entry in entries) != REFERENCE_SPEAKER_ORDER:
        raise VoiceManifestError(
            "manifest speaker 顺序/集合与固定契约不一致，期望 "
            f"{REFERENCE_SPEAKER_ORDER}，实际 {[e.speaker_id for e in entries]}"
        )
    return tuple(entries)
