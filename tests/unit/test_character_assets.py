"""CharacterAssetService 测试（V0.3.5 强逻辑 AI 轨道，成员 C）。

全部使用真实临时库与临时目录，不 mock 存储层；真实 IO 失败直接抛出。
契约：``docs/plans/V0.3.5-契约冻结.md`` §2.5/§2.6。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pair_harness.app_paths import AppPaths
from pair_harness.character_cards.assets import (
    KIND_AVATAR,
    KIND_REFERENCE_AUDIO,
    AssetRecord,
    CharacterAssetError,
    CharacterAssetService,
)
from pair_harness.storage.sqlite_store import SQLiteStore

PNG_BYTES = b"\x89PNG\r\n\x1a\nmock-png-body"


@pytest.fixture()
def service(tmp_path: Path) -> tuple[CharacterAssetService, SQLiteStore, Path]:
    store = SQLiteStore(tmp_path / "data" / "pair_harness.db")
    root = tmp_path / "character_assets"
    yield CharacterAssetService(store, root), store, root
    store.close()


def _store_png(
    assets: CharacterAssetService,
    card_id: str,
    *,
    source_ref: str = "avatar.png",
    data: bytes = PNG_BYTES,
) -> str:
    return assets.store_asset(
        card_id=card_id,
        data=data,
        kind=KIND_AVATAR,
        mime_type="image/png",
        source="user_upload",
        source_ref=source_ref,
    )


# ---------------------------------------------------------------- 全路径


def test_store_and_get_round_trip(service) -> None:
    assets, store, root = service
    asset_id = _store_png(assets, card_id="card-1", source_ref="原文件名.png")

    assert len(asset_id) == 32
    # 文件存在且遵守 <asset_id>.<ext> 命名
    stored = root / f"{asset_id}.png"
    assert stored.exists()
    assert stored.read_bytes() == PNG_BYTES

    data, mime_type = assets.get_asset(asset_id)
    assert data == PNG_BYTES
    assert mime_type == "image/png"

    # 表记录完整（kind / source_ref / card_id）
    row = store.connection.execute(
        "SELECT * FROM character_assets WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    assert row["card_id"] == "card-1"
    assert row["kind"] == KIND_AVATAR
    assert row["source_ref"] == "原文件名.png"
    assert row["file_path"] == str(stored)


def test_store_asset_extension_inference_and_explicit(service) -> None:
    assets, _, root = service
    jpeg = assets.store_asset(
        card_id="card-1",
        data=b"jpeg",
        kind=KIND_AVATAR,
        mime_type="image/jpeg",
        source="user_upload",
        source_ref="a.jpg",
    )
    assert (root / f"{jpeg}.jpeg").exists()

    unknown = assets.store_asset(
        card_id="card-1",
        data=b"dat",
        kind=KIND_REFERENCE_AUDIO,
        mime_type="application/octet-stream",
        source="user_upload",
        source_ref="b.dat",
    )
    assert (root / f"{unknown}.bin").exists()

    explicit = assets.store_asset(
        card_id="card-1",
        data=b"png",
        kind=KIND_AVATAR,
        mime_type="image/png",
        source="user_upload",
        source_ref="c.txt",
        extension="custom",
    )
    assert (root / f"{explicit}.custom").exists()


def test_get_asset_unknown_id_raises_keyerror(service) -> None:
    assets, _, _ = service
    with pytest.raises(KeyError):
        assets.get_asset("no-such-asset-id")


def test_get_asset_missing_file_raises_character_asset_error(service) -> None:
    assets, _, root = service
    asset_id = _store_png(assets, card_id="card-1")
    (root / f"{asset_id}.png").unlink()

    # 表记录仍在、文件缺失：真实失败必须抛出，不得返回空数据
    with pytest.raises(CharacterAssetError, match="资产文件缺失") as exc_info:
        assets.get_asset(asset_id)
    assert str(root / f"{asset_id}.png") in str(exc_info.value)


def test_delete_assets_for_card_cleans_files_and_rows(service) -> None:
    assets, store, root = service
    first = _store_png(assets, card_id="card-1", source_ref="1.png")
    second = _store_png(assets, card_id="card-1", source_ref="2.png")

    deleted = assets.delete_assets_for_card("card-1")
    assert deleted == 2
    assert not (root / f"{first}.png").exists()
    assert not (root / f"{second}.png").exists()
    assert assets.list_assets_for_card("card-1") == []
    with pytest.raises(KeyError):
        assets.get_asset(first)
    count = store.connection.execute(
        "SELECT COUNT(*) FROM character_assets WHERE card_id = ?", ("card-1",)
    ).fetchone()[0]
    assert count == 0
    # 无残留时重复删除返回 0，幂等
    assert assets.delete_assets_for_card("card-1") == 0


def test_delete_assets_for_card_tolerates_missing_file(service) -> None:
    assets, _, root = service
    asset_id = _store_png(assets, card_id="card-1")
    (root / f"{asset_id}.png").unlink()

    # 清理路径容忍文件级残缺：文件缺失不构成失败，表删除必须完成
    assert assets.delete_assets_for_card("card-1") == 1
    assert assets.list_assets_for_card("card-1") == []


def test_assets_isolated_per_card(service) -> None:
    assets, _, root = service
    card_a_asset = _store_png(assets, card_id="card-A", source_ref="a.png")
    card_b_asset = _store_png(assets, card_id="card-B", source_ref="b.png")

    listed_a = assets.list_assets_for_card("card-A")
    assert [a.asset_id for a in listed_a] == [card_a_asset]
    assert all(isinstance(a, AssetRecord) for a in listed_a)
    listed_b = assets.list_assets_for_card("card-B")
    assert [a.asset_id for a in listed_b] == [card_b_asset]

    assets.delete_assets_for_card("card-A")
    assert not (root / f"{card_a_asset}.png").exists()
    assert (root / f"{card_b_asset}.png").exists()
    assert assets.list_assets_for_card("card-A") == []
    assert [a.asset_id for a in assets.list_assets_for_card("card-B")] == [card_b_asset]


def test_store_asset_write_failure_leaves_no_record(service) -> None:
    _, store, root = service
    root.mkdir(parents=True, exist_ok=True)
    blocked = root / "blocked_dir"
    blocked.write_text("this is a file, not a directory")
    assets = CharacterAssetService(store, blocked)

    # 文件写失败（root.mkdir 对已存在文件抛 FileExistsError）：原始异常不吞
    with pytest.raises(FileExistsError):
        _store_png(assets, card_id="card-1")
    count = store.connection.execute(
        "SELECT COUNT(*) FROM character_assets"
    ).fetchone()[0]
    assert count == 0  # 不留半行记录


# ---------------------------------------------------------------- AppPaths 目录


def test_app_paths_character_assets(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paths = AppPaths(data_dir).ensure()
    assert paths.character_assets == data_dir / "character_assets"
    assert paths.character_assets.is_dir()
