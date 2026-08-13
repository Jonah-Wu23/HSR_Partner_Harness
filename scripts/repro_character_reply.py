"""复现「让角色介绍项目」的对话模型流：确认 stream_reply 是否产出 character.final。

使用仓库根 .env 的真实 DeepSeek 配置（短请求，max_tokens 由模型决定）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pair_harness.cli import load_dotenv  # noqa: E402
from pair_harness.adapters.dialogue.openai_compatible import (  # noqa: E402
    OpenAICompatibleDialogueModel,
)
from pair_harness.config.providers import load_reasoning_preset  # noqa: E402
from pair_harness.core.contracts import (  # noqa: E402
    DialogueRequest,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageTarget,
    ProjectRuntimeContext,
)


async def main() -> None:
    load_dotenv(ROOT / ".env")
    import os

    base_url = os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL", "")
    api_key = os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY", "")
    model = os.getenv("PAIR_HARNESS_DIALOGUE_MODEL", "")
    print(f"model={model} base={base_url}")
    preset = load_reasoning_preset(base_url, model)
    print(f"preset: default_thinking={preset.default_thinking}")
    model_client = OpenAICompatibleDialogueModel(
        base_url=base_url,
        api_key=api_key,
        model=model,
        thinking=preset.default_thinking,
        reasoning_effort="auto",
        temperature=1.0,
    )
    user = Message(
        conversation_id="repro",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="介绍一下这个项目",
        target=MessageTarget.CHARACTER,
        origin=MessageOrigin.USER,
    )
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="repro",
        user_message=user,
        recent_messages=(),
        runtime_context=ProjectRuntimeContext(
            project_name="HSR Partner Harness",
            project_abs_dir=str(ROOT),
            local_time="2026-08-13 10:00:00",
            timezone="CST",
            conversation_mode="collaboration",
        ),
    )
    events = []
    async for event in model_client.stream_reply(request):
        events.append(event)
        print(f"[event] {event.type}")
        if event.type == "reasoning.delta":
            print("  reasoning:", (event.delta or "")[:80])
        elif event.type == "speech.delta":
            print("  speech:", event.delta)
        elif event.type == "character.final":
            turn = event.turn
            print("  speech_final:", repr(turn.speech))
            print("  delegation:", turn.delegation)
    print(f"\ntotal events: {len(events)}")


if __name__ == "__main__":
    asyncio.run(main())
