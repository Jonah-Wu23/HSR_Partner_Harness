# 搭档绑定：binding_id 是用户选择的搭档身份，base_pair_id 指向 YAML 搭档配置。
# 写方法不提交事务，由调用方统一提交，使「卡落库 + 绑定创建 + 目录版本递增」
# 能落在同一个事务里；只读方法不写库。

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from pair_harness.storage.sqlite_store import SQLiteStore

# app_state 键：搭档目录版本。不存在视为 0，每次绑定变化由调用方 +1。
CATALOG_VERSION_KEY = "partner_catalog.version"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PartnerBinding:
    """一条搭档绑定；character_card_id 为 None 表示内置角色。"""

    binding_id: str
    character_card_id: str | None
    base_pair_id: str
    enabled: bool
    created_at: str
    updated_at: str

    @property
    def source(self) -> str:
        return "builtin" if self.character_card_id is None else "card"


class PartnerBindingRepository:
    """partner_bindings 持久化仓库，复用 ``store.connection``。"""

    def __init__(self, store: SQLiteStore) -> None:
        self.connection = store.connection

    # ---------------------------------------------------------------- 写入

    def create_binding(
        self, character_card_id: str | None, base_pair_id: str
    ) -> PartnerBinding:
        """创建绑定；同一 (character_card_id, base_pair_id) 已存在时返回既有记录。

        幂等，导入与发布重复触发不会产生第二行。内置绑定的 binding_id 固定为
        ``builtin:<base_pair_id>``。不提交事务。
        """
        existing = self.find_binding(character_card_id, base_pair_id)
        if existing is not None:
            return existing
        binding_id = (
            f"builtin:{base_pair_id}" if character_card_id is None else uuid4().hex
        )
        now = _now()
        self.connection.execute(
            "INSERT INTO partner_bindings("
            "binding_id, character_card_id, base_pair_id, enabled, created_at, updated_at"
            ") VALUES (?, ?, ?, 1, ?, ?) ON CONFLICT DO NOTHING",
            (binding_id, character_card_id, base_pair_id, now, now),
        )
        record = self.find_binding(character_card_id, base_pair_id)
        if record is None:
            raise RuntimeError(
                f"搭档绑定写入后读不到：{character_card_id!r} / {base_pair_id!r}"
            )
        return record

    def set_enabled(self, binding_id: str, enabled: bool) -> PartnerBinding:
        """启用或停用一条绑定；绑定不存在抛 KeyError。不提交事务。"""
        cursor = self.connection.execute(
            "UPDATE partner_bindings SET enabled = ?, updated_at = ? WHERE binding_id = ?",
            (1 if enabled else 0, _now(), binding_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown binding_id: {binding_id}")
        return self.get_binding(binding_id)

    def update_base_pair(self, binding_id: str, base_pair_id: str) -> PartnerBinding:
        """换绑到另一个内置搭档（配对配置改助手）；同一张卡已绑该搭档时由唯一索引拒绝。"""
        cursor = self.connection.execute(
            "UPDATE partner_bindings SET base_pair_id = ?, updated_at = ? "
            "WHERE binding_id = ?",
            (base_pair_id, _now(), binding_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown binding_id: {binding_id}")
        return self.get_binding(binding_id)

    def bump_catalog_version(self) -> int:
        """目录版本 +1 并返回新值；不提交事务，由调用方与绑定变更一起提交。"""
        version = self.catalog_version() + 1
        self.connection.execute(
            "INSERT INTO app_state(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (CATALOG_VERSION_KEY, str(version)),
        )
        return version

    # ---------------------------------------------------------------- 查询

    def get_binding(self, binding_id: str) -> PartnerBinding:
        row = self.connection.execute(
            "SELECT * FROM partner_bindings WHERE binding_id = ?", (binding_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown binding_id: {binding_id}")
        return self._binding_from_row(row)

    def find_binding(
        self, character_card_id: str | None, base_pair_id: str
    ) -> PartnerBinding | None:
        """按（角色卡, 内置搭档）查绑定；character_card_id 为 None 时匹配内置绑定。"""
        row = self.connection.execute(
            "SELECT * FROM partner_bindings "
            "WHERE character_card_id IS ? AND base_pair_id = ? "
            "ORDER BY created_at, binding_id LIMIT 1",
            (character_card_id, base_pair_id),
        ).fetchone()
        return self._binding_from_row(row) if row is not None else None

    def list_bindings(self, *, include_disabled: bool = False) -> list[PartnerBinding]:
        """按创建顺序列出绑定；默认不含已停用的绑定。"""
        where = "" if include_disabled else " WHERE enabled = 1"
        rows = self.connection.execute(
            f"SELECT * FROM partner_bindings{where} ORDER BY created_at, binding_id"
        ).fetchall()
        return [self._binding_from_row(row) for row in rows]

    def catalog_version(self) -> int:
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key = ?", (CATALOG_VERSION_KEY,)
        ).fetchone()
        if row is None:
            return 0
        return int(row["value"])

    @staticmethod
    def _binding_from_row(row) -> PartnerBinding:
        return PartnerBinding(
            binding_id=row["binding_id"],
            character_card_id=row["character_card_id"],
            base_pair_id=row["base_pair_id"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
