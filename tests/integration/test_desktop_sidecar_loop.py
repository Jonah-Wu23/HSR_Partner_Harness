from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest


async def _read_json_line(stream: asyncio.StreamReader) -> dict:
    line = await asyncio.wait_for(stream.readline(), timeout=10)
    assert line, "Sidecar 提前退出"
    value = json.loads(line.decode("utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.mark.asyncio
async def test_demo_sidecar_survives_bad_json_and_processes_valid_requests(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    data_dir = tmp_path / "data"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pair_harness.desktop_backend",
        "--demo",
        "--project",
        str(tmp_path),
        "--data-dir",
        str(data_dir),
        cwd=root,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        ready = await _read_json_line(process.stdout)
        assert ready["kind"] == "event"
        assert ready["event"] == "backend.ready"

        process.stdin.write(b"not-json\n")
        await process.stdin.drain()
        protocol_error = await _read_json_line(process.stdout)
        assert protocol_error["kind"] == "error"
        assert protocol_error["error"]["code"] == "invalid_json"

        process.stdin.write(
            (json.dumps(
                {
                    "kind": "request",
                    "id": "bootstrap-1",
                    "method": "app.bootstrap",
                    "params": {},
                },
                ensure_ascii=False,
            ) + "\n").encode("utf-8")
        )
        await process.stdin.drain()
        bootstrap = await _read_json_line(process.stdout)
        assert bootstrap["kind"] == "response"
        assert bootstrap["id"] == "bootstrap-1"
        assert bootstrap["ok"] is True
        assert bootstrap["result"]["projects"]

        process.stdin.write(
            (json.dumps(
                {
                    "kind": "request",
                    "id": "shutdown-1",
                    "method": "app.shutdown",
                    "params": {},
                }
            ) + "\n").encode("utf-8")
        )
        await process.stdin.drain()
        shutdown = await _read_json_line(process.stdout)
        assert shutdown["ok"] is True
        await asyncio.wait_for(process.wait(), timeout=10)
        assert process.returncode == 0
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
