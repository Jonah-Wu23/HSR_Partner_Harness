from pair_harness.ui.approval_bar import ApprovalBar


def test_approval_bar_is_hidden_by_default(qtbot) -> None:
    bar = ApprovalBar()
    qtbot.addWidget(bar)
    # 未收到任何审批请求前保持隐藏
    assert not bar.isVisible()


def test_request_expands_with_summary_reason_and_three_buttons(qtbot) -> None:
    bar = ApprovalBar()
    qtbot.addWidget(bar)
    bar.enqueue_request("approval-1", "删除 build 目录", "删除类命令")
    assert bar.isVisible()
    # O1.7：摘要与真实理由都要展示
    assert "删除 build 目录" in bar.summary_label.text()
    assert "删除类命令" in bar.summary_label.text()
    assert bar.allow_button.isVisible()
    assert bar.allow_for_conversation_button.isVisible()
    assert bar.deny_button.isVisible()


def test_allow_click_emits_decision_with_id_and_hides(qtbot) -> None:
    bar = ApprovalBar()
    qtbot.addWidget(bar)
    bar.enqueue_request("approval-1", "删除 build 目录", "")
    decisions = []
    bar.decided.connect(lambda approval_id, decision: decisions.append((approval_id, decision)))
    bar.allow_button.click()
    # O1.7：信号携带 approval_id 与决策
    assert decisions == [("approval-1", "allow")]
    assert not bar.isVisible()


def test_allow_for_conversation_click_emits_correct_decision(qtbot) -> None:
    bar = ApprovalBar()
    qtbot.addWidget(bar)
    bar.enqueue_request("approval-1", "执行 pip install", "")
    decisions = []
    bar.decided.connect(lambda approval_id, decision: decisions.append((approval_id, decision)))
    bar.allow_for_conversation_button.click()
    assert decisions == [("approval-1", "allow_for_conversation")]
    assert not bar.isVisible()


def test_deny_click_emits_correct_decision(qtbot) -> None:
    bar = ApprovalBar()
    qtbot.addWidget(bar)
    bar.enqueue_request("approval-1", "git reset --hard", "")
    decisions = []
    bar.decided.connect(lambda approval_id, decision: decisions.append((approval_id, decision)))
    bar.deny_button.click()
    assert decisions == [("approval-1", "deny")]
    assert not bar.isVisible()


def test_requests_are_queued_and_shown_one_at_a_time(qtbot) -> None:
    bar = ApprovalBar()
    qtbot.addWidget(bar)
    bar.enqueue_request("approval-1", "操作一", "")
    bar.enqueue_request("approval-2", "操作二", "")
    assert bar.pending_count == 2
    assert "操作一" in bar.summary_label.text()
    decisions = []
    bar.decided.connect(lambda approval_id, decision: decisions.append((approval_id, decision)))
    bar.allow_button.click()
    assert decisions == [("approval-1", "allow")]
    assert bar.isVisible()
    assert "操作二" in bar.summary_label.text()
    bar.allow_button.click()
    assert decisions == [("approval-1", "allow"), ("approval-2", "allow")]
    assert not bar.isVisible()


def test_review_mode_shows_verdict_without_buttons(qtbot) -> None:
    bar = ApprovalBar()
    qtbot.addWidget(bar)
    bar.show_review("审查中… 删除类命令")
    assert bar.isVisible()
    assert not bar.allow_button.isVisible()
    assert not bar.allow_for_conversation_button.isVisible()
    assert not bar.deny_button.isVisible()
    assert "审查中" in bar.verdict_label.text()

    bar.show_review("审查结果：否决（危险，建议改用 shutil）")
    assert "否决" in bar.verdict_label.text()
