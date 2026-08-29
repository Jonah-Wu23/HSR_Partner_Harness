from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path

    @property
    def database(self) -> Path:
        return self.data_dir / "pair_harness.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def character_assets(self) -> Path:
        """角色卡受管理资产目录（头像、参考音频等），见 V0.3.5 契约 §2.5/§2.6。"""
        return self.data_dir / "character_assets"

    def ensure(self) -> "AppPaths":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.character_assets.mkdir(parents=True, exist_ok=True)
        return self

    @classmethod
    def default(cls) -> "AppPaths":
        local_app_data = os.getenv("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
        return cls(base / "PairHarness")

