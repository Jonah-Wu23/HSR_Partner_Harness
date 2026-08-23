"""角色卡持久化仓库（CharacterCardRepository）测试（V0.3.3 强逻辑 AI 轨道，成员 A）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pair_harness.character_cards import (
    AvatarAsset,
    CharacterCard,
    HsrExtension,
    VoiceProfile,
    load_card_json,
)
from pair_harness.character_cards.repository import (
    CardRecord,
    CharacterCardRepository,
)
from pair_harness.storage.sqlite_store import SCHEMA_VERSION, SQLiteStore


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[CharacterCardRepository, SQLiteStore]:
    store = SQLiteStore(tmp_path / "data" / "pair_harness.db")
    yield CharacterCardRepository(store), store
    store.close()


def _make_card(name: str = "测试角色") -> CharacterCard:
    card = CharacterCard(name=name)
    card.description = "第一版描述"
    return card


def _set_state(repository: CharacterCardRepository, card_id: str, state: str) -> None:
    """测试辅助：直接把生命周期状态写库，绕过 draft 拦截。"""
    repository.connection.execute(
        "UPDATE character_cards SET state = ? WHERE card_id = ?", (state, card_id)
    )
    repository.connection.commit()


# ---------------------------------------------------------------- 全路径


def test_full_lifecycle_create_update_duplicate_archive_select(repo) -> None:
    repository, _ = repo

    # 创建草稿
    draft = repository.create_draft(name="塔提亚")
    assert isinstance(draft, CardRecord)
    assert draft.state == "draft"
    assert draft.source == "user_created"
    assert draft.card.name == "塔提亚"

    # 更新内容（state 保持 draft）
    card = _make_card(name="塔提亚")
    card.description = "更新后的描述"
    updated = repository.update_card(draft.card_id, card)
    assert updated.card.description == "更新后的描述"
    assert updated.card.name == "塔提亚"
    assert updated.state == "draft"

    # 复制
    duplicate = repository.duplicate_card(draft.card_id)
    assert duplicate.card_id != draft.card_id
    assert duplicate.card.name == "塔提亚（副本）"
    assert duplicate.state == draft.state
    assert duplicate.source == draft.source

    # 归档草稿应拒绝
    with pytest.raises(ValueError):
        repository.archive_card(draft.card_id)

    # 置为 saved 后归档（state 保持原值）
    _set_state(repository, duplicate.card_id, "saved")
    archived = repository.archive_card(duplicate.card_id)
    assert archived.state == "saved"
    assert archived.card_id in repository._archived_ids()

    # 选择使用 + 读取
    repository.select_active(draft.card_id)
    assert repository.get_active_card_id() == draft.card_id

    # 已归档卡不允许被选中
    with pytest.raises(ValueError):
        repository.select_active(duplicate.card_id)

    # list 过滤
    summaries = repository.list_cards()
    ids_only = {s.card_id for s in summaries}
    assert draft.card_id in ids_only  # 未归档仍可见
    assert duplicate.card_id not in ids_only  # 已归档默认过滤
    all_summaries = repository.list_cards(include_archived=True)
    assert duplicate.card_id in {s.card_id for s in all_summaries}


def test_has_avatar_and_voice_state_in_summary(repo) -> None:
    repository, _ = repo
    draft = repository.create_draft(name="无头像")

    # 无 hsr：无头像、voice_unconfigured
    summary = next(s for s in repository.list_cards() if s.card_id == draft.card_id)
    assert summary.has_avatar is False
    assert summary.voice_state == "voice_unconfigured"

    # 带头像与音色
    card = _make_card(name="有头像")
    card.hsr = HsrExtension(
        avatar_asset=AvatarAsset(asset_id="asset-1"),
        voice_profile=VoiceProfile(state="voice_creating", voice_id="vid-1"),
    )
    repository.update_card(draft.card_id, card)
    summary = next(s for s in repository.list_cards() if s.card_id == draft.card_id)
    assert summary.has_avatar is True
    assert summary.voice_state == "voice_creating"


def test_delete_requires_confirm(repo) -> None:
    repository, _ = repo
    draft = repository.create_draft(name="要删的卡")
    with pytest.raises(ValueError, match="删除需要确认"):
        repository.delete_card(draft.card_id)

    # 置为 saved 并归档，确认删除后行与归档引用一起消失
    _set_state(repository, draft.card_id, "saved")
    repository.archive_card(draft.card_id)
    assert draft.card_id in repository._archived_ids()
    repository.delete_card(draft.card_id, confirm=True)
    assert draft.card_id not in repository._archived_ids()
    with pytest.raises(KeyError):
        repository.get_card(draft.card_id)


def test_get_card_missing_raises_keyerror(repo) -> None:
    repository, _ = repo
    with pytest.raises(KeyError):
        repository.get_card("no-such-card")


def test_update_card_missing_raises_keyerror(repo) -> None:
    repository, _ = repo
    with pytest.raises(KeyError):
        repository.update_card("no-such-card", _make_card())


def test_active_default_is_none(repo) -> None:
    repository, _ = repo
    assert repository.get_active_card_id() is None


# ---------------------------------------------------------------- 未知扩展往返


def test_unknown_extension_round_trip_preserved(repo) -> None:
    repository, _ = repo
    draft = repository.create_draft(name="扩展保留")

    card = _make_card(name="扩展保留")
    card.extensions["vendor_custom_3px"] = {
        "nested": {"a": [1, 2, {"x": None}]},
        "flag": True,
    }
    card.hsr = HsrExtension()
    card.hsr.extras["future_hsr_field"] = {"future": "value"}
    card.data_extras["data_future_field"] = {"df": 1}
    repository.update_card(draft.card_id, card)

    # 直接读库里的 card_json，走 load_card_json 往返
    row = repository.connection.execute(
        "SELECT card_json FROM character_cards WHERE card_id = ?", (draft.card_id,)
    ).fetchone()
    parsed = load_card_json(row["card_json"]).card
    assert parsed.extensions["vendor_custom_3px"] == {
        "nested": {"a": [1, 2, {"x": None}]},
        "flag": True,
    }
    assert parsed.hsr.extras["future_hsr_field"] == {"future": "value"}
    assert parsed.data_extras["data_future_field"] == {"df": 1}

    # 重新 get 再对比
    fetched = repository.get_card(draft.card_id)
    assert fetched.card.extensions["vendor_custom_3px"]["nested"] == {
        "a": [1, 2, {"x": None}]
    }
    assert fetched.card.hsr.extras["future_hsr_field"] == {"future": "value"}
    assert fetched.card.data_extras["data_future_field"] == {"df": 1}


# ---------------------------------------------------------------- 旧库升级


def test_legacy_db_upgrade_rebuilds_card_tables_and_preserves_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.db"

    # 建库并写入既有数据（projects / conversations / app_state）
    with SQLiteStore(database) as store:
        project = store.create_project(name="旧项目", root_path=str(tmp_path))
        conversation = store.create_conversation(
            project_id=project.project_id, pair_id="pair_a", title="旧聊天"
        )
        store.set_app_state("login", "u1")
        assert (
            store.connection.execute("PRAGMA user_version").fetchone()[0]
            == SCHEMA_VERSION
        )
        # 回退到 v8 并 DROP 新表，模拟 v8 旧库
        store.connection.execute("PRAGMA user_version = 8")
        store.connection.executescript(
            "DROP TABLE IF EXISTS character_cards;"
            "DROP TABLE IF EXISTS character_assets;"
        )
        store.connection.commit()
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 8

    # 重开：应迁移到 SCHEMA_VERSION 并重建表
    with SQLiteStore(database) as migrated:
        assert (
            migrated.connection.execute("PRAGMA user_version").fetchone()[0]
            == SCHEMA_VERSION
        )
        # 新表已重建并可写
        repository = CharacterCardRepository(migrated)
        draft = repository.create_draft(name="升级后的草稿")
        loaded = repository.get_card(draft.card_id)
        assert loaded.card.name == "升级后的草稿"
        # 既有数据完整
        p = migrated.get_project(project.project_id)
        assert p.name == "旧项目"
        c = migrated.get_conversation(conversation.conversation_id)
        assert c.project_id == project.project_id
        assert migrated.get_app_state("login") == "u1"


# ---------------------------------------------------------------- 新库直建


def test_fresh_db_has_card_tables(repo) -> None:
    repository, store = repo
    tables = {
        row[0]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "character_cards" in tables
    assert "character_assets" in tables


# ---------------------------------------------------------------- 导入（V0.3.5 §2.2）


def test_import_card_default(repo) -> None:
    repository, _ = repo
    card = _make_card(name="白厄")
    card.description = "导入的描述"

    record = repository.import_card(card)
    assert isinstance(record, CardRecord)
    assert record.state == "imported"
    assert record.source == "tavern_import"
    assert record.card.name == "白厄"
    assert record.card.description == "导入的描述"
    # 传入对象未被修改
    assert card.name == "白厄"
    # 库内行与返回值一致
    row = repository.connection.execute(
        "SELECT state, source, name FROM character_cards WHERE card_id = ?",
        (record.card_id,),
    ).fetchone()
    assert row["state"] == "imported"
    assert row["source"] == "tavern_import"
    assert row["name"] == "白厄"


def test_import_card_as_duplicate(repo) -> None:
    repository, _ = repo
    card = _make_card(name="白厄")

    record = repository.import_card(card, as_duplicate=True)
    assert record.state == "imported"
    assert record.source == "tavern_import"
    assert record.card.name == "白厄（副本）"
    # 传入对象未被修改
    assert card.name == "白厄"

    # 同源卡默认导入与副本导入各得新 card_id，名称互不影响
    first = repository.import_card(card)
    assert first.card_id != record.card_id
    assert first.card.name == "白厄"