from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pair_harness.core.contracts import (
    EngineSessionRef,
    Message,
    MessageKind,
    MessageSource,
    ToolRun,
)
from pair_harness.storage.records import (
    ConversationSummary,
    MemoryScope,
    PairMemory,
    TurnMetric,
    TurnMetricQuery,
)
from pair_harness.storage.sqlite_store import SQLiteStore


def _seed(store: SQLiteStore, *, conversation_id: str = "c1", project_id: str = "p1") -> str:
    store.create_project(name="Repo", root_path=str(store.database.parent), project_id=project_id)
    store.create_conversation(
        project_id=project_id,
        pair_id="phainon_ancient_machine",
        title="聊天",
        conversation_id=conversation_id,
        account_id="default-local",
    )
    return conversation_id


def _message(conversation_id: str, text: str, *, index: int) -> Message:
    return Message(
        message_id=f"m{index}",
        conversation_id=conversation_id,
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text=text,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
    )


def _metric(
    conversation_id: str,
    *,
    turn_id: str,
    index: int = 0,
    status: str = "completed",
    turn_kind: str = "character_turn",
    **overrides: object,
) -> TurnMetric:
    payload = {
        "account_id": "default-local",
        "project_id": "p1",
        "conversation_id": conversation_id,
        "pair_id": "phainon_ancient_machine",
        "character_ref": "builtin:phainon",
        "assistant_identity": "ancient_machine",
        "turn_kind": turn_kind,
        "turn_id": turn_id,
        "status": status,
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
    }
    payload.update(overrides)
    return TurnMetric(**payload)


def _scope(**overrides: str) -> MemoryScope:
    payload = {
        "account_id": "default-local",
        "project_id": "p1",
        "pair_id": "phainon_ancient_machine",
        "character_ref": "builtin:phainon",
        "assistant_identity": "ancient_machine",
    }
    payload.update(overrides)
    return MemoryScope(**payload)


def test_store_persists_core_records(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "data" / "pair_harness.db")
    project = store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
    conversation = store.create_conversation(
        project_id=project.project_id,
        pair_id="phainon_ancient_machine",
        title="First",
        conversation_id="c",
    )
    message = Message(
        conversation_id=conversation.conversation_id,
        pair_id=conversation.pair_id,
        source=MessageSource.ASSISTANT,
        kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
        text="完成",
        payload={"reasoning": "先核对结果。"},
        tts_eligible=True,
    )
    tool_run = ToolRun(
        tool_call_id="tool",
        conversation_id="c",
        task_id="task",
        engine_turn_id="turn",
        sequence=2,
        status="succeeded",
        title="pytest",
        summary="2 passed",
    )
    session = EngineSessionRef(engine_type="scripted", opaque_ref="private")
    store.save_message(message)
    store.save_tool_run(tool_run)
    store.save_engine_session("c", session)

    snapshot = store.load_conversation("c")
    assert snapshot.messages == (message,)
    assert snapshot.tool_runs == (tool_run,)
    assert snapshot.engine_session == session
    store.close()


