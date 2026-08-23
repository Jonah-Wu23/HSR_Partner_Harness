"""角色卡持久化仓库（V0.3.3 强逻辑 AI 轨道，成员 A）。

本模块复用 :class:`SQLiteStore` 的同一连接，把所有角色卡读写集中到一张
``character_cards`` 表。序列化只走 :func:`codec.load_card_json` /
:func:`codec.dump_card_v3`，本模块不得重新实现解析、不得二次清洗字段。

生命周期说明：

- 角色卡本体生命周期状态（draft / saved / imported / invalid）存表的 ``state`` 列；
- 归档集合不引入新的状态值，而是用 ``app_state`` 键 ``character_cards.archived``
  （JSON 数组，存已归档 card_id）承载；
- “正在使用”的角色卡用 ``app_state`` 键 ``character_cards.active`` 记录单一值。

真实失败（主键冲突、库损坏、解析失败、不存在的卡）直接抛出，不吞。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from pair_harness.character_cards.codec import dump_card_v3, load_card_json
from pair_harness.character_cards.models import CharacterCard
from pair_harness.storage.sqlite_store import SQLiteStore

# app_state 键：已归档角色卡 id 集合（JSON 数组）。
ARCHIVED_KEY = "character_cards.archived"
# app_state 键：当前使用中的角色卡 id（INSERT OR REPLACE 单值）。
ACTIVE_KEY = "character_cards.active"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CardSummary:
    """角色卡列表展示摘要（不含完整卡内容）。"""

    card_id: str
    name: str
    state: str
    source: str
    updated_at: str
    has_avatar: bool
    voice_state: str
    active: bool


@dataclass(frozen=True)
class CardRecord:
    """一张角色卡完整记录（含解析后的 :class:`CharacterCard`）。"""

    card_id: str
    state: str
    source: str
    created_at: str
    updated_at: str
    card: CharacterCard


class CharacterCardRepository:
    """角色卡持久化仓库，复用 ``store.connection``。"""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.connection = store.connection

    # ---------------------------------------------------------------- 查询

    def list_cards(self, *, include_archived: bool = False) -> list[CardSummary]:
        archived = self._archived_ids()
        active = self.get_active_card_id()
        rows = self.connection.execute(
            "SELECT * FROM character_cards ORDER BY updated_at DESC"
        ).fetchall()
        summaries: list[CardSummary] = []
        for row in rows:
            card_id = row["card_id"]
            if not include_archived and card_id in archived:
                continue
            summaries.append(self._summary_from_row(row, active=card_id == active))
        return summaries

    def get_card(self, card_id: str) -> CardRecord:
        row = self.connection.execute(
            "SELECT * FROM character_cards WHERE card_id = ?", (card_id,)
        ).fetchone()
        if row is None:
            raise KeyError(card_id)
        return self._record_from_row(row)

    # ---------------------------------------------------------------- 写入

    def create_draft(self, name: str) -> CardRecord:
        """新建一张最小草稿（state=draft, source=user_created）。"""
        card_id = uuid4().hex
        card = CharacterCard(name=name)
        now = _now()
        self.connection.execute(
            "INSERT INTO character_cards("
            "card_id, state, name, source, card_json, created_at, updated_at"
            ") VALUES (?, 'draft', ?, 'user_created', ?, ?, ?)",
            (card_id, name, dump_card_v3(card), now, now),
        )
        self.connection.commit()
        return self.get_card(card_id)

    def update_card(self, card_id: str, card: CharacterCard) -> CardRecord:
        """以传入卡重新 dump 覆盖 card_json，刷新 updated_at。"""
        now = _now()
        cursor = self.connection.execute(
            "UPDATE character_cards SET card_json = ?, name = ?, updated_at = ? "
            "WHERE card_id = ?",
            (dump_card_v3(card), card.name, now, card_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(card_id)
        self.connection.commit()
        return self.get_card(card_id)

    def import_card(self, card: CharacterCard, *, as_duplicate: bool = False) -> CardRecord:
        """导入一张解析后的卡：state=imported, source=tavern_import，新 card_id。

        ``as_duplicate=True`` 时名称追加「（副本）」——deepcopy 后修改，
        不改变传入对象。语义与 create_draft/update_card 一致：真实失败直接抛。
        """
        if as_duplicate:
            card_to_store = copy.deepcopy(card)
            card_to_store.name = f"{card_to_store.name}（副本）"
        else:
            card_to_store = card
        card_id = uuid4().hex
        now = _now()
        self.connection.execute(
            "INSERT INTO character_cards("
            "card_id, state, name, source, card_json, created_at, updated_at"
            ") VALUES (?, 'imported', ?, 'tavern_import', ?, ?, ?)",
            (card_id, card_to_store.name, dump_card_v3(card_to_store), now, now),
        )
        self.connection.commit()
        return self.get_card(card_id)

    def duplicate_card(self, card_id: str) -> CardRecord:
        """复制一张卡：新 card_id、名称加后缀（副本），state/source 与源卡一致。"""
        source = self.get_card(card_id)
        new_id = uuid4().hex
        card = copy.deepcopy(source.card)
        card.name = f"{card.name}（副本）"
        now = _now()
        self.connection.execute(
            "INSERT INTO character_cards("
            "card_id, state, name, source, card_json, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id,
                source.state,
                card.name,
                source.source,
                dump_card_v3(card),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.get_card(new_id)

    def archive_card(self, card_id: str) -> CardRecord:
        """归档一张卡：draft 状态拒绝；已归档的保留原名与状态，仅进归档集合。"""
        record = self.get_card(card_id)
        if record.state == "draft":
            raise ValueError("草稿不能归档，请先保存")
        archived = self._archived_ids()
        if card_id not in archived:
            archived.add(card_id)
            self._store_archived(archived)
        self.connection.commit()
        return record

    def delete_card(self, card_id: str, *, confirm: bool = False) -> None:
        """删除一张卡及其在归档集合中的引用；confirm=False 拒绝且抛出。"""
        if not confirm:
            raise ValueError("删除需要确认")
        self.connection.execute("DELETE FROM character_cards WHERE card_id = ?", (card_id,))
        archived = self._archived_ids()
        if card_id in archived:
            archived.discard(card_id)
            self._store_archived(archived)
        self.connection.commit()

    def select_active(self, card_id: str) -> None:
        """将卡片设为当前使用；已归档卡不允许被选中。"""
        if card_id in self._archived_ids():
            raise ValueError(f"已归档角色卡不能设为当前使用: {card_id}")
        self.connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES (?, ?)",
            (ACTIVE_KEY, card_id),
        )
        self.connection.commit()

    def get_active_card_id(self) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key = ?", (ACTIVE_KEY,)
        ).fetchone()
        return row["value"] if row is not None else None

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _has_avatar(card: CharacterCard) -> bool:
        hsr = card.hsr
        if hsr is None or hsr.avatar_asset is None:
            return False
        return bool(hsr.avatar_asset.asset_id)

    @staticmethod
    def _voice_state(card: CharacterCard) -> str:
        hsr = card.hsr
        if hsr is None or hsr.voice_profile is None:
            return "voice_unconfigured"
        return hsr.voice_profile.state or "voice_unconfigured"

    def _summary_from_row(self, row, active: bool) -> CardSummary:
        card = load_card_json(row["card_json"]).card
        return CardSummary(
            card_id=row["card_id"],
            name=row["name"],
            state=row["state"],
            source=row["source"],
            updated_at=row["updated_at"],
            has_avatar=self._has_avatar(card),
            voice_state=self._voice_state(card),
            active=active,
        )

    def _record_from_row(self, row) -> CardRecord:
        return CardRecord(
            card_id=row["card_id"],
            state=row["state"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            card=load_card_json(row["card_json"]).card,
        )

    def _archived_ids(self) -> set[str]:
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key = ?", (ARCHIVED_KEY,)
        ).fetchone()
        if row is None:
            return set()
        payload = json.loads(row["value"])
        return set(payload)

    def _store_archived(self, ids: set[str]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES (?, ?)",
            (ARCHIVED_KEY, json.dumps(sorted(ids), ensure_ascii=False)),
        )