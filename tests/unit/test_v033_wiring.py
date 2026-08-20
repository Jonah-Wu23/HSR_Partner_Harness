"""V0.3.3 批 3 接线测试：card.* / remote.* 命令与助手提示词装配断言。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pair_harness.core.context import (
    AssistantInstructionError,
    assert_single_assistant_markdown,
)
from pair_harness.desktop_backend.application_service import ServiceError, build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


# ---------------------------------------------------------------- 装配断言


def test_assert_single_markdown_passes_on_exact_injection() -> None:
    md = "# 助手提示词\n你负责工具执行。"
    assert_single_assistant_markdown(md, md)


def test_assert_single_markdown_rejects_double_injection() -> None:
    md = "# 助手提示词"
    with pytest.raises(AssistantInstructionError):
        assert_single_assistant_markdown(md + "\n" + md, md)


def test_assert_single_markdown_rejects_mixed_character_content() -> None:
    md = "# 助手提示词"
    with pytest.raises(AssistantInstructionError):
        assert_single_assistant_markdown(md + "\n\n【角色卡】世界设定……", md)


def test_assert_single_markdown_rejects_empty() -> None:
    with pytest.raises(AssistantInstructionError):
        assert_single_assistant_markdown("", "# 助手提示词")


# ---------------------------------------------------------------- card.* 命令


@pytest.fixture
def service(tmp_path: Path):
    svc = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=lambda message: None,
    )
    yield svc
    svc.store.close()


async def test_card_list_contains_builtin_and_user_cards(service) -> None:
    result = await service.handle_command(command("1", "card.list"))
    sources = {card["source"] for card in result["cards"]}
    assert "builtin" in sources
    builtin = [c for c in result["cards"] if c["source"] == "builtin"]
    # 三对内置配对的角色侧（白厄、流萤、三月七）只读暴露
    assert {c["name"] for c in builtin} == {"白厄", "流萤", "三月七"}
    assert all(c["read_only"] is True for c in builtin)
    assert all(c["card_id"].startswith("builtin:") for c in builtin)


async def test_card_draft_persist_and_list(service) -> None:
    created = await service.handle_command(
        command("1", "card.create_draft", name="测试角色")
    )
    card_id = created["card_id"]
    listing = await service.handle_command(command("2", "card.list"))
    mine = [c for c in listing["cards"] if c["card_id"] == card_id]
    assert len(mine) == 1
    assert mine[0]["state"] == "draft"
    assert mine[0]["source"] == "user_created"
    assert mine[0]["read_only"] is False

    fetched = await service.handle_command(command("3", "card.get", card_id=card_id))
    assert fetched["card"]["name"] == "测试角色"
    assert fetched["card"]["spec"] == "chara_card_v3"


async def test_card_update_requires_payload(service) -> None:
    created = await service.handle_command(
        command("1", "card.create_draft", name="草稿")
    )
    with pytest.raises(ServiceError) as excinfo:
        await service.handle_command(
            command("2", "card.update", card_id=created["card_id"], card=None)
        )
    assert excinfo.value.code == "invalid_params"


async def test_card_update_rejects_invalid_payload(service) -> None:
    created = await service.handle_command(
        command("1", "card.create_draft", name="草稿")
    )
    with pytest.raises(ServiceError) as excinfo:
        await service.handle_command(
            command("2", "card.update", card_id=created["card_id"], card={"name": 123}
            )
        )
    assert excinfo.value.code == "card_invalid_payload"


async def test_builtin_cards_are_read_only(service) -> None:
    builtin_id = "builtin:phainon"
    for method, params in [
        ("card.update", {"card_id": builtin_id, "card": {"name": "x"}}),
        ("card.archive", {"card_id": builtin_id}),
        ("card.delete", {"card_id": builtin_id, "confirm": True}),
        ("card.select_active", {"card_id": builtin_id}),
        ("card.duplicate", {"card_id": builtin_id}),
    ]:
        with pytest.raises(ServiceError) as excinfo:
            await service.handle_command(command("1", method, **params))
        assert excinfo.value.code == "card_read_only", method


async def test_card_get_builtin_returns_readonly_card(service) -> None:
    fetched = await service.handle_command(
        command("1", "card.get", card_id="builtin:phainon")
    )
    assert fetched["card"]["name"] == "白厄"
    assert "builtin" in fetched["card"]["data"]["tags"]
    assert fetched["read_only"] is True


async def test_card_get_missing_raises(service) -> None:
    with pytest.raises(ServiceError) as excinfo:
        await service.handle_command(command("1", "card.get", card_id="nope"))
    assert excinfo.value.code == "card_not_found"


async def test_card_delete_requires_confirm(service) -> None:
    created = await service.handle_command(
        command("1", "card.create_draft", name="待删")
    )
    with pytest.raises(ServiceError) as excinfo:
        await service.handle_command(
            command("2", "card.delete", card_id=created["card_id"])
        )
    assert excinfo.value.code == "card_confirm_required"
    await service.handle_command(
        command("3", "card.delete", card_id=created["card_id"], confirm=True)
    )
    listing = await service.handle_command(command("4", "card.list"))
    assert all(c["card_id"] != created["card_id"] for c in listing["cards"])


# ---------------------------------------------------------------- remote.* 命令


async def test_remote_pair_full_flow(service) -> None:
    issued = await service.handle_command(command("0", "remote.issue_code"))
    code = issued["code"]
    assert issued["ttl_seconds"] == 300
    assert len(code) == 6 and code.isdigit()
    paired = await service.handle_command(
        command("1", "remote.pair", code=code, device_name="我的手机")
    )
    assert paired["token"]
    # 一次性：同码再用必须失败
    with pytest.raises(ServiceError) as excinfo:
        await service.handle_command(
            command("2", "remote.pair", code=code, device_name="第二台")
        )
    assert excinfo.value.code == "pairing_used"

    devices = await service.handle_command(command("3", "remote.list_devices"))
    assert [d["device_name"] for d in devices["devices"]] == ["我的手机"]
    assert all("token" not in d for d in devices["devices"])

    revoked = await service.handle_command(
        command("4", "remote.revoke", device_name="我的手机")
    )
    assert revoked["revoked_tokens"] == 1
    # 撤销后 authorize 立即拒绝
    decision = service.pairing_service.authorize(paired["token"], "app.bootstrap")
    assert decision.allowed is False
    assert decision.reason == "revoked_token"


async def test_remote_revoke_unknown_device(service) -> None:
    with pytest.raises(ServiceError) as excinfo:
        await service.handle_command(
            command("1", "remote.revoke", device_name="不存在的设备")
        )
    assert excinfo.value.code == "device_not_found"


async def test_pairing_state_persisted_across_service_restart(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    svc1 = build_demo_service(
        database=database, project_root=tmp_path, event_sink=lambda m: None
    )
    code = svc1.pairing_service.issue_code()
    token = svc1.pairing_service.claim(code, device_name="手机A")
    await svc1.shutdown()

    svc2 = build_demo_service(
        database=database, project_root=tmp_path, event_sink=lambda m: None
    )
    try:
        assert svc2.pairing_service.authorize(token, "app.bootstrap").allowed is True
    finally:
        svc2.store.close()


# ---------------------------------------------------------------- voice.provision 默认集合


def test_provision_default_excludes_assistant_speakers() -> None:
    """助手侧说话方不再随默认一键生成请求（V0.3.3 修正）。"""
    from pair_harness.config.voices import (
        assistant_speaker_ids,
        load_reference_voice_manifest,
    )

    manifest = load_reference_voice_manifest()
    assistant_ids = assistant_speaker_ids()
    default_set = {
        entry.speaker_id
        for entry in manifest
        if entry.speaker_id not in assistant_ids
    }
    # 角色侧三说话方仍在，助手侧被排除
    assert default_set == {"phainon", "firefly", "march7"}
    assert default_set & assistant_speaker_ids() == set()
