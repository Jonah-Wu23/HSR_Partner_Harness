"""card.peek_import / card.import_png / card.export_png 命令测试（V0.3.7 集成波）。

契约：``docs/plans/V0.3.7-契约冻结.md`` §1.1/§1.2/§1.3。
构造范式沿用 tests/unit/test_v033_wiring.py（build_demo_service + 事件 sink
捕获）；失败路径按 Let It Fail 保留原始错误（ServiceError 携带原文）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pair_harness.desktop_backend.application_service import (
    ServiceError,
    build_demo_service,
)
from pair_harness.desktop_backend.commands import DesktopCommand

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "character_cards"
JSON_FIXTURE = FIXTURE_DIR / "白厄（3.4前）.json"
PNG_FIXTURE = FIXTURE_DIR / "白厄（3.4前）.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

REPORT_FIELDS = {
    "applied",
    "preserved",
    "not_executed",
    "normalized_from_root",
    "warnings",
    "errors",
}


@pytest.fixture
def service(tmp_path: Path):
    events: list[dict] = []
    svc = build_demo_service(
        database=tmp_path / "db" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    yield SimpleNamespace(svc=svc, events=events)
    svc.store.close()


def command(method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id="1", method=method, params=params)


async def test_peek_import_json_preserves_existing_fields(service) -> None:
    """peek JSON 路径：format=json、既有字段不回归（契约 §1.1 别名行为）。"""
    preview = await service.svc.handle_command(
        command("card.peek_import", path=str(JSON_FIXTURE))
    )
    assert preview["preview"]["format"] == "json"
    assert preview["preview"]["name"] == "白厄（3.4前）"
    assert preview["preview"]["spec_version"] == "3.0"
    assert preview["preview"]["avatar_available"] is False
    assert preview["preview"]["avatar_width"] is None
    assert preview["preview"]["avatar_height"] is None
    assert preview["preview"]["greeting_count"] == 6
    assert preview["preview"]["world_book_entries"] == 20
    assert set(preview["preview"]["report"].keys()) == REPORT_FIELDS


async def test_peek_import_json_alias_same_handler(service) -> None:
    """card.peek_import_json 是 card.peek_import 的 deprecated 别名（同一行为）。"""
    a = await service.svc.handle_command(
        command("card.peek_import", path=str(JSON_FIXTURE))
    )
    b = await service.svc.handle_command(
        command("card.peek_import_json", path=str(JSON_FIXTURE))
    )
    assert a == b
    assert a["preview"]["format"] == "json"


async def test_peek_import_png_fixture(service) -> None:
    """peek PNG：format=png、avatar_available=True、IHDR 尺寸 64x64、report 存在。"""
    preview = (await service.svc.handle_command(
        command("card.peek_import", path=str(PNG_FIXTURE))
    ))["preview"]
    assert preview["format"] == "png"
    assert preview["avatar_available"] is True
    assert preview["avatar_width"] == 64
    assert preview["avatar_height"] == 64
    assert preview["name"] == "白厄（3.4前）"
    assert preview["greeting_count"] == 6
    assert preview["world_book_entries"] == 20
    assert set(preview["report"].keys()) == REPORT_FIELDS


async def test_peek_import_png_extension_mismatch_still_png(service, tmp_path) -> None:
    """文件签名优先于扩展名：把 PNG 字节存成 .json 仍走 PNG 分支。"""
    fake = tmp_path / "伪装成.json"
    fake.write_bytes(PNG_FIXTURE.read_bytes())
    preview = (await service.svc.handle_command(
        command("card.peek_import", path=str(fake))
    ))["preview"]
    assert preview["format"] == "png"
    assert preview["avatar_available"] is True


async def test_peek_import_png_corrupted_content(service, tmp_path) -> None:
    """签名为 PNG 但内容损坏：如实报 card_import_failed 且 message 非空。"""
    broken = tmp_path / "broken.png"
    broken.write_bytes(PNG_SIGNATURE + b"this is not a valid png chunk layout")
    with pytest.raises(ServiceError) as excinfo:
        await service.svc.handle_command(
            command("card.peek_import", path=str(broken))
        )
    assert excinfo.value.code == "card_import_failed"
    assert str(excinfo.value).strip()


async def test_import_png_full_chain(service) -> None:
    """import_png 全链路：落库 + 头像资产真实入库 + hsr.avatar_asset 回写。"""
    result = await service.svc.handle_command(
        command("card.import_png", path=str(PNG_FIXTURE))
    )
    card_id = result["card_id"]
    assert result["state"] == "imported"
    assert result["name"] == "白厄（3.4前）"
    assert set(result["report"].keys()) == REPORT_FIELDS

    record = service.svc.card_repository.get_card(card_id)
    hsr = record.card.hsr
    assert hsr is not None
    assert hsr.avatar_asset is not None
    assert hsr.avatar_asset.source == "png_import"
    assert hsr.avatar_asset.exported_in_png is True
    assert hsr.avatar_asset.mime_type == "image/png"

    data, mime = service.svc.asset_service.get_asset(hsr.avatar_asset.asset_id)
    assert mime == "image/png"
    # 头像即 PNG 原始字节（白厄 fixture 96807 字节），图像数据逐字节保真。
    assert len(data) >= 90 * 1024
    assert data[:8] == PNG_SIGNATURE
    assert data == PNG_FIXTURE.read_bytes()


async def test_import_png_as_duplicate_renames(service) -> None:
    """as_duplicate=True 名称追加「（副本）」；不查重不改名（契约 §1.2）。"""
    result = await service.svc.handle_command(
        command("card.import_png", path=str(PNG_FIXTURE), as_duplicate=True)
    )
    assert result["name"] == "白厄（3.4前）（副本）"
    assert result["state"] == "imported"


async def test_import_export_reimport_roundtrip(service, tmp_path) -> None:
    """import→export→再 import 往返：世界书 20 条、greeting 6、extensions 含 hsr。"""
    imported = await service.svc.handle_command(
        command("card.import_png", path=str(PNG_FIXTURE))
    )
    out_path = tmp_path / "roundtrip.png"
    exported = await service.svc.handle_command(
        command("card.export_png", card_id=imported["card_id"], path=str(out_path))
    )
    assert exported["exported"] is True
    assert exported["path"] == str(out_path)
    assert exported["name"] == "白厄（3.4前）"
    assert exported["world_book_entries"] == 20
    assert exported["greeting_count"] == 6
    assert "hsr" in exported["extensions"]
    assert out_path.exists()
    assert out_path.read_bytes()[:8] == PNG_SIGNATURE

    again = await service.svc.handle_command(
        command("card.import_png", path=str(out_path))
    )
    record = service.svc.card_repository.get_card(again["card_id"])
    assert len(record.card.character_book.entries) == 20
    assert record.card.greeting_count() == 6


async def test_export_png_without_avatar_fails(service, tmp_path) -> None:
    """无头像卡 export_png → card_export_failed、message 含「头像」，不合成默认图。"""
    draft = await service.svc.handle_command(
        command("card.create_draft", name="无头像")
    )
    with pytest.raises(ServiceError) as excinfo:
        await service.svc.handle_command(
            command(
                "card.export_png",
                card_id=draft["card_id"],
                path=str(tmp_path / "no-avatar.png"),
            )
        )
    assert excinfo.value.code == "card_export_failed"
    assert "头像" in str(excinfo.value)


async def test_export_png_builtin_card_read_only(service) -> None:
    """内置卡 export_png → card_read_only。"""
    with pytest.raises(ServiceError) as excinfo:
        await service.svc.handle_command(
            command("card.export_png", card_id="builtin:phainon", path="x.png")
        )
    assert excinfo.value.code == "card_read_only"
