from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from tests.service_helpers import call, expect_service_error

FIXTURE_CARD = (
    Path(__file__).resolve().parents[1] / "fixtures" / "character_cards" / "白厄（3.4前）.json"
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BUILTIN_ID = "builtin:phainon"


def _asset_dir(service) -> Path:
    return service.store.database.parent / "character_assets"


def _write_png(service, name: str, body: bytes = b"png-body") -> Path:
    # 头像按文件签名识别格式，PNG 签名加任意内容即可。
    path = service.tmp_path / name
    path.write_bytes(PNG_SIGNATURE + body)
    return path


async def _draft(service, name: str) -> str:
    return (await call(service, "draft", "card.create_draft", name=name))["card_id"]


# ---------------------------------------------------------------- 列表、草稿与内置卡


async def test_card_list_exposes_builtin_cards_read_only(service) -> None:
    result = await call(service, "1", "card.list")
    builtin = [c for c in result["cards"] if c["source"] == "builtin"]
    # 三对内置搭档的角色侧。
    assert {c["name"] for c in builtin} == {"白厄", "流萤", "三月七"}
    assert all(c["read_only"] is True for c in builtin)
    assert all(c["card_id"].startswith("builtin:") for c in builtin)


async def test_create_draft_lists_editable_user_card(service) -> None:
    card_id = await _draft(service, "测试角色")
    listing = await call(service, "1", "card.list")
    mine = [
        (c["state"], c["source"], c["read_only"])
        for c in listing["cards"]
        if c["card_id"] == card_id
    ]
    assert mine == [("draft", "user_created", False)]

    fetched = await call(service, "2", "card.get", card_id=card_id)
    assert fetched["card"]["name"] == "测试角色"
    assert fetched["card"]["spec"] == "chara_card_v3"


@pytest.mark.parametrize(
    ("card", "code"),
    [(None, "invalid_params"), ({"name": 123}, "card_invalid_payload")],
)
async def test_card_update_rejects_bad_payload(service, card: Any, code: str) -> None:
    card_id = await _draft(service, "草稿")
    await expect_service_error(
        lambda: call(service, "1", "card.update", card_id=card_id, card=card), code
    )


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("card.update", {"card": {"name": "x"}}),
        ("card.archive", {}),
        ("card.delete", {"confirm": True}),
        ("card.select_active", {}),
        ("card.export_png", {"path": "x.png"}),
    ],
)
async def test_builtin_cards_are_read_only(service, method: str, params: dict) -> None:
    await expect_service_error(
        lambda: call(service, "1", method, card_id=BUILTIN_ID, **params), "card_read_only"
    )


async def test_card_get_builtin_returns_read_only_card(service) -> None:
    fetched = await call(service, "1", "card.get", card_id=BUILTIN_ID)
    assert fetched["read_only"] is True
    assert fetched["card"]["name"] == "白厄"
    assert "builtin" in fetched["card"]["data"]["tags"]


async def test_duplicate_builtin_card_creates_editable_copy(service) -> None:
    # 内置卡不能直接导出，复制出的可编辑副本供导出使用。
    result = await call(service, "1", "card.duplicate", card_id=BUILTIN_ID)
    assert "副本" in result["name"]
    fetched = await call(service, "2", "card.get", card_id=result["card_id"])
    assert fetched["read_only"] is False
    assert fetched["state"] == "imported"
    assert "内置角色" in fetched["card"]["data"]["creator_notes"]


async def test_card_get_unknown_id_reports_not_found(service) -> None:
    await expect_service_error(
        lambda: call(service, "1", "card.get", card_id="nope"), "card_not_found"
    )


async def test_card_delete_requires_confirm(service) -> None:
    card_id = await _draft(service, "待删")
    await expect_service_error(
        lambda: call(service, "1", "card.delete", card_id=card_id), "card_confirm_required"
    )
    await call(service, "2", "card.delete", card_id=card_id, confirm=True)
    listing = await call(service, "3", "card.list")
    assert all(c["card_id"] != card_id for c in listing["cards"])


async def test_publish_validates_first_mes_then_is_idempotent(service) -> None:
    card_id = await _draft(service, "无开场白角色")
    await expect_service_error(
        lambda: call(service, "1", "card.publish", card_id=card_id),
        "card_publish_invalid",
        contains="第一条消息",
    )

    await call(
        service,
        "2",
        "card.update",
        card_id=card_id,
        card={"name": "无开场白角色", "description": "设定", "first_mes": "你好。"},
    )
    assert await call(service, "3", "card.publish", card_id=card_id) == {
        "card_id": card_id,
        "state": "saved",
    }
    # 已发布的卡再次发布直接返回当前状态。
    republished = await call(service, "4", "card.publish", card_id=card_id)
    assert republished["state"] == "saved"


# ---------------------------------------------------------------- 导入导出


@pytest.mark.parametrize(
    ("file_name", "content", "contains"),
    [
        ("不存在的卡.json", None, "不存在的卡.json"),
        ("broken.json", "{这不是合法JSON", "解析失败"),
    ],
)
async def test_peek_import_unreadable_json_reports_reason(
    service, file_name: str, content: str | None, contains: str
) -> None:
    path = service.tmp_path / file_name
    if content is not None:
        path.write_text(content, encoding="utf-8")
    await expect_service_error(
        lambda: call(service, "1", "card.peek_import", path=str(path)),
        "card_import_failed",
        contains=contains,
    )


