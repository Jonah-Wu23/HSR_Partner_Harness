# 角色卡资产：文件存于 <root>/<asset_id>.<ext>，记录存于 character_assets 表。
# 先写文件、成功后再写表；删除时文件已缺失不算失败，表记录必须删掉。

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pair_harness.storage.sqlite_store import SQLiteStore

# extension 参数缺省时按 mime_type 推断文件扩展名。
_EXTENSION_BY_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/webp": "webp",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
}
_DEFAULT_EXTENSION = "bin"


class CharacterAssetError(RuntimeError):
    """表中有资产记录而文件缺失。"""


@dataclass(frozen=True)
class AssetRecord:
    """``character_assets`` 表一行记录的只读视图。"""

    asset_id: str
    card_id: str
    kind: str
    mime_type: str
    file_path: str
    source_ref: str
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_extension(mime_type: str) -> str:
    return _EXTENSION_BY_MIME.get(mime_type, _DEFAULT_EXTENSION)


class CharacterAssetService:
    """角色卡资产的文件与表记录双向服务，复用 ``store.connection``。"""

    def __init__(self, store: SQLiteStore, root: Path) -> None:
        self.connection = store.connection
        self.root = Path(root)

    def store_asset(
        self,
        *,
        card_id: str,
        data: bytes,
        kind: str,
        mime_type: str,
        source: str,
        source_ref: str,
        extension: str = "",
    ) -> str:
        """写入一份资产，返回新分配的 asset_id。

        ``extension`` 缺省时按 mime_type 推断，推不出用 ``bin``。表里没有
        ``source`` 列，来源枚举由调用方写进卡 JSON 的 hsr 引用字段。
        """
        asset_id = uuid4().hex
        ext = extension.lstrip(".") if extension else _infer_extension(mime_type)
        path = self.root / f"{asset_id}.{ext}"
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.connection.execute(
            "INSERT INTO character_assets("
            "asset_id, card_id, kind, mime_type, file_path, source_ref, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (asset_id, card_id, kind, mime_type, str(path), source_ref, _now()),
        )
        self.connection.commit()
        return asset_id

    def get_asset(self, asset_id: str) -> tuple[bytes, str]:
        """读取资产字节与 mime_type。未知 asset_id 抛 KeyError；
        表有记录而文件缺失抛 :class:`CharacterAssetError`。"""
        row = self.connection.execute(
            "SELECT * FROM character_assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise KeyError(asset_id)
        path = Path(row["file_path"])
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise CharacterAssetError(f"资产文件缺失: {path}") from exc
        return data, row["mime_type"]

    def list_assets_for_card(self, card_id: str) -> list[AssetRecord]:
        """该卡全部资产记录，按创建先后排序。"""
        rows = self.connection.execute(
            "SELECT * FROM character_assets WHERE card_id = ? "
            "ORDER BY created_at, rowid",
            (card_id,),
        ).fetchall()
        return [
            AssetRecord(
                asset_id=row["asset_id"],
                card_id=row["card_id"],
                kind=row["kind"],
                mime_type=row["mime_type"],
                file_path=row["file_path"],
                source_ref=row["source_ref"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def delete_asset(self, asset_id: str) -> None:
        """删除单个资产的文件与表记录；未知 asset_id 抛 KeyError。"""
        row = self.connection.execute(
            "SELECT file_path FROM character_assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            raise KeyError(asset_id)
        Path(row["file_path"]).unlink(missing_ok=True)
        self.connection.execute(
            "DELETE FROM character_assets WHERE asset_id = ?", (asset_id,)
        )
        self.connection.commit()

    def delete_assets_for_card(self, card_id: str) -> int:
        """删除该卡全部资产的文件与表记录，返回删除的记录数。"""
        rows = self.connection.execute(
            "SELECT asset_id, file_path FROM character_assets WHERE card_id = ?",
            (card_id,),
        ).fetchall()
        for row in rows:
            Path(row["file_path"]).unlink(missing_ok=True)
        cursor = self.connection.execute(
            "DELETE FROM character_assets WHERE card_id = ?", (card_id,)
        )
        self.connection.commit()
        return cursor.rowcount
