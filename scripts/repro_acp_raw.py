"""原始 ACP 流调试：手工走 initialize → session/new → session/prompt，转储全部消息。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pair_harness.cli import load_dotenv  # noqa: E402
from pair_harness.desktop_backend.engine_factory import ensure_reasonix_home  # noqa: E402
from pair_harness.adapters.codex.auth import CodexAuthService  # noqa: E402
from pair_harness.adapters.codex.transport import SubprocessJsonLineConnection  # noqa: E402


async def main() -> None:
    load_dotenv(ROOT / ".env")
    base = os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL", "")
    key = os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY", "")
    model = os.getenv("PAIR_HARNESS_DIALOGUE_MODEL", "")
    auth = CodexAuthService(Path(os.getenv("TEMP", "/tmp")) / "ph-acp-raw", "default-local")
    home = ensure_reasonix_home(auth, base_url=base, model=model, api_key=key)
    conn = await SubprocessJsonLineConnection.create(
        "reasonix",
        args=["acp"],
        env={
            "REASONIX_HOME": str(home),
            "DEEPSEEK_API_KEY": key,
        },
    )
    seq = 0

    def request(method: str, params: dict) -> dict:
        nonlocal seq
        seq += 1
        return {"id": seq, "method": method, "params": params}

    async def call(method: str, params: dict) -> dict:
        await conn.write_line(
            (json.dumps(request(method, params), ensure_ascii=False) + "\n").encode("utf-8")
        )
        while True:
            line = await conn.read_line()
            if not line:
                raise RuntimeError("EOF")
            msg = json.loads(line)
            if "id" in msg and "method" not in msg:
                return msg
            print("[notify]", json.dumps(msg, ensure_ascii=False)[:400])

    print("[init]", json.dumps(await call("initialize", {"clientInfo": {"name": "raw", "version": "0"}}))[:200])
    new_session = await call("session/new", {"cwd": str(ROOT), "model": model})
    session_id = new_session["result"]["sessionId"]
    print("[session/new]", json.dumps(new_session)[:300])
    result = await call(
        "session/prompt",
        {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": "列出当前目录顶层文件，只要一行摘要，不要修改任何文件。"}],
        },
    )
    print("[prompt result]", json.dumps(result, ensure_ascii=False)[:400])
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
