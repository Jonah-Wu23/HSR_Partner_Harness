from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from pair_harness.character_cards.codec import dump_card_v3
from pair_harness.character_cards.models import CharacterCard
from pair_harness.character_cards.repository import CharacterCardRepository
from pair_harness.config.pairs import PAIR_CATALOG_IDS, list_pair_configs
from pair_harness.partner_catalog import PartnerBindingRepository
from pair_harness.storage.sqlite_store import SQLiteStore
from tests.fixtures.legacy_database import create_legacy_database

ROOT = Path(__file__).resolve().parents[2]
CARD_JSON = ROOT / "tests" / "fixtures" / "character_cards" / "白厄（3.4前）.json"
CARD_PNG = ROOT / "tests" / "fixtures" / "character_cards" / "白厄（3.4前）.png"
# 角色库样例冻结界面要覆盖的状态组合；card-01 与 JSON fixture 是同一角色。
LIBRARY_SAMPLE = ROOT / "docs" / "character-card" / "samples" / "角色库样例.json"
DEFAULT_PAIR_ID = "phainon_ancient_machine"
IO_TIMEOUT_S = 20.0
_CATALOG_ITEM_KEYS = {
    "binding_id",
    "pair_id",
    "character_card_id",
    "source",
    "character",
    "assistant",
    "theme",
}


def _library_card(card_id: str) -> dict[str, Any]:
    sample = json.loads(LIBRARY_SAMPLE.read_text(encoding="utf-8"))
    return next(card for card in sample["cards"] if card["id"] == card_id)


def _card_json_payload() -> dict[str, Any]:
    return json.loads(CARD_JSON.read_text(encoding="utf-8"))


def _pairs_by_id() -> dict[str, Any]:
    return {pair.pair_id: pair for pair in list_pair_configs()}


def _conversation_ids(snapshot: dict[str, Any]) -> set[str]:
    return {
        conversation["conversation_id"]
        for project in snapshot["projects"]
        for conversation in project["conversations"]
    }


def _project_conversations(snapshot: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    project = next(item for item in snapshot["projects"] if item["project_id"] == project_id)
    return project["conversations"]


def _catalog_item(snapshot: dict[str, Any], card_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in snapshot["pairs"] if item["character_card_id"] == card_id),
        None,
    )