async def test_import_json_persists_as_tavern_import_with_duplicate_suffix(service) -> None:
    imported = await call(service, "1", "card.import_json", path=str(FIXTURE_CARD))
    assert imported["state"] == "imported"
    assert imported["report"]["applied"]

    fetched = await call(service, "2", "card.get", card_id=imported["card_id"])
    assert fetched["card"]["name"] == "白厄（3.4前）"
    assert fetched["source"] == "tavern_import"

    duplicate = await call(
        service, "3", "card.import_json", path=str(FIXTURE_CARD), as_duplicate=True
    )
    assert duplicate["state"] == "imported"
    assert duplicate["name"] == "白厄（3.4前）（副本）"


async def test_export_json_writes_card_and_optional_avatar_sidecar(service) -> None:
    card_id = (await call(service, "1", "card.import_json", path=str(FIXTURE_CARD)))["card_id"]
    export_path = service.tmp_path / "exported_card.json"
    sidecar = export_path.with_suffix(".avatar.png")

    # 卡没有头像时只写卡文件。
    result = await call(
        service, "2", "card.export_json", card_id=card_id, path=str(export_path), save_avatar=True
    )
    assert result == {"exported": True, "path": str(export_path), "avatar_saved": False}
    assert not sidecar.exists()
    reread = await call(service, "3", "card.peek_import", path=str(export_path))
    assert reread["preview"]["name"] == "白厄（3.4前）"

    avatar = _write_png(service, "avatar.png", b"sidecar-bytes")
    await call(service, "4", "card.set_avatar", card_id=card_id, path=str(avatar))
    result = await call(
        service, "5", "card.export_json", card_id=card_id, path=str(export_path), save_avatar=True
    )
    assert result["avatar_saved"] is True
    assert sidecar.read_bytes() == avatar.read_bytes()


# ---------------------------------------------------------------- 头像与资产


async def test_avatar_roundtrip_through_managed_asset_dir(service) -> None:
    card_id = await _draft(service, "头像角色")
    avatar = _write_png(service, "avatar.png", b"png-body-bytes")

    set_result = await call(service, "1", "card.set_avatar", card_id=card_id, path=str(avatar))
    assert set_result["card_id"] == card_id
    assert set_result["mime_type"] == "image/png"
    # 头像复制进受管理目录。
    assert len(list(_asset_dir(service).iterdir())) == 1

    fetched = await call(service, "2", "card.get", card_id=card_id)
    assert fetched["avatar"]["mime_type"] == "image/png"
    assert base64.b64decode(fetched["avatar"]["data_base64"]) == avatar.read_bytes()

    removed = await call(service, "3", "card.remove_avatar", card_id=card_id)
    assert removed == {"card_id": card_id, "removed": True}
    assert (await call(service, "4", "card.get", card_id=card_id))["avatar"] is None
    assert list(_asset_dir(service).iterdir()) == []
    assert service.asset_service.list_assets_for_card(card_id) == []


@pytest.mark.parametrize(
    ("content", "code"),
    [
        pytest.param(b"plain text, not an image", "card_avatar_unsupported", id="非图片"),
        pytest.param(
            PNG_SIGNATURE + b"\x00" * (5 * 1024 * 1024), "card_avatar_too_large", id="超过5MB"
        ),
    ],
)
async def test_set_avatar_rejects_non_image_and_oversize(
    service, content: bytes, code: str
) -> None:
    card_id = await _draft(service, "头像校验")
    path = service.tmp_path / "avatar.png"
    path.write_bytes(content)
    await expect_service_error(
        lambda: call(service, "1", "card.set_avatar", card_id=card_id, path=str(path)), code
    )


async def test_card_get_reports_missing_avatar_asset(service) -> None:
    card_id = await _draft(service, "损坏卡")
    avatar = _write_png(service, "avatar.png", b"to-be-deleted")
    await call(service, "1", "card.set_avatar", card_id=card_id, path=str(avatar))
    # 资产记录还在，文件丢失。
    for record in service.asset_service.list_assets_for_card(card_id):
        Path(record.file_path).unlink()

    await expect_service_error(
        lambda: call(service, "2", "card.get", card_id=card_id), "card_avatar_missing"
    )


async def test_duplicate_card_copies_assets(service) -> None:
    card_id = await _draft(service, "资产卡")
    avatar = _write_png(service, "avatar.png", b"original-image-bytes")
    await call(service, "1", "card.set_avatar", card_id=card_id, path=str(avatar))
    copy_id = (await call(service, "2", "card.duplicate", card_id=card_id))["card_id"]

    # 删除原卡会清理原卡资产，副本头像仍可读取。
    await call(service, "3", "card.delete", card_id=card_id, confirm=True)
    fetched = await call(service, "4", "card.get", card_id=copy_id)
    assert base64.b64decode(fetched["avatar"]["data_base64"]) == avatar.read_bytes()


async def test_delete_card_cleans_all_assets(service) -> None:
    card_id = await _draft(service, "资产清理")
    avatar = _write_png(service, "avatar.png")
    await call(service, "1", "card.set_avatar", card_id=card_id, path=str(avatar))
    # MP3 只校验扩展名与大小，时长交给 DashScope 判断。
    reference = service.tmp_path / "reference.mp3"
    reference.write_bytes(b"ID3" + b"\x00" * 64)
    await call(
        service, "2", "voice.card_bind_reference", card_id=card_id, path=str(reference)
    )
    kinds = {a.kind for a in service.asset_service.list_assets_for_card(card_id)}
    assert kinds == {"avatar", "reference_audio"}

    await call(service, "3", "card.delete", card_id=card_id, confirm=True)
    assert service.asset_service.list_assets_for_card(card_id) == []
    assert list(_asset_dir(service).iterdir()) == []
