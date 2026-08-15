"""O3.2：角色适配器提示词装配与委派解析。

用本地假 HTTP 服务（http.server 后台线程）覆盖：
- 提示词装配内容（角色卡、搭档表达配置、进度/结果摘要注入、历史消息）；
- 三种输出形态：纯聊天、任务委派（task）、修改（amendment）；
- 解析失败直接暴露，不能把空输出变成省略号或其他占位台词；
- client 生命周期：复用、超时、关闭。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal

import pytest

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import (
    CharacterProgressSummary,
    CharacterResultSummary,
    CharacterTurn,
    DialogueRequest,
    Message,
    MessageKind,
    MessageSource,
    ProjectRuntimeContext,
    TaskAmendmentDraft,
    TaskRequestDraft,
)

PAIR_ID = "phainon_ancient_machine"


class _FakeChatHandler(BaseHTTPRequestHandler):
    """记录请求体；按脚本顺序回复（流式 chunk 或完整 JSON）。"""

    scripts: list[dict] = []
    captured: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).captured.append(body)
        script = type(self).scripts.pop(0)
        if script.get("stream"):
            lines = []
            for chunk in script["chunks"]:
                delta_payload = chunk if isinstance(chunk, dict) else {"content": chunk}
                data = json.dumps(
                    {"choices": [{"delta": delta_payload}]}, ensure_ascii=False
                )
                lines.append(f"data: {data}\n")
            lines.append("data: [DONE]\n")
            content = "".join(lines).encode("utf-8")
        else:
            content = json.dumps(script["json"], ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def fake_chat_server(monkeypatch: pytest.MonkeyPatch):
    _FakeChatHandler.scripts = []
    _FakeChatHandler.captured = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # httpx 默认 trust_env：本机系统代理会把 127.0.0.1 请求转发到代理，
    # 代理无法回连本机端口而返回 502——测试必须绕开代理
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def make_model(base_url: str) -> OpenAICompatibleDialogueModel:
    return OpenAICompatibleDialogueModel(
        base_url=base_url,
        api_key="test-key",
        model="test-model",
    )


def make_request(
    *,
    text: str = "帮我把报告整理好",
    result_status: str | None = None,
    runtime_mode: Literal["chat", "collaboration"] | None = None,
) -> DialogueRequest:
    user = Message(
        conversation_id="c",
        pair_id=PAIR_ID,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text=text,
    )
    previous_character = Message(
        conversation_id="c",
        pair_id=PAIR_ID,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text="好，我陪着你弄。",
    )
    result = None
    if result_status is not None:
        result = CharacterResultSummary(
            task_id="t-1",
            status=result_status,
            summary="报告已生成",
            user_visible_changes=("report.md",),
        )
    return DialogueRequest(
        pair_id=PAIR_ID,
        conversation_id="c",
        user_message=user,
        recent_messages=(previous_character,),
        progress_summary=CharacterProgressSummary(
            current_step="正在整理报告数据",
            completed_steps=2,
            total_steps=3,
        ),
        result_summary=result,
        runtime_context=(
            ProjectRuntimeContext(
                project_name="HSR Partner Harness",
                project_abs_dir=r"E:\AI\HSR Partner Harness",
                conversation_mode=runtime_mode,
            )
            if runtime_mode is not None
            else None
        ),
    )


async def run_turn(model: OpenAICompatibleDialogueModel, request: DialogueRequest) -> CharacterTurn:
    events = [event async for event in model.stream_reply(request)]
    final = [event for event in events if event.type == "character.final"]
    assert len(final) == 1
    return final[0].turn


@pytest.mark.asyncio
async def test_prompt_assembly_injects_role_card_partner_and_summaries(
    fake_chat_server: str,
) -> None:
    """提示词装配：system 含角色卡、搭档表达配置与输出约定；历史消息与
    进度/结果摘要注入；最后一条是用户消息。"""
    _FakeChatHandler.scripts.append({"stream": True, "chunks": ["这就去办。"]})
    model = make_model(fake_chat_server)
    request = make_request(result_status="completed")

    turn = await run_turn(model, request)
    assert turn.speech == "这就去办。"

    body = _FakeChatHandler.captured[0]
    messages = body["messages"]
    system = messages[0]["content"]
    # 角色卡（config/prompts/characters/phainon.md）
    assert "白厄" in system and "翁法罗斯" in system
    # 搭档（助手）表达配置：按 pair_id 从 config/pairs 加载
    assert "神秘的古代机械" in system
    # 输出格式约定（delegation JSON 形态与 delegate 自报字段）
    assert '"type": "task"' in system and '"type": "amendment"' in system
    assert "delegate" in system
    # 近期角色对话：character → assistant
    assert {"role": "assistant", "content": "好，我陪着你弄。"} in messages
    # 进度与结果摘要注入
    assert any(
        m["role"] == "system" and "任务进度" in m["content"] and "已完成：2/3" in m["content"]
        for m in messages
    )
    assert any(
        m["role"] == "system" and "任务结果" in m["content"] and "report.md" in m["content"]
        for m in messages
    )
    # 最后一条是用户消息
    assert messages[-1] == {"role": "user", "content": "帮我把报告整理好"}
    assert body["model"] == "test-model"


@pytest.mark.asyncio
async def test_plain_chat_output_yields_no_delegation(fake_chat_server: str) -> None:
    _FakeChatHandler.scripts.append(
        {"stream": True, "chunks": ["好", "啊，", "听你的。"]}
    )
    model = make_model(fake_chat_server)

    turn = await run_turn(model, make_request(text="今天有点累，陪我聊聊。"))
    assert turn.speech == "好啊，听你的。"
    assert turn.delegation is None


@pytest.mark.asyncio
async def test_missing_delegation_is_not_synthesized_from_user_keywords(
    fake_chat_server: str,
) -> None:
    """模型漏委派时不能靠关键词猜测并伪造一次助手任务。"""
    _FakeChatHandler.scripts.append(
        {"stream": True, "chunks": ['{"speech":"我来帮你处理。"}']}
    )
    model = make_model(fake_chat_server)
    request = make_request(text="请帮我删除 notes.txt 文件")

    turn = await run_turn(model, request)
    assert turn.delegation is None
    assert turn.speech == "我来帮你处理。"


@pytest.mark.asyncio
async def test_placeholder_speech_fails_instead_of_becoming_a_delegation_reply(
    fake_chat_server: str,
) -> None:
    """模型只返回省略号时必须报错，不能伪造成委派成功。"""
    _FakeChatHandler.scripts.append(
        {"stream": True, "chunks": ['{"speech":"……"}']}
    )
    model = make_model(fake_chat_server)

    with pytest.raises(ValueError, match="占位标点"):
        await run_turn(
            model,
            make_request(
                text="嗯，今天的话，我想陪你看看这个项目到底是做什么的。",
                runtime_mode="collaboration",
            ),
        )


@pytest.mark.asyncio
async def test_result_turn_passes_through_verbatim(fake_chat_server: str) -> None:
    """结果轮台词原样放行：代码不再改写，成败表述交给模型自己。"""
    _FakeChatHandler.scripts.append(
        {"stream": True, "chunks": ['{"speech":"我已经把文件删掉了。"}']}
    )
    model = make_model(fake_chat_server)

    turn = await run_turn(model, make_request(result_status="failed"))

    assert turn.delegation is None
    assert turn.speech == "我已经把文件删掉了。"


@pytest.mark.asyncio
async def test_returned_reasoning_is_kept_separate_from_speech(fake_chat_server: str) -> None:
    _FakeChatHandler.scripts.append(
        {
            "stream": True,
            "chunks": [
                {"reasoning_content": "先判断这是普通聊天。"},
                {"content": '{"speech":"坐下歇一会儿，我陪你。"}'},
            ],
        }
    )
    model = make_model(fake_chat_server)

    turn = await run_turn(model, make_request(text="今天有点累，陪我聊聊。"))

    assert turn.speech == "坐下歇一会儿，我陪你。"
    assert turn.reasoning == "先判断这是普通聊天。"
    assert "先判断" not in turn.speech


@pytest.mark.asyncio
async def test_task_delegation_json_output(fake_chat_server: str) -> None:
    """delegation.type == "task" → TaskRequestDraft（含 constraints）。"""
    _FakeChatHandler.scripts.append(
        {
            "stream": True,
            "chunks": [
                "行，这事交给古代机械。",
                '\n{"speech": "古代机械，把报告整理好。", "delegation": '
                '{"type": "task", "instructions": "整理报告", '
                '"constraints": ["markdown"]}}',
            ],
        }
    )
    model = make_model(fake_chat_server)

    turn = await run_turn(model, make_request())
    assert turn.speech == "古代机械，把报告整理好。"
    assert isinstance(turn.delegation, TaskRequestDraft)
    assert turn.delegation.instructions == "整理报告"
    assert turn.delegation.constraints == ("markdown",)


@pytest.mark.asyncio
async def test_amendment_delegation_json_output(fake_chat_server: str) -> None:
    """delegation.type == "amendment" → TaskAmendmentDraft。"""
    _FakeChatHandler.scripts.append(
        {
            "stream": True,
            "chunks": [
                '{"speech": "换个方式，别用那种工具。", "delegation": '
                '{"type": "amendment", "instructions": "改用 shutil", '
                '"target_task_id": "t-9", "revision": 2}}',
            ],
        }
    )
    model = make_model(fake_chat_server)

    turn = await run_turn(model, make_request())
    assert isinstance(turn.delegation, TaskAmendmentDraft)
    assert turn.delegation.instructions == "改用 shutil"
    assert turn.delegation.target_task_id == "t-9"
    assert turn.delegation.revision == 2


@pytest.mark.asyncio
async def test_broken_json_fails_instead_of_becoming_plain_speech(
    fake_chat_server: str,
) -> None:
    """损坏的 JSON 输出直接失败，不能把半截协议当成成功回复。"""
    _FakeChatHandler.scripts.append(
        {
            "stream": True,
            "chunks": [
                '\n{"speech": "古代机械，把报告整理好。", "delegation": {"type": "task", '
            ],
        }
    )
    model = make_model(fake_chat_server)

    with pytest.raises(ValueError, match="可用 speech"):
        await run_turn(model, make_request())


@pytest.mark.asyncio
async def test_prose_with_json_tail_parses_and_prose_braces_kept(
    fake_chat_server: str,
) -> None:
    """台词后附完整 JSON → 结构化；普通台词中的花括号不受剥离影响。"""
    _FakeChatHandler.scripts.append(
        {
            "stream": True,
            "chunks": [
                "我先看看",
                '\n{"speech": "看过了。", "delegation": {"type": "task", '
                '"instructions": "执行"}}',
            ],
        }
    )
    model = make_model(fake_chat_server)

    turn = await run_turn(model, make_request())
    # 台词不再被代码补全，原样保留模型输出
    assert turn.speech == "看过了。"
    assert isinstance(turn.delegation, TaskRequestDraft)

    _FakeChatHandler.scripts.append({"stream": True, "chunks": ["用 {shutil} 库。"]})
    turn = await run_turn(model, make_request())
    assert turn.speech == "用 {shutil} 库。"
    assert turn.delegation is None


@pytest.mark.asyncio
async def test_client_reused_across_calls_and_closed(fake_chat_server: str) -> None:
    """client 生命周期：多次调用复用同一 client；aclose 关闭自建 client，
    注入的外部 client 交由调用方关闭。"""
    _FakeChatHandler.scripts.append({"stream": True, "chunks": ["第一句。"]})
    _FakeChatHandler.scripts.append({"stream": True, "chunks": ["第二句。"]})
    model = make_model(fake_chat_server)

    await run_turn(model, make_request())
    first_client = model._client
    assert first_client is not None

    await run_turn(model, make_request())
    assert model._client is first_client
    assert len(_FakeChatHandler.captured) == 2

    await model.aclose()
    assert model._client is None
    # 再次调用会重建 client（不报错、不复用已关闭的连接池）
    _FakeChatHandler.scripts.append({"stream": True, "chunks": ["第三句。"]})
    turn = await run_turn(model, make_request())
    assert turn.speech == "第三句。"
    assert model._client is not None and model._client is not first_client


@pytest.mark.asyncio
async def test_injected_client_not_closed_by_aclose(fake_chat_server: str) -> None:
    """注入的 client 由调用方管理：aclose 后仍可用。"""
    import httpx

    _FakeChatHandler.scripts.append({"stream": True, "chunks": ["注入。"]})
    external = httpx.AsyncClient(base_url=fake_chat_server)
    model = OpenAICompatibleDialogueModel(
        base_url=fake_chat_server,
        api_key="k",
        model="m",
        client=external,
    )

    turn = await run_turn(model, make_request())
    assert turn.speech == "注入。"
    await model.aclose()
    assert model._client is external
    # 外部 client 仍可正常请求
    response = await external.get("/")
    assert response.status_code == 501  # 假服务未实现 GET，但连接可用
    await external.aclose()
