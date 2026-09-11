"""V0.3.9 契约 §2：角色装配顺序中的聊天摘要与配对记忆模块。

契约出处：``.archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md`` §2（装配顺序与扫描源）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from pair_harness.character_cards.models import CharacterCard
from pair_harness.core.character_prompt_assembler import assemble_turn_prompt
from pair_harness.core.memory import MemoryScope, PairMemory
from pair_harness.core.summary import completed_summary, failed_summary

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _card() -> CharacterCard:
    card = CharacterCard(name="白厄", description="角色设定原文")
    return card


def _scope(**overrides) -> MemoryScope:
    values = {
        "account_id": "acc-1",
        "project_id": "proj-1",
        "pair_id": "phainon_ancient_machine",
        "character_ref": "builtin:phainon",
        "assistant_identity": "ancient_machine",
    }
    values.update(overrides)
    return MemoryScope(**values)


def _memory(memory_id: str, content: dict, *, status: str = "active") -> PairMemory:
    return PairMemory(
        memory_id=memory_id,
        scope=_scope(),
        content=content,
        status=status,
        updated_at=_NOW,
    )


def _summary(status: str = "completed"):
    if status == "failed":
        return failed_summary(
            summary_id="s1",
            conversation_id="conv-1",
            error_code="summary_timeout",
            error="provider timeout",
        )
    return completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m3",
        covers_message_count=3,
        content={"剧情": "两人在雨夜相遇", "约定": ["不再提旧事"]},
    )


def test_no_summary_no_memory_keeps_previous_module_set() -> None:
    result = assemble_turn_prompt(_card(), [])
    assert [module.kind for module in result.modules] == ["description"]
    assert result.diagnostics["summary"] == {
        "injected": False,
        "summary_id": None,
        "char_count": 0,
    }
    assert result.diagnostics["memory"] == {
        "injected": False,
        "count": 0,
        "memory_ids": [],
        "char_count": 0,
    }


def test_summary_and_memory_modules_follow_hsr_and_precede_triggers() -> None:
    card = CharacterCard(
        name="白厄",
        description="角色设定原文",
        system_prompt="系统提示",
    )
    result = assemble_turn_prompt(
        card,
        [],
        summary=_summary(),
        memories=(_memory("mem-1", {"喜好": "安静"}),),
    )
    kinds = [module.kind for module in result.modules]
    assert kinds == ["description", "system_prompt", "chat_summary", "pair_memory"]
    summary_module = result.modules[kinds.index("chat_summary")]
    memory_module = result.modules[kinds.index("pair_memory")]
    assert summary_module.title == "聊天摘要"
    assert summary_module.source_field == "summary:s1"
    assert memory_module.title == "配对记忆"
    # 模型内容原样呈现，不改写
    assert "两人在雨夜相遇" in summary_module.content
    assert "不再提旧事" in summary_module.content
    assert "安静" in memory_module.content
    # 字符区间覆盖新模块
    assert summary_module.char_start is not None and summary_module.char_end is not None
    assert result.system_text[summary_module.char_start : summary_module.char_end].startswith(
        "## 聊天摘要"
    )
    assert result.diagnostics["summary"]["injected"] is True
    assert result.diagnostics["summary"]["summary_id"] == "s1"
    assert result.diagnostics["memory"]["count"] == 1
    assert result.diagnostics["memory"]["memory_ids"] == ["mem-1"]


def test_event_trigger_stays_after_summary_and_memory() -> None:
    card = CharacterCard(
        name="白厄",
        description="角色设定原文",
        hsr=_hsr_with_trigger(),
    )
    result = assemble_turn_prompt(
        card,
        [],
        turn_index=1,
        summary=_summary(),
        memories=(_memory("mem-1", {"喜好": "安静"}),),
    )
    kinds = [module.kind for module in result.modules]
    assert kinds[-1] == "hsr.event_trigger"
    assert kinds.index("chat_summary") < kinds.index("hsr.event_trigger")
    assert kinds.index("pair_memory") < kinds.index("hsr.event_trigger")


def _hsr_with_trigger():
    from pair_harness.character_cards.models import HsrExtension

    return HsrExtension(
        event_system={
            "任务": {
                "runtime_trigger": {"kind": "turn", "turn": 1},
                "content": "第一回合事件原文",
            }
        }
    )


def test_failed_summary_is_not_injected() -> None:
    result = assemble_turn_prompt(_card(), [], summary=_summary("failed"))
    assert "chat_summary" not in [module.kind for module in result.modules]
    assert result.diagnostics["summary"]["injected"] is False


def test_deleted_memory_is_not_injected_but_active_is() -> None:
    result = assemble_turn_prompt(
        _card(),
        [],
        memories=(
            _memory("mem-active", {"保留": "是"}),
            _memory("mem-deleted", {"保留": "否"}, status="deleted"),
        ),
    )
    assert result.diagnostics["memory"]["memory_ids"] == ["mem-active"]
    memory_module = next(
        module for module in result.modules if module.kind == "pair_memory"
    )
    assert "是" in memory_module.content
    assert "否" not in memory_module.content


def test_empty_summary_or_memory_content_produces_no_module() -> None:
    empty_summary = completed_summary(
        summary_id="s-empty",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m1",
        covers_message_count=1,
        content={},
    )
    result = assemble_turn_prompt(
        _card(),
        [],
        summary=empty_summary,
        memories=(_memory("mem-empty", {}),),
    )
    kinds = [module.kind for module in result.modules]
    assert "chat_summary" not in kinds
    assert "pair_memory" not in kinds
    assert result.diagnostics["summary"]["injected"] is False
    assert result.diagnostics["memory"]["injected"] is False


def test_summary_and_memory_do_not_leak_into_assistant_brief() -> None:
    """摘要与记忆只进角色 system 段；本模块不产出助手文本。"""
    result = assemble_turn_prompt(
        _card(),
        [],
        summary=_summary(),
        memories=(_memory("mem-1", {"喜好": "安静"}),),
    )
    assert "助手" not in result.system_text
    assert result.diagnostics["summary"]["summary_id"] == "s1"
