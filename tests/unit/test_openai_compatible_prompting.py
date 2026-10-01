from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
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
)

PAIR_ID = "phainon_ancient_machine"


class _FakeChatHandler(BaseHTTPRequestHandler):
    """记录请求体，按脚本顺序以 Chat Completions SSE 流回复。"""

    scripts: list[dict] = []
    captured: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).captured.append(body)
        script = type(self).scripts.pop(0)
        lines = []
        for chunk in script["chunks"]:
            data = json.dumps({"choices": [{"delta": {"content": chunk}}]}, ensure_ascii=False)
            lines.append(f"data: {data}\n\n")
        lines.append("data: [DONE]\n\n")
        content = "".join(lines).encode("utf-8")
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
    # httpx 默认 trust_env：终端里的 socks5:// 代理变量会让 AsyncClient 构造时因缺
    # socksio 抛 ImportError；没有代理变量时 Windows 会读系统代理，把 127.0.0.1
    # 请求转给代理。测试内清除代理变量并用 NO_PROXY 放行回环地址。
    for var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
                "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
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


def make_request(*, result_status: str | None = None) -> DialogueRequest:
    user = Message(
        conversation_id="c",
        pair_id=PAIR_ID,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="帮我把报告整理好",
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
        ),
        result_summary=result,
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
    _FakeChatHandler.scripts.append({"chunks": ['{"speech":"这就去办。","delegate":false}']})
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
        m["role"] == "system" and "任务进度" in m["content"] and "已完成步骤：2" in m["content"]
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
async def test_client_reused_across_calls_and_rebuilt_after_aclose(fake_chat_server: str) -> None:
    _FakeChatHandler.scripts.append({"chunks": ['{"speech":"第一句。"}']})
    _FakeChatHandler.scripts.append({"chunks": ['{"speech":"第二句。"}']})
    model = make_model(fake_chat_server)

    await run_turn(model, make_request())
    first_client = model._client
    assert first_client is not None

    await run_turn(model, make_request())
    assert model._client is first_client
    assert len(_FakeChatHandler.captured) == 2

    await model.aclose()
    assert model._client is None
    # aclose 后再次调用会重建 client
    _FakeChatHandler.scripts.append({"chunks": ['{"speech":"第三句。"}']})
    turn = await run_turn(model, make_request())
    assert turn.speech == "第三句。"
    assert model._client is not None and model._client is not first_client


@pytest.mark.asyncio
async def test_injected_client_not_closed_by_aclose(fake_chat_server: str) -> None:
    _FakeChatHandler.scripts.append({"chunks": ['{"speech":"注入。"}']})
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
