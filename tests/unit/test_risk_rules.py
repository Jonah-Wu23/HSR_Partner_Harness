from pathlib import Path

import pytest

from pair_harness.core.contracts import PendingOperation
from pair_harness.core.risk_rules import load_risk_rules, match_high_risk


@pytest.fixture
def rules():
    return load_risk_rules(Path(__file__).resolve().parents[2] / "config" / "risk_rules.yaml")


def _shell(command: str) -> PendingOperation:
    return PendingOperation(tool_kind="shell", command=command)


def _file_write(path: str) -> PendingOperation:
    return PendingOperation(tool_kind="file_write", paths=[path])


@pytest.mark.parametrize(
    ("op", "label"),
    [
        (PendingOperation(tool_kind="file_delete", paths=["x.txt"]), "file_delete"),
        (_shell("rm -rf build"), "删除"),
        (_shell("git push origin main --force"), "git"),
        (_shell("curl https://example.com"), "网络"),
        (_shell("pip install requests"), "依赖"),
        (PendingOperation(tool_kind="patch", patch_file_count=6), "批量"),
        (_file_write("config/.env"), "敏感"),
        # Windows 分隔符、含 .. 的相对路径与正斜杠绝对路径都按 POSIX 形态匹配
        (_file_write("C:\\proj\\.env"), "敏感"),
        (_file_write("src/../.env"), "敏感"),
        (_file_write("C:/proj/.env"), "敏感"),
    ],
)
def test_high_risk_operation_reports_matched_rule(rules, op, label) -> None:
    assert label in match_high_risk(op, rules)


@pytest.mark.parametrize(
    "op",
    [
        _file_write("x.txt"),
        _file_write("C:\\proj\\app.py"),
        _shell("ls -la"),
        PendingOperation(tool_kind="patch", patch_file_count=5),
    ],
)
def test_regular_operation_is_not_high_risk(rules, op) -> None:
    assert match_high_risk(op, rules) is None
