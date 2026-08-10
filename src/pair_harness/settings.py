from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    codex_bin: str = "codex"
    dialogue_base_url: str | None = None
    dialogue_api_key: str | None = None
    dialogue_model: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            codex_bin=os.getenv("PAIR_HARNESS_CODEX_BIN", "codex"),
            dialogue_base_url=os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL"),
            dialogue_api_key=os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY"),
            dialogue_model=os.getenv("PAIR_HARNESS_DIALOGUE_MODEL"),
        )