class SidecarLoop:
    """真实 Sidecar 子进程的 JSONL 环路：请求读响应，途经事件按到达顺序留存。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.data_dir = tmp_path / "data"
        self.events: list[dict[str, Any]] = []
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_file: Any = None
        self._counter = 0
        self._stderr_path = tmp_path / "sidecar.stderr.log"

    async def start(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        self._stderr_file = self._stderr_path.open("ab")
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pair_harness.desktop_backend",
            "--demo",
            "--project",
            str(self.tmp_path),
            "--data-dir",
            str(self.data_dir),
            cwd=ROOT,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self._stderr_file,
            # card.avatar 的 base64 头像超过默认 64KiB 行上限。
            limit=8 * 1024 * 1024,
        )
        while True:
            message = await self._read()
            if message["kind"] != "event":
                raise AssertionError(f"Sidecar 启动未收到 backend.ready：{message}")
            if message["event"] == "backend.ready":
                assert message["payload"]["demo"] is True, message
                return
            self.events.append(message)

    async def _read(self) -> dict[str, Any]:
        process = self._process
        assert process is not None and process.stdout is not None
        line = await asyncio.wait_for(process.stdout.readline(), timeout=IO_TIMEOUT_S)
        if not line:
            raise AssertionError(f"Sidecar 提前退出：{self.stderr_text()}")
        return json.loads(line.decode("utf-8"))

    async def request(self, method: str, *, ok: bool = True, **params: Any) -> Any:
        process = self._process
        assert process is not None and process.stdin is not None
        self._counter += 1
        request_id = f"{self._counter}-{method}"
        frame = {"kind": "request", "id": request_id, "method": method, "params": params}
        process.stdin.write((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))
        await process.stdin.drain()
        while True:
            message = await self._read()
            if message["kind"] == "event":
                self.events.append(message)
                continue
            assert message["kind"] == "response", message
            assert message["id"] == request_id, message
            if not ok:
                assert message["ok"] is False, message
                return message["error"]
            assert message["ok"] is True, message
            return message["result"]

    def payloads(self, event: str) -> list[dict[str, Any]]:
        return [item["payload"] for item in self.events if item["event"] == event]

    def clear_events(self) -> None:
        self.events.clear()

    def stderr_text(self) -> str:
        if not self._stderr_path.exists():
            return ""
        return self._stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]

    async def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            await self.request("app.shutdown")
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        assert process.returncode == 0, self.stderr_text()
        self._stderr_file.close()
        self._process = None


@pytest.mark.asyncio
async def test_json_import_enters_catalog_and_drives_conversation(tmp_path: Path) -> None:
    """卡经 peek/import 入目录，绑定建会话，开场白与装配来源全部真实。"""
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        baseline = await loop.request("app.bootstrap")
        assert [item["pair_id"] for item in baseline["pairs"]] == list(PAIR_CATALOG_IDS)
        assert baseline["catalog_version"] == 0

        # card.peek_import 只预检，不写库。
        preview = (await loop.request("card.peek_import", path=str(CARD_JSON)))["preview"]
        library_card = _library_card("card-01")
        assert preview["name"] == library_card["name"] == "白厄（3.4前）"
        assert preview["format"] == "json"
        untouched = await loop.request("pair.list")
        assert untouched["catalog_version"] == baseline["catalog_version"]
        assert len(untouched["pairs"]) == len(PAIR_CATALOG_IDS)

        imported = await loop.request("card.import_json", path=str(CARD_JSON))
        card_id = imported["card_id"]
        assert imported["name"] == library_card["name"]
        assert imported["state"] == library_card["state"] == "imported"

        card_events = loop.payloads("card.updated")
        pair_events = loop.payloads("pair.updated")
        assert len(card_events) == 1 and len(pair_events) == 1
        assert card_events[0]["card_id"] == card_id
        version = card_events[0]["catalog_version"]
        assert pair_events[0]["catalog_version"] == version
        assert version > baseline["catalog_version"]

        listing = await loop.request("pair.list")
        assert listing["catalog_version"] == version
        option = _catalog_item(listing, card_id)
        assert option is not None
        fetched = await loop.request("card.get", card_id=card_id)
        assert set(option) == _CATALOG_ITEM_KEYS
        assert option["source"] == "card"
        assert option["pair_id"] == DEFAULT_PAIR_ID
        assert option["character"] == {
            "id": card_id,
            "name": library_card["name"],
            "voice_id": "",
            "avatar_ref": None,
            "avatar_version": fetched["updated_at"],
            "missing": False,
        }
        expected_assistant = _pairs_by_id()[DEFAULT_PAIR_ID].assistant
        assert option["assistant"] == {
            "id": expected_assistant.id,
            "name": expected_assistant.name,
            "voice_id": expected_assistant.voice_id,
        }
        assert option["binding_id"] != f"builtin:{DEFAULT_PAIR_ID}"

        # 快照与 pair.list 同源：目录项与目录版本一致。
        snapshot = await loop.request("app.bootstrap")
        assert snapshot["catalog_version"] == listing["catalog_version"]
        assert _catalog_item(snapshot, card_id) == option

        created = await loop.request("conversation.create", binding_id=option["binding_id"])
        assert created["reused"] is False
        conversation = created["current_conversation"]
        assert conversation["binding_id"] == option["binding_id"]
        assert conversation["character_card_id"] == card_id
        assert conversation["pair_id"] == DEFAULT_PAIR_ID
        assert conversation["character_identity"] == {
            "name": library_card["name"],
            "avatar_ref": None,
            "avatar_version": fetched["updated_at"],
            "missing": False,
            "source": "card",
        }
        expected_greeting = _card_json_payload()["data"]["first_mes"].strip()
        greetings = [
            message for message in created["messages"] if message["source"] == "character"
        ]
        assert [message["text"] for message in greetings] == [expected_greeting]

        # 装配诊断与对话走同一入口，来源标明绑定卡。
        assembly = await loop.request(
            "diagnostics.prompt_assembly",
            conversation_id=conversation["conversation_id"],
            include_hidden=True,
        )
        assert assembly["source"] == "card"
        assert assembly["reason"] is None
        hidden = {module["name"]: module["hidden_content"] for module in assembly["modules"]}
        assert hidden.get("角色设定") == _card_json_payload()["data"]["description"]

        # reuse_active=true 复用同绑定的活跃会话，不重复插开场白。
        reused = await loop.request(
            "conversation.create",
            binding_id=option["binding_id"],
            reuse_active=True,
        )
        assert reused["reused"] is True
        assert reused["current_conversation_id"] == conversation["conversation_id"]
        assert [message["message_id"] for message in reused["messages"]] == [
            message["message_id"] for message in created["messages"]
        ]
        bound_conversations = [
            item
            for item in _project_conversations(reused, reused["current_project_id"])
            if item["binding_id"] == option["binding_id"]
        ]
        assert [item["conversation_id"] for item in bound_conversations] == [
            conversation["conversation_id"]
        ]
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_draft_publish_enters_catalog_and_greets_from_first_mes(tmp_path: Path) -> None:
    """草稿不入目录；发布后自动绑定入目录，开场白来自卡 first_mes。"""
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        draft = await loop.request("card.create_draft", name="草稿搭档")
        card_id = draft["card_id"]
        assert draft["state"] == "draft"

        before = await loop.request("pair.list")
        assert _catalog_item(before, card_id) is None
        assert len(before["pairs"]) == len(PAIR_CATALOG_IDS)

        first_mes = "第一条消息，来自卡。"
        updated = await loop.request(
            "card.update",
            card_id=card_id,
            card={
                "name": "草稿搭档",
                "description": "草稿转正的设定。",
                "first_mes": first_mes,
            },
        )
        assert updated["card_id"] == card_id
        published = await loop.request("card.publish", card_id=card_id)
        assert published["state"] == "saved"

        assert len(loop.payloads("pair.updated")) == 1
        version = loop.payloads("pair.updated")[0]["catalog_version"]
        assert loop.payloads("card.updated") == [
            {"card_id": card_id, "catalog_version": version}
        ]
        listing = await loop.request("pair.list")
        assert listing["catalog_version"] == version
        option = _catalog_item(listing, card_id)
        assert option is not None
        assert option["source"] == "card"
        assert option["binding_id"] != f"builtin:{DEFAULT_PAIR_ID}"

        created = await loop.request("conversation.create", binding_id=option["binding_id"])
        assert created["current_conversation"]["character_card_id"] == card_id
        assert [
            message["text"]
            for message in created["messages"]
            if message["source"] == "character"
        ] == [first_mes]
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_png_import_exposes_avatar_asset_in_catalog(tmp_path: Path) -> None:
    """PNG 卡导入后目录项带头像引用与版本，card.avatar 取回原始 PNG。"""
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        baseline = await loop.request("pair.list")
        preview = (await loop.request("card.peek_import", path=str(CARD_PNG)))["preview"]
        library_card = _library_card("card-01")
        assert preview["name"] == library_card["name"]
        assert preview["format"] == "png"
        assert preview["avatar_available"] is True

        imported = await loop.request("card.import_png", path=str(CARD_PNG))
        assert len(loop.payloads("pair.updated")) == 1
        version = loop.payloads("pair.updated")[0]["catalog_version"]
        assert version > baseline["catalog_version"]
        listing = await loop.request("pair.list")
        assert listing["catalog_version"] == version
        option = _catalog_item(listing, imported["card_id"])
        assert option is not None
        fetched = await loop.request("card.get", card_id=imported["card_id"])
        assert option["character"]["avatar_ref"]
        assert option["character"]["avatar_version"] == fetched["updated_at"]
        assert option["character"]["name"] == library_card["name"]

        avatar = await loop.request("card.avatar", card_id=imported["card_id"])
        assert avatar["avatar"]["mime_type"] == "image/png"
        assert base64.b64decode(avatar["avatar"]["data_base64"]) == CARD_PNG.read_bytes()
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_archive_restore_delete_sync_catalog_and_open_identity(tmp_path: Path) -> None:
    """归档/恢复同步目录并各发一次 pair.updated；删除后 open 标记身份缺失。"""
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        imported = await loop.request("card.import_json", path=str(CARD_JSON))
        card_id = imported["card_id"]
        listing = await loop.request("pair.list")
        binding_id = _catalog_item(listing, card_id)["binding_id"]
        created = await loop.request("conversation.create", binding_id=binding_id)
        conversation_id = created["current_conversation_id"]

        loop.clear_events()
        await loop.request("card.archive", card_id=card_id)
        archived_version = loop.payloads("pair.updated")[0]["catalog_version"]
        assert loop.payloads("card.updated") == []
        archived = await loop.request("pair.list")
        assert archived["catalog_version"] == archived_version
        assert _catalog_item(archived, card_id) is None
        snapshot = await loop.request("app.bootstrap")
        assert _catalog_item(snapshot, card_id) is None

        loop.clear_events()
        await loop.request("card.unarchive", card_id=card_id)
        restored_version = loop.payloads("pair.updated")[0]["catalog_version"]
        assert restored_version > archived_version
        restored = await loop.request("pair.list")
        assert restored["catalog_version"] == restored_version
        assert _catalog_item(restored, card_id) is not None

        loop.clear_events()
        await loop.request("card.delete", card_id=card_id, confirm=True)
        deleted_version = loop.payloads("pair.updated")[0]["catalog_version"]
        assert deleted_version > restored_version
        after_delete = await loop.request("pair.list")
        assert _catalog_item(after_delete, card_id) is None

        opened = await loop.request("conversation.open", conversation_id=conversation_id)
        assert opened["conversation"]["character_identity"] == {
            "name": "",
            "avatar_ref": None,
            "avatar_version": None,
            "missing": True,
            "source": "card",
        }
        assert opened["conversation"]["character_card_id"] == card_id
        missing_events = loop.payloads("conversation.card_missing")
        assert [event["card_id"] for event in missing_events] == [card_id]
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_card_rename_and_avatar_sync_catalog_entry(tmp_path: Path) -> None:
    """改名与换头像各推进目录版本，目录项实时反映新名字与头像。"""
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        draft = await loop.request("card.create_draft", name="初名搭档")
        card_id = draft["card_id"]
        await loop.request(
            "card.update",
            card_id=card_id,
            card={"name": "初名搭档", "description": "设定", "first_mes": "你好"},
        )
        await loop.request("card.publish", card_id=card_id)
        loop.clear_events()

        await loop.request(
            "card.update",
            card_id=card_id,
            card={"name": "改名后的搭档", "description": "设定", "first_mes": "你好"},
        )
        rename_version = loop.payloads("card.updated")[0]["catalog_version"]
        assert loop.payloads("pair.updated") == []
        renamed = await loop.request("pair.list")
        assert renamed["catalog_version"] == rename_version
        assert _catalog_item(renamed, card_id)["character"]["name"] == "改名后的搭档"

        loop.clear_events()
        await loop.request("card.set_avatar", card_id=card_id, path=str(CARD_PNG))
        avatar_version = loop.payloads("card.updated")[0]["catalog_version"]
        assert avatar_version > rename_version
        with_avatar = await loop.request("pair.list")
        assert with_avatar["catalog_version"] == avatar_version
        option = _catalog_item(with_avatar, card_id)
        fetched = await loop.request("card.get", card_id=card_id)
        assert option["character"]["avatar_ref"]
        assert option["character"]["avatar_version"] == fetched["updated_at"]
        avatar = await loop.request("card.avatar", card_id=card_id)
        assert base64.b64decode(avatar["avatar"]["data_base64"]) == CARD_PNG.read_bytes()
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_illegal_identity_create_fails_without_conversation_record(tmp_path: Path) -> None:
    """草稿无绑定、已归档卡失效、绑定不存在：建会话失败且不落任何会话记录。"""
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        draft = await loop.request("card.create_draft", name="未发布草稿")
        draft_id = draft["card_id"]
        imported = await loop.request("card.import_json", path=str(CARD_JSON))
        card_id = imported["card_id"]
        listing = await loop.request("pair.list")
        binding_id = _catalog_item(listing, card_id)["binding_id"]
        await loop.request("card.archive", card_id=card_id)

        before = _conversation_ids(await loop.request("app.bootstrap"))
        before_version = (await loop.request("pair.list"))["catalog_version"]

        draft_error = await loop.request(
            "conversation.create", character_card_id=draft_id, ok=False
        )
        assert draft_error["code"] == "binding_not_found"
        archived_error = await loop.request(
            "conversation.create", binding_id=binding_id, ok=False
        )
        assert archived_error["code"] == "card_invalid_state"
        unknown_error = await loop.request(
            "conversation.create", binding_id="no-such-binding", ok=False
        )
        assert unknown_error["code"] == "binding_not_found"

        after = await loop.request("app.bootstrap")
        assert _conversation_ids(after) == before
        assert after["catalog_version"] == before_version
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_builtin_binding_creates_each_assistant(tmp_path: Path) -> None:
    """不带 binding_id 的创建解析为 builtin:<pair_id>，三个内置搭档逐项一致。"""
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        default_created = await loop.request("conversation.create")
        default_conversation = default_created["current_conversation"]
        assert default_conversation["binding_id"] == f"builtin:{DEFAULT_PAIR_ID}"
        assert default_conversation["character_card_id"] is None
        assert default_conversation["pair_id"] == DEFAULT_PAIR_ID
        assert default_created["pair"]["pair_id"] == DEFAULT_PAIR_ID

        pairs = _pairs_by_id()
        for pair_id in PAIR_CATALOG_IDS:
            created = await loop.request("conversation.create", pair_id=pair_id)
            conversation = created["current_conversation"]
            assert conversation["binding_id"] == f"builtin:{pair_id}"
            assert conversation["character_card_id"] is None
            assert conversation["pair_id"] == pair_id
            assert created["pair"]["pair_id"] == pair_id
            assert created["pair"]["character"]["name"] == pairs[pair_id].character.name
            assert created["pair"]["assistant"]["name"] == pairs[pair_id].assistant.name
            assert conversation["character_identity"] == {
                "name": pairs[pair_id].character.name,
                "avatar_ref": None,
                "avatar_version": None,
                "missing": False,
                "source": "builtin",
            }
    finally:
        await loop.stop()


def _insert_legacy_project(connection) -> None:
    connection.execute(
        "INSERT INTO projects(project_id, account_id, name, root_path, created_at, "
        "last_opened_at) VALUES ('p', 'default-local', '迁移项目', 'C:/legacy', ?, ?)",
        ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )


def _insert_legacy_card(connection, card_id: str, *, state: str, card_json: str) -> None:
    now = "2026-01-01T00:00:00+00:00"
    connection.execute(
        "INSERT INTO character_cards(card_id, state, name, source, card_json, "
        "created_at, updated_at) VALUES (?, ?, ?, 'tavern_import', ?, ?, ?)",
        (card_id, state, card_id, card_json, now, now),
    )


def _insert_legacy_conversation(
    connection, conversation_id: str, *, card_id: str | None
) -> None:
    now = "2026-01-01T00:00:00+00:00"
    if card_id is None:
        connection.execute(
            "INSERT INTO conversations(conversation_id, project_id, account_id, pair_id, "
            "title, created_at, updated_at) VALUES (?, 'p', 'default-local', ?, '旧聊天', ?, ?)",
            (conversation_id, DEFAULT_PAIR_ID, now, now),
        )
        return
    connection.execute(
        "INSERT INTO conversations(conversation_id, project_id, account_id, pair_id, "
        "title, created_at, updated_at, character_card_id) "
        "VALUES (?, 'p', 'default-local', ?, '旧聊天', ?, ?, ?)",
        (conversation_id, DEFAULT_PAIR_ID, now, now, card_id),
    )


async def _verify_migrated_restart(tmp_path: Path, card_id: str) -> None:
    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        listing = await loop.request("pair.list")
        assert listing["catalog_version"] == 0
        option = _catalog_item(listing, card_id)
        assert option is not None
        assert option["binding_id"] == f"card:{card_id}"
        assert option["source"] == "card"
        assert option["character"]["name"] == "迁移角色"
        assert option["character"]["avatar_version"] == "2026-01-01T00:00:00+00:00"
        assert _catalog_item(listing, "card-draft") is None

        snapshot = await loop.request("app.bootstrap")
        assert snapshot["catalog_version"] == 0
        assert _catalog_item(snapshot, card_id) == option
        conversations = {
            item["conversation_id"]: item
            for item in _project_conversations(snapshot, "p")
        }
        assert conversations["c-card"]["binding_id"] == f"card:{card_id}"
        assert conversations["c-builtin"]["binding_id"] == f"builtin:{DEFAULT_PAIR_ID}"
        assert conversations["c-draft"]["binding_id"] is None

        opened = await loop.request("conversation.open", conversation_id="c-card")
        assert opened["conversation"]["character_identity"] == {
            "name": "迁移角色",
            "avatar_ref": None,
            "avatar_version": "2026-01-01T00:00:00+00:00",
            "missing": False,
            "source": "card",
        }
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_migrated_database_restart_keeps_catalog_and_identity(tmp_path: Path) -> None:
    """旧库迁移后重启：既有卡绑定进目录，既有会话身份与绑定回填正确。"""
    database = tmp_path / "data" / "pair_harness.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = create_legacy_database(database, 13)
    _insert_legacy_project(connection)
    card_id = "card-migrated"
    card = CharacterCard(name="迁移角色", description="迁移设定", first_mes="迁移开场白")
    _insert_legacy_card(connection, card_id, state="saved", card_json=dump_card_v3(card))
    _insert_legacy_card(
        connection,
        "card-draft",
        state="draft",
        card_json=dump_card_v3(CharacterCard(name="草稿")),
    )
    _insert_legacy_conversation(connection, "c-card", card_id=card_id)
    _insert_legacy_conversation(connection, "c-builtin", card_id=None)
    _insert_legacy_conversation(connection, "c-draft", card_id="card-draft")
    connection.commit()
    connection.close()

    await _verify_migrated_restart(tmp_path, card_id)
    await _verify_migrated_restart(tmp_path, card_id)


@pytest.mark.asyncio
async def test_draft_card_with_existing_binding_is_rejected(tmp_path: Path) -> None:
    """库中存在草稿卡绑定时，按该 binding 建会话失败为 card_invalid_state 且不留记录。"""
    database = tmp_path / "data" / "pair_harness.db"
    store = SQLiteStore(database)
    cards = CharacterCardRepository(store)
    bindings = PartnerBindingRepository(store)
    draft = cards.create_draft(name="库内草稿")
    binding = bindings.create_binding(draft.card_id, DEFAULT_PAIR_ID)
    store.connection.commit()
    store.close()

    loop = SidecarLoop(tmp_path)
    await loop.start()
    try:
        before = _conversation_ids(await loop.request("app.bootstrap"))
        error = await loop.request("conversation.create", binding_id=binding.binding_id, ok=False)
        assert error["code"] == "card_invalid_state"
        after = await loop.request("app.bootstrap")
        assert _conversation_ids(after) == before
        assert _catalog_item(after, draft.card_id) is None
    finally:
        await loop.stop()
