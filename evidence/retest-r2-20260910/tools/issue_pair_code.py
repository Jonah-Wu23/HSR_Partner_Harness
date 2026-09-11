"""手机端配对辅助：经已鉴权远程连接签发配对码（无需桌面 GUI）。

`remote.issue_code` 的实现允许「桌面 stdin 路径与已鉴权远程连接」调用，因此
本地已持有一个有效 token 时可以直接签发新配对码，供手机端手动填入。
"""

from __future__ import annotations

import asyncio
import json
import sys

from ph_client import Harness
from r2common import WS_URL, load_token


async def issue() -> dict:
    session = Harness(WS_URL, load_token(), device_name="desktop-code-issuer")
    await session.connect()
    try:
        return await session.call("remote.issue_code", {}, timeout=30)
    finally:
        await session.close()


async def main() -> int:
    code = await issue()
    print(json.dumps(code, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
