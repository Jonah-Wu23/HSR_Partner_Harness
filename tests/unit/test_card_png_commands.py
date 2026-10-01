from __future__ import annotations

from pathlib import Path

from tests.service_helpers import call, expect_service_error

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


async def test_peek_import_json_reports_preview(service) -> None:
    preview = (await call(service, "1", "card.peek_import", path=str(JSON_FIXTURE)))["preview"]
    assert preview["format"] == "json"
    assert preview["name"] == "白厄（3.4前）"
    assert preview["spec_version"] == "3.0"
    assert preview["avatar_available"] is False
    assert preview["avatar_width"] is None
    assert preview["avatar_height"] is None
    assert preview["greeting_count"] == 6
    assert preview["world_book_entries"] == 20
    assert set(preview["report"].keys()) == REPORT_FIELDS


async def test_peek_import_png_reports_preview_with_avatar_size(service) -> None:
    preview = (await call(service, "1", "card.peek_import", path=str(PNG_FIXTURE)))["preview"]
    assert preview["format"] == "png"
    assert preview["avatar_available"] is True
    assert preview["avatar_width"] == 64
    assert preview["avatar_height"] == 64
    assert preview["name"] == "白厄（3.4前）"
    assert preview["greeting_count"] == 6
    assert preview["world_book_entries"] == 20
    assert set(preview["report"].keys()) == REPORT_FIELDS


async def test_peek_import_detects_png_by_signature(service) -> None:
    disguised = service.tmp_path / "伪装成.json"
    disguised.write_bytes(PNG_FIXTURE.read_bytes())
    preview = (await call(service, "1", "card.peek_import", path=str(disguised)))["preview"]
    assert preview["format"] == "png"
    assert preview["avatar_available"] is True


async def test_peek_import_corrupted_png_fails_with_reason(service) -> None:
    broken = service.tmp_path / "broken.png"
    broken.write_bytes(PNG_SIGNATURE + b"this is not a valid png chunk layout")
    error = await expect_service_error(
        lambda: call(service, "1", "card.peek_import", path=str(broken)),
        "card_import_failed",
    )
    assert str(error).strip()


async def test_import_png_stores_card_and_avatar_asset(service) -> None:
    result = await call(service, "1", "card.import_png", path=str(PNG_FIXTURE))
    assert result["state"] == "imported"
    assert result["name"] == "白厄（3.4前）"
    assert set(result["report"].keys()) == REPORT_FIELDS

    hsr = service.card_repository.get_card(result["card_id"]).card.hsr
    assert hsr.avatar_asset.source == "png_import"
    assert hsr.avatar_asset.exported_in_png is True
    assert hsr.avatar_asset.mime_type == "image/png"
    # 头像资产就是导入的 PNG 原始字节。
    data, mime = service.asset_service.get_asset(hsr.avatar_asset.asset_id)
    assert mime == "image/png"
    assert data == PNG_FIXTURE.read_bytes()


async def test_import_png_as_duplicate_renames(service) -> None:
    result = await call(
        service, "1", "card.import_png", path=str(PNG_FIXTURE), as_duplicate=True
    )
    assert result["name"] == "白厄（3.4前）（副本）"
    assert result["state"] == "imported"


async def test_import_export_reimport_roundtrip(service) -> None:
    imported = await call(service, "1", "card.import_png", path=str(PNG_FIXTURE))
    out_path = service.tmp_path / "roundtrip.png"
    exported = await call(
        service, "2", "card.export_png", card_id=imported["card_id"], path=str(out_path)
    )
    assert exported["exported"] is True
    assert exported["path"] == str(out_path)
    assert exported["name"] == "白厄（3.4前）"
    assert exported["world_book_entries"] == 20
    assert exported["greeting_count"] == 6
    assert "hsr" in exported["extensions"]
    assert out_path.read_bytes()[:8] == PNG_SIGNATURE

    again = await call(service, "3", "card.import_png", path=str(out_path))
    record = service.card_repository.get_card(again["card_id"])
    assert len(record.card.character_book.entries) == 20
    assert record.card.greeting_count() == 6


async def test_export_png_without_avatar_fails(service) -> None:
    draft = await call(service, "1", "card.create_draft", name="无头像")
    await expect_service_error(
        lambda: call(
            service,
            "2",
            "card.export_png",
            card_id=draft["card_id"],
            path=str(service.tmp_path / "no-avatar.png"),
        ),
        "card_export_failed",
        contains="头像",
    )