def test_approval_mode_is_persisted_per_project(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    with SQLiteStore(database) as store:
        project = store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        assert project.approval_mode == "request_approval"
        store.update_project_approval_mode("p", "full_auto")
        assert store.get_project("p").approval_mode == "full_auto"
        # 重复注册项目只刷新路径与打开时间，不覆盖用户设置
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        assert store.get_project("p").approval_mode == "full_auto"

    with SQLiteStore(database) as reopened:
        assert reopened.get_project("p").approval_mode == "full_auto"


def test_reasoning_effort_is_persisted_per_project(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    with SQLiteStore(database) as store:
        project = store.create_project(
            name="Repo", root_path=str(tmp_path), project_id="p"
        )
        assert project.reasoning_effort == "low"
        store.update_project_reasoning_effort("p", "high")
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        assert store.get_project("p").reasoning_effort == "high"

    with SQLiteStore(database) as reopened:
        assert reopened.get_project("p").reasoning_effort == "high"


def test_project_can_be_reopened_by_normalized_root_path(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(
            name="Repo", root_path=str(project_root), project_id="stable-project"
        )

        reopened = store.find_project_by_root_path(str(project_root / "."))

        assert reopened is not None
        assert reopened.project_id == "stable-project"


def test_archived_project_directory_restores_existing_record(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(project_id="p", name="P", root_path=str(tmp_path))
        store.archive_project("p")

        found = store.find_project_by_root_path(str(tmp_path))
        assert found is not None
        assert found.project_id == "p"
        assert found.archived is True

        restored = store.unarchive_project("p")
        assert restored.archived is False
        assert len(store.list_projects()) == 1
        assert len(store.list_projects(include_archived=True)) == 1


def test_recent_projects_sort_by_time_across_timestamp_formats(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(project_id="old-space", name="旧格式", root_path=str(tmp_path / "a"))
        store.create_project(project_id="iso-plus", name="ISO", root_path=str(tmp_path / "b"))
        store.connection.execute(
            "UPDATE projects SET last_opened_at = ? WHERE project_id = ?",
            ("2026-08-01 10:00:00", "old-space"),
        )
        store.connection.execute(
            "UPDATE projects SET last_opened_at = ? WHERE project_id = ?",
            ("2026-08-01T11:00:00+00:00", "iso-plus"),
        )
        store.connection.commit()

        assert [p.project_id for p in store.list_projects()] == ["iso-plus", "old-space"]


def test_new_conversation_does_not_inherit_history_or_session(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="old"
        )
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="new"
        )
        store.save_engine_session(
            "old", EngineSessionRef(engine_type="scripted", opaque_ref="old-session")
        )

        snapshot = store.load_conversation("new")
        assert snapshot.messages == ()
        assert snapshot.tool_runs == ()
        assert snapshot.engine_session is None


def test_missing_project_path_keeps_history_readable(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Gone", root_path=str(missing), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        assert not store.get_project("p").path_available
        assert store.load_conversation("c").conversation.conversation_id == "c"


def test_message_source_kind_columns_store_enum_values(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        message = Message(
            conversation_id="c",
            pair_id="phainon_ancient_machine",
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text="我在。",
            tts_eligible=True,
        )
        store.save_message(message)
        row = store.connection.execute(
            "SELECT source, kind FROM messages WHERE message_id = ?",
            (message.message_id,),
        ).fetchone()
        assert row["source"] == "character"
        assert row["kind"] == "character.speech"


def test_message_with_lone_surrogates_can_be_persisted(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        message = Message(
            conversation_id="c",
            pair_id="phainon_ancient_machine",
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text="前\udc80后 😀",
            payload={"reasoning": "思考\ud800", "items": ["\udfff"]},
        )

        store.save_message(message)

        assert message.text == "前�后 😀"
        assert message.payload == {"reasoning": "思考�", "items": ["�"]}
        assert store.load_conversation("c").messages == (message,)


def test_updates_on_missing_rows_raise_key_error(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(KeyError):
            store.rename_conversation("missing", "标题")
        with pytest.raises(KeyError):
            store.update_project_name("missing", "项目")
        with pytest.raises(KeyError):
            store.archive_project("missing")
        with pytest.raises(KeyError):
            store.set_onboarding_complete("missing")


def test_desktop_conversation_mode_and_archive_preserve_project(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "desktop.sqlite") as store:
        project = store.create_project(project_id="p", name="Repo", root_path=str(tmp_path))
        first = store.create_conversation(
            conversation_id="c1",
            project_id=project.project_id,
            pair_id="phainon_ancient_machine",
            title="聊天 1",
        )
        second = store.create_conversation(
            conversation_id="c2",
            project_id=project.project_id,
            pair_id="phainon_ancient_machine",
            title="聊天 2",
        )
        store.update_conversation_mode(first.conversation_id, "collaboration")
        store.archive_conversation(first.conversation_id)

        assert store.get_conversation(first.conversation_id).last_mode == "collaboration"
        assert store.get_conversation(first.conversation_id).archived is True
        assert [item.conversation_id for item in store.list_conversations(project.project_id)] == [
            second.conversation_id
        ]
        assert store.get_project(project.project_id).archived is False


def test_conversation_account_id_is_written_and_filters(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        project = store.create_project(project_id="p", name="Repo", root_path=str(tmp_path))
        account_a = store.create_conversation(
            project_id=project.project_id,
            pair_id="phainon_ancient_machine",
            title="账号A聊天",
            account_id="account-a",
        )
        account_b = store.create_conversation(
            project_id=project.project_id,
            pair_id="phainon_ancient_machine",
            title="账号B聊天",
            account_id="account-b",
        )
        # 按账号过滤互不可见（即使挂在同一项目下）
        assert [
            item.conversation_id
            for item in store.list_conversations(project.project_id, account_id="account-a")
        ] == [account_a.conversation_id]
        assert [
            item.conversation_id
            for item in store.list_conversations(project.project_id, account_id="account-b")
        ] == [account_b.conversation_id]
        # 不传账号时不过滤
        assert len(store.list_conversations(project.project_id)) == 2


def test_clear_engine_sessions_invalidates_only_target_account(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite")
    try:
        store.create_project(project_id="p", name="P", root_path=str(tmp_path))
        store.create_conversation(
            project_id="p",
            pair_id="phainon_ancient_machine",
            conversation_id="acc-a-conv",
            account_id="acc-a",
        )
        store.create_conversation(
            project_id="p",
            pair_id="phainon_ancient_machine",
            conversation_id="acc-b-conv",
            account_id="acc-b",
        )
        store.save_engine_session(
            "acc-a-conv", EngineSessionRef(engine_type="acp", opaque_ref="old-a")
        )
        store.save_engine_session(
            "acc-b-conv", EngineSessionRef(engine_type="acp", opaque_ref="old-b")
        )

        store.clear_engine_sessions("acc-a")

        assert store.load_conversation("acc-a-conv").engine_session is None
        assert store.load_conversation("acc-b-conv").engine_session == EngineSessionRef(
            engine_type="acp", opaque_ref="old-b"
        )
    finally:
        store.close()


def test_conversation_character_card_id_roundtrip(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        project = store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        bound = store.create_conversation(
            project_id=project.project_id,
            pair_id="phainon_ancient_machine",
            title="绑定卡",
            conversation_id="c-bound",
            character_card_id="card-01",
        )
        store.create_conversation(
            project_id=project.project_id,
            pair_id="phainon_ancient_machine",
            title="内置角色",
            conversation_id="c-unbound",
        )

        assert bound.character_card_id == "card-01"
        assert store.get_conversation("c-bound").character_card_id == "card-01"
        assert store.get_conversation("c-unbound").character_card_id is None
        listed = {
            item.conversation_id: item
            for item in store.list_conversations(project.project_id)
        }
        assert listed["c-bound"].character_card_id == "card-01"
        assert listed["c-unbound"].character_card_id is None


def test_find_active_conversation_with_pair_and_card(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p1")
        conv1 = store.create_conversation(
            project_id="p1",
            pair_id="pair_a",
            title="聊天1",
            character_card_id="card_x",
            account_id="acc1",
        )
        conv2 = store.create_conversation(
            project_id="p1",
            pair_id="pair_b",
            title="聊天2",
            character_card_id="card_x",
            account_id="acc1",
        )
        found_a = store.find_active_conversation(
            "p1", character_card_id="card_x", pair_id="pair_a", account_id="acc1"
        )
        assert found_a is not None and found_a.conversation_id == conv1.conversation_id
        found_b = store.find_active_conversation(
            "p1", character_card_id="card_x", pair_id="pair_b", account_id="acc1"
        )
        assert found_b is not None and found_b.conversation_id == conv2.conversation_id
        assert store.find_active_conversation("p1", pair_id="pair_c") is None


# ---------------------------------------------------------------- 摘要


def test_summary_upsert_is_idempotent_by_range(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        # 摘要只覆盖已落库的消息
        for message in (_message(cid, "开始", index=1), _message(cid, "结束", index=80)):
            store.save_message(message)
        first = store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id="m80",
                covers_message_count=80,
                content="第一版",
                provider="deepseek",
                model="deepseek-v4-flash",
                status="running",
            )
        )
        second = store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id="m80",
                covers_message_count=80,
                content="第二版",
                provider="deepseek",
                model="deepseek-v4-flash",
                status="completed",
            )
        )
        # 区间相同：保留原 summary_id，只更新内容与状态
        assert second.summary_id == first.summary_id
        assert second.content == "第二版"
        assert second.status == "completed"
        assert len(store.list_summaries(cid)) == 1
        assert store.latest_completed_summary(cid).summary_id == first.summary_id


def test_summary_failure_keeps_real_error(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        for message in (_message(cid, "开始", index=1), _message(cid, "结束", index=9)):
            store.save_message(message)
        summary = store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id="m9",
                covers_message_count=9,
                status="failed",
                error_code="summary_timeout",
                error="provider timeout",
            )
        )
        assert summary.content == ""
        assert summary.error_code == "summary_timeout"
        assert summary.error == "provider timeout"
        assert store.latest_completed_summary(cid) is None

        updated = store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id="m9",
                covers_message_count=9,
                content="补跑成功",
                status="completed",
            )
        )
        assert updated.summary_id == summary.summary_id
        assert updated.status == "completed"
        assert updated.content == "补跑成功"
        assert store.latest_completed_summary(cid).summary_id == summary.summary_id


def test_latest_summary_follows_coverage_end_time(tmp_path: Path) -> None:
    """最新摘要按覆盖终点消息的时间取，与 summary_id 顺序无关，failed 不参与。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        for i in (1, 40, 80, 90):
            store.save_message(_message(cid, f"第{i}条", index=i))

        def summary(summary_id: str, to_index: int, status: str) -> ConversationSummary:
            return ConversationSummary(
                summary_id=summary_id,
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id=f"m{to_index}",
                covers_message_count=to_index,
                content='{"摘要": "内容"}' if status == "completed" else "",
                status=status,
            )

        store.upsert_summary(summary("aaa-newer", 80, "completed"))
        store.upsert_summary(summary("zzz-older", 40, "completed"))
        store.upsert_summary(summary("mmm-failed", 90, "failed"))

        assert store.latest_completed_summary(cid).summary_id == "aaa-newer"
        assert store.load_conversation(cid).summary.summary_id == "aaa-newer"
        assert [item.summary_id for item in store.list_summaries(cid)] == [
            "aaa-newer",
            "mmm-failed",
            "zzz-older",
        ]


def test_summary_rejects_unknown_status_and_missing_row(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        with pytest.raises(ValueError, match="未知摘要状态"):
            store.upsert_summary(
                ConversationSummary(
                    conversation_id=cid,
                    covers_from_message_id="m1",
                    covers_to_message_id="m2",
                    covers_message_count=2,
                    status="半途",
                )
            )
        with pytest.raises(KeyError):
            store.get_summary("不存在")


# ---------------------------------------------------------------- 长期记忆


def test_memory_scope_isolation_by_project_and_assistant(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        scope = _scope()
        store.upsert_memory(
            PairMemory(
                **scope.model_dump(),
                conversation_id=cid,
                content="喜欢安静地看星星",
            )
        )
        assert len(store.list_memories(scope)) == 1
        # 换项目、角色、助手身份或账号都读不到
        assert store.list_memories(_scope(project_id="p2")) == []
        assert store.list_memories(_scope(character_ref="card:other")) == []
        assert store.list_memories(_scope(assistant_identity="another_assistant")) == []
        assert store.list_memories(_scope(account_id="account-b")) == []


def test_memory_requires_project_in_scope() -> None:
    with pytest.raises(ValueError, match="project_id"):
        _scope(project_id="")


def test_memory_delete_is_soft_and_recreatable(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope = _scope()
        memory = store.upsert_memory(PairMemory(**scope.model_dump(), content="一条记忆"))
        deleted = store.delete_memory(memory.memory_id)
        assert deleted.status == "deleted"
        assert store.list_memories(scope) == []
        assert len(store.list_memories(scope, status=None)) == 1
        assert store.get_memory(memory.memory_id).status == "deleted"

        # 删除后同内容可以重新写入（partial unique index 只约束 active）
        recreated = store.upsert_memory(PairMemory(**scope.model_dump(), content="一条记忆"))
        assert recreated.status == "active"
        assert recreated.memory_id != memory.memory_id
        assert len(store.list_memories(scope)) == 1
        assert len(store.list_memories(scope, status=None)) == 2


def test_memory_same_content_in_scope_is_idempotent(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope = _scope()
        first = store.upsert_memory(PairMemory(**scope.model_dump(), content="同一条"))
        second = store.upsert_memory(
            PairMemory(**scope.model_dump(), conversation_id="c-other", content="同一条")
        )
        assert second.memory_id == first.memory_id
        assert second.conversation_id == "c-other"
        assert len(store.list_memories(scope)) == 1


def test_memory_update_content_and_missing_row(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope = _scope()
        memory = store.upsert_memory(PairMemory(**scope.model_dump(), content="旧内容"))
        updated = store.update_memory(memory.memory_id, content="新内容")
        assert updated.content == "新内容"
        with pytest.raises(KeyError):
            store.update_memory("不存在", content="x")
        with pytest.raises(ValueError, match="不支持的记忆字段"):
            store.update_memory(memory.memory_id, keyword="x")


def test_memory_assistant_identity_unique_key_and_mutation_scope(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope_a = _scope(assistant_identity="assistant_a")
        scope_b = _scope(assistant_identity="assistant_b")

        # 唯一键含 assistant_identity：不同助手同项目同内容可以并存
        mem_a = store.upsert_memory(PairMemory(**scope_a.model_dump(), content="重要约定"))
        mem_b = store.upsert_memory(PairMemory(**scope_b.model_dump(), content="重要约定"))
        assert mem_a.memory_id != mem_b.memory_id
        assert [m.memory_id for m in store.list_memories(scope_a)] == [mem_a.memory_id]
        assert [m.memory_id for m in store.list_memories(scope_b)] == [mem_b.memory_id]

        # 带 scope 的读取、修改、删除跨助手时报 memory_scope_mismatch
        with pytest.raises(KeyError, match="memory_scope_mismatch"):
            store.get_memory(mem_a.memory_id, scope=scope_b)
        with pytest.raises(KeyError, match="memory_scope_mismatch"):
            store.update_memory(mem_a.memory_id, scope=scope_b, content="恶意篡改")
        with pytest.raises(KeyError, match="memory_scope_mismatch"):
            store.delete_memory(mem_a.memory_id, scope=scope_b)

        deleted_a = store.delete_memory(mem_a.memory_id, scope=scope_a)
        assert deleted_a.status == "deleted"
        assert store.list_memories(scope_a) == []
        assert len(store.list_memories(scope_b)) == 1
        assert store.get_memory(mem_b.memory_id, scope=scope_b).status == "active"


# ---------------------------------------------------------------- 回合指标


def test_metric_null_and_zero_semantics(tmp_path: Path) -> None:
    """未观测字段为 None，真实零值为 0。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        stored = store.upsert_turn_metric(_metric(cid, turn_id="t1", status="running"))
        assert stored.input_tokens is None
        assert stored.output_tokens is None
        assert stored.total_tokens is None
        assert stored.tool_rounds == 0
        assert stored.failure_type is None
        assert stored.origin == "desktop"
        assert stored.remote_device_key is None

        reloaded = store.query_turn_metrics(TurnMetricQuery(conversation_id=cid)).items
        assert reloaded == (stored,)

        updated = store.upsert_turn_metric(
            _metric(
                cid,
                turn_id="t1",
                status="failed",
                failure_type="provider_error",
                failure_message="HTTP 503",
                input_tokens=None,
            )
        )
        assert updated.status == "failed"
        assert updated.failure_type == "provider_error"
        assert updated.input_tokens is None


def test_metric_upsert_keeps_one_row_per_turn(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.upsert_turn_metric(_metric(cid, turn_id="t1", status="running"))
        store.upsert_turn_metric(_metric(cid, turn_id="t1", status="completed", tool_rounds=3))
        (metric,) = store.query_turn_metrics(
            TurnMetricQuery(conversation_id=cid, turn_kind="character_turn")
        ).items
        assert metric.turn_id == "t1"
        assert metric.status == "completed"
        assert metric.tool_rounds == 3


def test_metric_query_filters_and_cursor_pagination(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        for index in range(5):
            store.upsert_turn_metric(
                _metric(
                    cid,
                    turn_id=f"t{index}",
                    index=index,
                    status="completed" if index % 2 == 0 else "failed",
                )
            )
        store.upsert_turn_metric(
            _metric(cid, turn_id="task-1", index=9, turn_kind="assistant_task", origin="remote",
                    remote_device_key="device-1")
        )

        page = store.query_turn_metrics(TurnMetricQuery(conversation_id=cid, limit=2))
        assert [item.turn_id for item in page.items] == ["task-1", "t4"]
        assert page.next_cursor is not None
        second = store.query_turn_metrics(
            TurnMetricQuery(conversation_id=cid, limit=2, cursor=page.next_cursor)
        )
        assert [item.turn_id for item in second.items] == ["t3", "t2"]

        failed = store.query_turn_metrics(
            TurnMetricQuery(conversation_id=cid, status="failed")
        )
        assert {item.turn_id for item in failed.items} == {"t1", "t3"}

        remote = store.query_turn_metrics(TurnMetricQuery(origin="remote"))
        assert [item.turn_id for item in remote.items] == ["task-1"]
        assert remote.items[0].remote_device_key == "device-1"

        by_assistant = store.query_turn_metrics(
            TurnMetricQuery(assistant_identity="ancient_machine")
        )
        assert len(by_assistant.items) == 6
        assert store.query_turn_metrics(
            TurnMetricQuery(assistant_identity="unknown_assistant")
        ).items == ()


def test_metric_terminal_state_cannot_regress(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        metric = store.upsert_turn_metric(_metric(cid, turn_id="t1", status="completed"))
        # 同状态重写允许
        again = store.upsert_turn_metric(_metric(cid, turn_id="t1", status="completed"))
        assert again.metric_id == metric.metric_id
        with pytest.raises(ValueError, match="终态不可回退"):
            store.upsert_turn_metric(_metric(cid, turn_id="t1", status="running"))
        # 非终态之间可以推进
        running = store.upsert_turn_metric(_metric(cid, turn_id="t2", status="running"))
        cancelled = store.upsert_turn_metric(_metric(cid, turn_id="t2", status="cancelled"))
        assert cancelled.metric_id == running.metric_id
        assert cancelled.status == "cancelled"


def test_metric_query_limit_is_capped_at_200() -> None:
    assert TurnMetricQuery(limit=1000).limit == 200
    with pytest.raises(ValueError, match="limit"):
        TurnMetricQuery(limit=0)


def test_metric_query_rejects_bad_cursor(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(ValueError, match="游标"):
            store.query_turn_metrics(TurnMetricQuery(cursor="不是游标"))


def test_metric_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="未知指标状态"):
        _metric("c1", turn_id="t1", status="半途")
