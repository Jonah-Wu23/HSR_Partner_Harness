"""角色卡受管理资产服务（V0.3.5 强逻辑 AI 轨道，成员 C）。

契约：``docs/plans/V0.3.5-契约冻结.md`` §2.6（资产服务内部接口）、
§2.5（set_avatar 相关语义）。资产由两层组成：

- 文件层：``<root>/<asset_id>.<ext>``，root 为 ``AppPaths.character_assets``；
- 表记录层：``character_assets`` 表（v9，见 ``storage/sqlite_store.py``）。

写入顺序固定为「先写文件、成功后再落库」，文件写失败直接抛原始异常，
不留半行记录；读取时表有记录而文件缺失必须抛 :class:`CharacterAssetError`
（真实失败，不合成空数据）。清理路径容忍文件级残缺（文件已缺失仍继续
删表），但表删除必须完成。

契约偏离说明：§2.6 的 ``store_asset`` 签名含 ``source`` 参数，但 v9
``character_assets`` 表只有 ``source_ref`` 一列（无 source 列，schema.sql 与
迁移均不在本任务可改范围）。资产的 ``source`` 溯源枚举的权威位置是角色卡
JSON 的 ``hsr.avatar_asset`` / ``hsr.voice_profile``（见
``docs/character-card/角色卡数据契约.md`` §6/§7），由调用方在落库后写入卡，
本服务只持久化 ``source_ref``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pair_harness.storage.sqlite_store import SQLiteStore

# 资产种类约定（kind 列的值）。
KIND_AVATAR = "avatar"
KIND_REFERENCE_AUDIO = "reference_audio"

# mime_type → 文件扩展名（extension 参数缺省时的推断表）。
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
    """资产相关真实失败（如表记录在而文件缺失）。"""


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
        self.store = store
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
        """落库一份资产，返回新分配的 asset_id。

        先写文件（``<root>/<asset_id>.<ext>``，无点扩展名；缺省按 mime_type
        推断，推不出用 ``bin``），写文件成功后再 INSERT 表记录。文件写失败
        抛原始异常，不吞、不留半行记录。``source`` 溯源枚举在表无对应列，
        由调用方写入卡 JSON 的 hsr 引用字段，本层不持久化。
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
        表有记录而文件缺失抛 :class:`CharacterAssetError`，不合成空数据。"""
        row = self.connection.execute(
            "SELECT * FROM character_assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise KeyError(asset_id)
        path = Path(row["file_path"])
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise CharacterAssetError(f"资产文件缺失: {path}") from None
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

    def delete_assets_for_card(self, card_id: str) -> int:
        """删除该卡全部资产：先删文件、再删表记录，返回删除的记录数。

        文件已缺失不构成失败（清理路径容忍文件级残缺），但任何其他文件
        IO 异常与表删除失败都按原始异常抛出；表删除必须完成。
        """
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
