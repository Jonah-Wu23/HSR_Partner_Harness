"""配对级长期记忆纯逻辑（V0.3.9 契约冻结 §1/§2）。

契约出处：``.archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md`` §1（权威来源与身份）、§2（记忆）。

作用域（冻结）：

``account_id + project_id + pair_id + character_ref + assistant_identity``

- ``character_ref`` 由服务端从聊天解析：自定义角色为 ``card:<character_card_id>``，
  内置角色为 ``builtin:<pair.character.id>``；
- ``assistant_identity`` 必须来自该聊天绑定的权威搭档配置的 ``assistant.id``，
  每次读写重新解析，``pair_id`` 不可替代助手身份；
- 项目为空的日常聊天不读写长期记忆；
- 角色卡删除后原作用域保留为孤立数据（``card:<id>`` 不静默改成内置角色）。

本模块只做结构与作用域校验：不解析、不摘要、不按关键词筛选或截断模型产出的
记忆内容（Let It Go）。内容语义由模型负责。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from .contracts import FrozenModel, utc_now

# 契约 §7 错误码（记忆相关）。
MEMORY_SCOPE_MISMATCH = "memory_scope_mismatch"
MEMORY_NOT_FOUND = "memory_not_found"
# 结构不合法（作用域/内容类型）。契约要求"至少包括"上述两个码，这里如实细分。
MEMORY_INVALID = "memory_invalid"

BUILTIN_CHARACTER_PREFIX = "builtin:"
CARD_CHARACTER_PREFIX = "card:"


class MemoryError(ValueError):
    """记忆操作的真实失败；``code`` 为契约错误码。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def character_ref_for(
    *, character_card_id: str | None, pair_character_id: str
) -> str:
    """把聊天的角色身份归一化为契约 ``character_ref``。

    聊天持久化了角色卡 id 时使用 ``card:<id>``（卡已删除也保持原值，
    由调用方按孤立数据处理），否则使用内置角色 ``builtin:<pair.character.id>``。
    """
    card_id = (character_card_id or "").strip()
    if card_id:
        return f"{CARD_CHARACTER_PREFIX}{card_id}"
    builtin_id = (pair_character_id or "").strip()
    if not builtin_id:
        raise MemoryError("内置角色 id 为空，无法解析 character_ref", code=MEMORY_INVALID)
    return f"{BUILTIN_CHARACTER_PREFIX}{builtin_id}"


def character_ref_card_id(character_ref: str) -> str | None:
    """``card:<id>`` 返回卡 id；内置角色返回 None。"""
    if character_ref.startswith(CARD_CHARACTER_PREFIX):
        return character_ref[len(CARD_CHARACTER_PREFIX) :]
    return None


def is_card_character_ref(character_ref: str) -> bool:
    return character_ref.startswith(CARD_CHARACTER_PREFIX)


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
    """长期记忆作用域（契约 §1 五分量）。"""

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

    @property
    def scope_key(self) -> str:
        """唯一键的规范化文本（数据库唯一约束与查询过滤用）。

        使用排序后的 JSON 对象，避免分隔符歧义；与协议载荷无关，
        ``model_dump`` 不包含该属性。
        """
        return json.dumps(
            {
                "account_id": self.account_id,
                "assistant_identity": self.assistant_identity,
                "character_ref": self.character_ref,
                "pair_id": self.pair_id,
                "project_id": self.project_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def resolve_memory_scope(identity: ConversationIdentity) -> MemoryScope | None:
    """解析聊天的长期记忆作用域；项目为空的日常聊天返回 None。

    只使用聊天自身持久化的 ``character_card_id`` 与权威搭档配置的
    ``assistant.id``：角色卡被删除时仍解析为 ``card:<id>``，绝不静默并入
    内置角色（契约 §1）。
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
        raise MemoryError(str(exc), code=MEMORY_INVALID) from exc


class PairMemory(FrozenModel):
    """一条配对级长期记忆（契约 §2；与 TS ``PairMemory`` 同形）。"""

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
        # 契约 §2：内容由模型负责，代码只验证"是 JSON 对象"这一结构事实。
        if not isinstance(value, Mapping):
            raise ValueError("记忆内容必须是 JSON 对象")
        return dict(value)


def active_memories(memories: Iterable[PairMemory]) -> tuple[PairMemory, ...]:
    """只返回 active 记录（deleted 不参与装配，但保留在库中）。"""
    return tuple(memory for memory in memories if memory.status == "active")


def require_same_scope(expected: MemoryScope, actual: MemoryScope) -> None:
    """读写作用域必须与解析出的权威作用域一致（契约 §1）。"""
    if expected.scope_key != actual.scope_key:
        raise MemoryError(
            "记忆作用域不匹配："
            f"期望 {expected.scope_key}，实际 {actual.scope_key}",
            code=MEMORY_SCOPE_MISMATCH,
        )


def require_memory_found(memory: PairMemory | None, memory_id: str) -> PairMemory:
    """按 id 取记忆时找不到即真实失败，不返回空记录。"""
    if memory is None:
        raise MemoryError(f"记忆不存在：{memory_id}", code=MEMORY_NOT_FOUND)
    return memory


def memory_event_payload(memory: PairMemory, *, conversation_id: str | None = None) -> dict:
    """``memory.updated``/``memory.deleted`` 事件载荷（契约 §2）。

    事件携带 account/project/conversation/pair/character_ref/assistant_identity
    与记录 id；不携带隐藏提示内容。
    """
    payload: dict = {
        "memory_id": memory.memory_id,
        "account_id": memory.scope.account_id,
        "project_id": memory.scope.project_id,
        "pair_id": memory.scope.pair_id,
        "character_ref": memory.scope.character_ref,
        "assistant_identity": memory.scope.assistant_identity,
        "status": memory.status,
        "updated_at": memory.updated_at,
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return payload
