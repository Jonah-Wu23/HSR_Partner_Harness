from pair_harness.core.contracts import ToolRun
from pair_harness.ui.tool_card import ToolCard


def run(status: str, summary: str) -> ToolRun:
    return ToolRun(
        tool_call_id="tool-1",
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn",
        sequence=1,
        status=status,
        title="pytest",
        summary=summary,
        details="full output",
    )


def test_tool_card_is_collapsed_and_updates_in_place(qtbot) -> None:
    card = ToolCard(run("running", "starting"))
    qtbot.addWidget(card)
    card.show()

    assert not card.expanded
    assert not card.details_label.isVisible()
    card.update_run(run("succeeded", "2 passed"))
    assert card.status_label.text() == "succeeded"
    assert card.summary_label.text() == "2 passed"

    card.toggle.click()
    assert card.expanded
    assert card.details_label.isVisible()

