# 配对级长期记忆的结构与作用域校验。作用域为 account_id + project_id + pair_id + character_ref +
# assistant_identity；项目为空的日常聊天不读写长期记忆。记忆内容由模型负责，这里不解析、
# 不摘要、不筛选也不截断。

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from .contracts import FrozenModel, utc_now

# 记忆相关错误码。
MEMORY_NOT_FOUND = "memory_not_found"
# 结构不合法（作用域或内容类型）。
MEMORY_INVALID = "memory_invalid"

BUILTIN_CHARACTER_PREFIX = "builtin:"
CARD_CHARACTER_PREFIX = "card:"


class PairMemoryError(ValueError):
    """记忆操作的真实失败；``code`` 为错误码。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def character_ref_for(
    *, character_card_id: str | None, pair_character_id: str
) -> str:
    """把聊天的角色身份归一化为 ``character_ref``。

    聊天持久化了角色卡 id 时使用 ``card:<id>``（卡已删除也保持原值，
    由调用方按孤立数据处理），否则使用内置角色 ``builtin:<pair.character.id>``。
    """
    card_id = (character_card_id or "").strip()
    if card_id:
        return f"{CARD_CHARACTER_PREFIX}{card_id}"
    builtin_id = (pair_character_id or "").strip()
    if not builtin_id:
        raise PairMemoryError(
            "内置角色 id 为空，无法解析 character_ref", code=MEMORY_INVALID
        )
    return f"{BUILTIN_CHARACTER_PREFIX}{builtin_id}"


@dataclass(frozen=True)
class ConversationIdentity:
    """解析记忆作用域所需的权威身份输入（全部来自服务端权威来源）。

    ``pair_character_id``/``assistant_identity`` 必须取自该聊天绑定的搭档
    配置（``pair.character.id`` / ``pair.assistant.id``），不接受客户端参数。
    """

    account_id: str
    project_id: str | None
    conversation_id: str
    pair_id: str
    character_card_id: str | None
    pair_character_id: str
    assistant_identity: str


class MemoryScope(FrozenModel):
    """长期记忆作用域（五分量）。"""

    account_id: str
    project_id: str
    pair_id: str
    character_ref: str
    assistant_identity: str

    @field_validator("account_id", "project_id", "pair_id", "assistant_identity")
    @classmethod
    def _require_text(cls, value: str, info: Any) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError(f"记忆作用域字段不得为空：{info.field_name}")
        return text

    @field_validator("character_ref")
    @classmethod
    def _require_character_ref(cls, value: str) -> str:
        text = (value or "").strip()
        for prefix in (BUILTIN_CHARACTER_PREFIX, CARD_CHARACTER_PREFIX):
            if text.startswith(prefix):
                if not text[len(prefix) :]:
                    raise ValueError("character_ref 缺少角色标识")
                return text
        raise ValueError(
            "character_ref 必须以 builtin: 或 card: 开头，得到：" + repr(text)
        )


def resolve_memory_scope(identity: ConversationIdentity) -> MemoryScope | None:
    """解析聊天的长期记忆作用域；项目为空的日常聊天返回 None。

    只使用聊天自身持久化的 ``character_card_id`` 与权威搭档配置的
    ``assistant.id``：角色卡被删除时仍解析为 ``card:<id>``，不并入内置角色。
    """
    if not (identity.project_id or "").strip():
        return None
    character_ref = character_ref_for(
        character_card_id=identity.character_card_id,
        pair_character_id=identity.pair_character_id,
    )
    try:
        return MemoryScope(
            account_id=identity.account_id,
            project_id=identity.project_id,
            pair_id=identity.pair_id,
            character_ref=character_ref,
            assistant_identity=identity.assistant_identity,
        )
    except ValueError as exc:
        raise PairMemoryError(str(exc), code=MEMORY_INVALID) from exc


class PairMemory(FrozenModel):
    """一条配对级长期记忆（与 TS ``PairMemory`` 同形）。"""

    memory_id: str
    scope: MemoryScope
    content: Mapping[str, Any]
    status: Literal["active", "deleted"] = "active"
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("memory_id")
    @classmethod
    def _require_memory_id(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("memory_id 不得为空")
        return text

    @field_validator("content")
    @classmethod
    def _require_object(cls, value: Any) -> Mapping[str, Any]:
        # 内容由模型负责，代码只验证“是 JSON 对象”这一结构事实。
        if not isinstance(value, Mapping):
            raise ValueError("记忆内容必须是 JSON 对象")
        return dict(value)


def active_memories(memories: Iterable[PairMemory]) -> tuple[PairMemory, ...]:
    """只返回 active 记录（deleted 不参与装配，但保留在库中）。"""
    return tuple(memory for memory in memories if memory.status == "active")
