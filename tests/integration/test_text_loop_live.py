import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import ApprovalMode, MessageKind, ProjectRef
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import make_context, unexpected_approval

# 真实 DeepSeek 对话与打包 Reasonix 的全链路联调。在进程环境里设置
# RUN_LIVE_DEEPSEEK=1 才会运行，凭据 PAIR_HARNESS_DIALOGUE_* 可放在仓库根 .env：
#   .\.venv\Scripts\python.exe -m pytest -q -m live tests\integration\test_text_loop_live.py
pytestmark = pytest.mark.live

_REQUIRED_ENV = (
    "PAIR_HARNESS_DIALOGUE_BASE_URL",
    "PAIR_HARNESS_DIALOGUE_API_KEY",
    "PAIR_HARNESS_DIALOGUE_MODEL",
)


@pytest.fixture(scope="module")
def live_env() -> None:
    if os.getenv("RUN_LIVE_DEEPSEEK") != "1":
        pytest.skip("未设置 RUN_LIVE_DEEPSEEK=1")
    # 确定运行 live 用例后才读取 .env，跳过时不向测试进程注入任何变量
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
    if missing:
        pytest.skip(f"缺少真实凭据: {', '.join(missing)}")


@pytest.fixture(scope="module")
def smoke_project(tmp_path_factory) -> Path:
    project = tmp_path_factory.mktemp("live-smoke")
    # 在 git 仓库里 Reasonix 的差异展示更完整；没有 git 也可运行
    git = shutil.which("git")
    if git:
        subprocess.run(
            [git, "init", "-q", str(project)],
            check=False,
            capture_output=True,
        )
    return project


def run_cli(project: Path, message: str, conversation: str, *extra: str) -> subprocess.CompletedProcess:
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
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
        env=child_env,
    )


def test_live_cli_creates_file_and_resumes_session(
    live_env: None, smoke_project: Path
) -> None:
    """第一次运行创建 hello.txt；同一会话二次运行恢复旧聊天；新会话另开编程会话。"""
    first = run_cli(
        smoke_project,
        "请严格通过结构化 delegation 让古代机械创建 hello.txt，内容为 hello",
        conversation="live-smoke",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    hello = smoke_project / "hello.txt"
    assert hello.is_file(), f"hello.txt 未创建\n{first.stdout}\n{first.stderr}"
    assert "hello" in hello.read_text(encoding="utf-8", errors="replace").lower()

    # 同一会话：恢复旧聊天（输出带恢复标记）并复用 ACP 会话。恢复后模型记得
    # 上次的执行结果，纯查看请求可能只闲聊不委派，因此用必须真实执行的追加请求。
    second = run_cli(
        smoke_project,
        "请严格通过结构化 delegation 让古代机械在 hello.txt 末尾追加一行 world，其他内容保持不变",
        conversation="live-smoke",
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert "恢复旧聊天" in second.stdout, f"未恢复旧聊天\n{second.stdout}\n{second.stderr}"
    content = hello.read_text(encoding="utf-8", errors="replace")
    assert "world" in content.lower(), f"resume 后未追加 world\n{content}\n{second.stdout}\n{second.stderr}"

    # 新会话不继承旧编程会话的上下文（hello.txt 已存在，需要自行检查）。
    # 用明确委派句式降低真实模型闲聊不委派的概率。
    fresh = run_cli(
        smoke_project,
        "请严格通过结构化 delegation 让古代机械检查当前目录下是否存在 hello.txt，并报告其内容",
        conversation="live-smoke-fresh",
    )
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    # 新会话没有历史快照，误复用旧编程会话时 CLI 会打印「恢复旧聊天」
    assert "恢复旧聊天" not in fresh.stdout, (
        f"新会话不应恢复旧聊天\n{fresh.stdout}\n{fresh.stderr}"
    )


@pytest.mark.asyncio
async def test_live_deepseek_roleplay_boundaries_are_stable(
    live_env: None, tmp_path: Path
) -> None:
    """固定三场景重复两轮：闲聊、委派、失败结果均遵守职责边界。"""
    model = OpenAICompatibleDialogueModel(
        base_url=os.environ["PAIR_HARNESS_DIALOGUE_BASE_URL"],
        api_key=os.environ["PAIR_HARNESS_DIALOGUE_API_KEY"],
        model=os.environ["PAIR_HARNESS_DIALOGUE_MODEL"],
        temperature=1.0,
    )
    try:
        for iteration in range(2):
            chat_engine = ScriptedCodingEngine()
            chat = _live_orchestrator(model, chat_engine)
            chat_outcome = await chat.handle_character_input(
                conversation_id=f"chat-{iteration}",
                text="今天有点累，陪我聊聊奥赫玛的日常。",
                context=_live_context(f"chat-{iteration}", tmp_path),
            )
            assert chat_outcome.receipt is None
            assert chat_engine.requests == []

            task_engine = ScriptedCodingEngine()
            task = _live_orchestrator(model, task_engine)
            task_outcome = await task.handle_character_input(
                conversation_id=f"task-{iteration}",
                text="请帮我创建 notes.txt 文件，内容写一行 hello。",
                context=_live_context(f"task-{iteration}", tmp_path),
            )
            assert task_outcome.receipt is not None
            assert task_outcome.receipt.status == "completed"
            assert len(task_engine.requests) == 1

            failed_engine = ScriptedCodingEngine(fail_tool=True)
            failed = _live_orchestrator(model, failed_engine)
            failed_outcome = await failed.handle_character_input(
                conversation_id=f"failed-{iteration}",
                text="请帮我删除 missing.txt 文件。",
                context=_live_context(f"failed-{iteration}", tmp_path),
            )
            assert failed_outcome.receipt is not None
            assert failed_outcome.receipt.status == "failed"
            last_character = [
                message
                for message in failed_outcome.messages
                if message.kind == MessageKind.CHARACTER_SPEECH
            ][-1]
            assert "做完了" not in last_character.text
            assert "已经完成" not in last_character.text

            # DeepSeek 结构化角色回合为保证 JSON 委派可解析会关闭 thinking；
            # 供应商若返回 reasoning，运行时仍需保留，未返回时不伪造字段。
            all_messages = (
                chat_outcome.messages
                + task_outcome.messages
                + failed_outcome.messages
            )
            reasoning_values = [
                message.payload.get("reasoning", "")
                for message in all_messages
                if message.kind == MessageKind.CHARACTER_SPEECH
            ]
            assert all(isinstance(value, str) for value in reasoning_values)
    finally:
        await model.aclose()


def _live_orchestrator(
    model: OpenAICompatibleDialogueModel,
    engine: ScriptedCodingEngine,
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        dialogue_model=model,
        coding_engine=engine,
        store=None,
        approval_callback=unexpected_approval,
    )


def _live_context(conversation_id: str, project_root: Path):
    return make_context(
        ProjectRef(project_id="live-role", name="live-role", root_path=str(project_root)),
        conversation_id=conversation_id,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
