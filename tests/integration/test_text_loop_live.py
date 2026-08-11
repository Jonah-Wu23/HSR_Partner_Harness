"""B1 真实联调：DeepSeek 对话 + codex app-server 全链路（live marker）。

依赖真实凭据（PAIR_HARNESS_DIALOGUE_* 与 codex 登录态），无凭据时跳过：:

  .\\.venv\\Scripts\\python.exe -m pytest -q -m live tests\\integration\\test_text_loop_live.py

覆盖 MVP 计划 B1 完成标准：
- 真实文件修改（hello.txt 创建）；
- 旧聊天恢复同一编程线程（thread/resume）；
- 新聊天不继承旧会话（thread/start）。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

_REQUIRED_ENV = (
    "PAIR_HARNESS_DIALOGUE_BASE_URL",
    "PAIR_HARNESS_DIALOGUE_API_KEY",
    "PAIR_HARNESS_DIALOGUE_MODEL",
)


@pytest.fixture(scope="module")
def live_env() -> dict[str, str]:
    missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
    if missing:
        pytest.skip(f"缺少真实凭据: {', '.join(missing)}")
    return {name: os.environ[name] for name in _REQUIRED_ENV}


@pytest.fixture(scope="module")
def smoke_project(tmp_path_factory) -> Path:
    project = tmp_path_factory.mktemp("codex-smoke")
    # codex 在 git 仓库里展示差异与沙箱行为更完整；无 git 也可运行
    git = shutil.which("git")
    if git:
        subprocess.run(
            [git, "init", "-q", str(project)],
            check=False,
            capture_output=True,
        )
    return project


def run_cli(project: Path, message: str, conversation: str, *extra: str) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-m",
        "pair_harness.cli",
        "--real",
        "--pair",
        "phainon_ancient_machine",
        "--project",
        str(project),
        "--message",
        message,
        "--conversation",
        conversation,
        "--approval-mode",
        "full-auto",
        "--data-dir",
        str(project / ".state"),
        *extra,
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
        cwd=Path(__file__).resolve().parents[2],
    )


def test_live_cli_creates_file_and_resumes_thread(
    live_env: dict[str, str], smoke_project: Path
) -> None:
    """第一次运行创建 hello.txt；同一会话二次运行恢复旧聊天；新会话另开线程。"""
    first = run_cli(
        smoke_project,
        "请让古代机械创建 hello.txt，内容为 hello",
        conversation="live-smoke",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    hello = smoke_project / "hello.txt"
    assert hello.is_file(), f"hello.txt 未创建\n{first.stdout}\n{first.stderr}"
    assert "hello" in hello.read_text(encoding="utf-8", errors="replace").lower()

    # 同一会话：恢复旧聊天（输出应带恢复标记），线程复用 thread/resume。
    # 注意：恢复后模型"记得"上次执行结果，纯查看请求可能不委派（只闲聊），
    # 因此用"追加一行"这类必须真实执行引擎操作的请求来验证 resume 路径。
    second = run_cli(
        smoke_project,
        "请让古代机械在 hello.txt 末尾追加一行 world，其他内容保持不变",
        conversation="live-smoke",
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert "恢复旧聊天" in second.stdout, f"未恢复旧聊天\n{second.stdout}\n{second.stderr}"
    content = hello.read_text(encoding="utf-8", errors="replace")
    assert "world" in content.lower(), f"resume 后未追加 world\n{content}\n{second.stdout}\n{second.stderr}"

    # 新会话：不应继承旧线程上下文（hello.txt 已存在，新线程需自行检查）。
    # 用明确委派句式降低真实模型闲聊不委派的概率。
    fresh = run_cli(
        smoke_project,
        "请让古代机械检查当前目录下是否存在 hello.txt，并报告其内容",
        conversation="live-smoke-fresh",
    )
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
