# 角色卡存于 character_cards 表，序列化统一走 codec。生命周期状态存 state 列；
# 归档集合与当前使用的卡存于 app_state，不占用 state 取值。

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pair_harness.character_cards.codec import dump_card_v3, load_card_json
from pair_harness.character_cards.models import CharacterCard, HsrExtension, VoiceProfile
from pair_harness.character_cards.states import CharacterVoiceState
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
        self._insert_card_row(
            card_id=card_id,
            state="draft",
            name=name,
            source="user_created",
            card_json=dump_card_v3(card),
            created_at=now,
            updated_at=now,
        )
        self.connection.commit()
        return self.get_card(card_id)

    def update_card(self, card_id: str, card: CharacterCard) -> CardRecord:
        """以传入卡重新 dump 覆盖 card_json，刷新 updated_at。"""
        cursor = self._update_card_row(
            card_id,
            card_json=dump_card_v3(card),
            name=card.name,
            updated_at=_now(),
        )
        if cursor == 0:
            raise KeyError(card_id)
        self.connection.commit()
        return self.get_card(card_id)

    def update_voice_profile(self, card_id: str, **fields: str) -> CardRecord:
        """只改 ``hsr.voice_profile`` 的指定字段，其余卡内容以库中最新值为准。

        每次调用重读当前卡再写回，音色创建等待期间对卡其他部分的编辑不会
        被旧快照覆盖。未知字段名抛 TypeError。
        """
        card = self.get_card(card_id).card
        if card.hsr is None:
            card.hsr = HsrExtension()
        profile = card.hsr.voice_profile or VoiceProfile()
        card.hsr.voice_profile = replace(profile, **fields, updated_at=_now())
        return self.update_card(card_id, card)

    def import_card(self, card: CharacterCard, *, as_duplicate: bool = False) -> CardRecord:
        """导入一张解析后的卡：state=imported, source=tavern_import，新 card_id。

        ``as_duplicate=True`` 时在副本上给名称追加「（副本）」，不改变传入对象。
        导入文件里的资产引用指向其他设备的资产库，按导出形态落库去掉。
        """
        name = f"{card.name}（副本）" if as_duplicate else card.name
        card_to_store = replace(card, name=name)
        card_id = uuid4().hex
        now = _now()
        self._insert_card_row(
            card_id=card_id,
            state="imported",
            name=name,
            source="tavern_import",
            card_json=dump_card_v3(card_to_store, for_export=True),
            created_at=now,
            updated_at=now,
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
        self._insert_card_row(
            card_id=new_id,
            state=source.state,
            name=card.name,
            source=source.source,
            card_json=dump_card_v3(card),
            created_at=now,
            updated_at=now,
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

    def unarchive_card(self, card_id: str) -> CardRecord:
        """把卡移出归档集合；卡不存在抛 KeyError，未归档的卡原样返回。"""
        record = self.get_card(card_id)
        archived = self._archived_ids()
        if card_id in archived:
            archived.discard(card_id)
            self._store_archived(archived)
            self.connection.commit()
        return record

    def delete_card(self, card_id: str, *, confirm: bool = False) -> None:
        """删除一张卡及其在归档集合中的引用；confirm=False 拒绝且抛出。"""
        if not confirm:
            raise ValueError("删除需要确认")
        self._delete_card_row(card_id)
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

    def publish_card(self, card_id: str) -> CardRecord:
        """完成创建：draft 改为 saved；其他状态原样返回当前记录。"""
        record = self.get_card(card_id)
        if record.state != "draft":
            return record
        self._update_card_row(card_id, state="saved", updated_at=_now())
        self.connection.commit()
        return self.get_card(card_id)

    def is_archived(self, card_id: str) -> bool:
        """卡是否在归档集合。"""
        return card_id in self._archived_ids()

    def get_active_card_id(self) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key = ?", (ACTIVE_KEY,)
        ).fetchone()
        return row["value"] if row is not None else None

    # ---------------------------------------------------------------- 内部

    def _insert_card_row(
        self,
        *,
        card_id: str,
        state: str,
        name: str,
        source: str,
        card_json: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        """插入一行角色卡，不提交事务。

        供需要把「卡落库 + 绑定创建 + 目录版本递增」放进同一事务的调用方
        使用；公开写方法在此之上自行提交。
        """
        self.connection.execute(
            "INSERT INTO character_cards("
            "card_id, state, name, source, card_json, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (card_id, state, name, source, card_json, created_at, updated_at),
        )

    def _update_card_row(
        self,
        card_id: str,
        *,
        card_json: str | None = None,
        name: str | None = None,
        state: str | None = None,
        updated_at: str | None = None,
    ) -> int:
        """按需更新一行角色卡的指定列，不提交事务；返回受影响行数。"""
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("card_json", card_json),
            ("name", name),
            ("state", state),
            ("updated_at", updated_at),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                params.append(value)
        if not assignments:
            return 0
        params.append(card_id)
        cursor = self.connection.execute(
            f"UPDATE character_cards SET {', '.join(assignments)} WHERE card_id = ?",
            tuple(params),
        )
        return cursor.rowcount

    def _delete_card_row(self, card_id: str) -> int:
        """删除一行角色卡，不提交事务；返回受影响行数。"""
        cursor = self.connection.execute(
            "DELETE FROM character_cards WHERE card_id = ?", (card_id,)
        )
        return cursor.rowcount

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
            return CharacterVoiceState.UNCONFIGURED.value
        return hsr.voice_profile.state

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