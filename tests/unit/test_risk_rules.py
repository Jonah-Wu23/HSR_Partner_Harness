from pathlib import Path

import pytest

from pair_harness.core.contracts import PendingOperation
from pair_harness.core.risk_rules import load_risk_rules, match_high_risk


@pytest.fixture
def rules():
    return load_risk_rules(Path(__file__).resolve().parents[2] / "config" / "risk_rules.yaml")


def test_file_delete_is_high_risk(rules) -> None:
    op = PendingOperation(tool_kind="file_delete", paths=["x.txt"], summary="删除文件")
    assert match_high_risk(op, rules) is not None


def test_file_write_is_not_high_risk_by_default(rules) -> None:
    op = PendingOperation(tool_kind="file_write", paths=["x.txt"], summary="写入文件")
    assert match_high_risk(op, rules) is None


def test_rm_command_is_high_risk(rules) -> None:
    op = PendingOperation(tool_kind="shell", command="rm -rf build", summary="删除")
    assert "删除" in match_high_risk(op, rules)


def test_git_push_force_is_high_risk(rules) -> None:
    op = PendingOperation(tool_kind="shell", command="git push origin main --force", summary="推送")
    assert "git" in match_high_risk(op, rules)


def test_curl_is_high_risk(rules) -> None:
    op = PendingOperation(tool_kind="shell", command="curl https://example.com", summary="下载")
    assert "网络" in match_high_risk(op, rules)


def test_pip_install_is_high_risk(rules) -> None:
    op = PendingOperation(tool_kind="shell", command="pip install requests", summary="安装依赖")
    assert "依赖" in match_high_risk(op, rules)


def test_safe_ls_is_not_high_risk(rules) -> None:
    op = PendingOperation(tool_kind="shell", command="ls -la", summary="列出文件")
    assert match_high_risk(op, rules) is None


def test_patch_file_count_boundary(rules) -> None:
    op5 = PendingOperation(tool_kind="patch", patch_file_count=5, summary="改 5 个文件")
    op6 = PendingOperation(tool_kind="patch", patch_file_count=6, summary="改 6 个文件")
    assert match_high_risk(op5, rules) is None
    assert "批量" in match_high_risk(op6, rules)


def test_sensitive_path_matches(rules) -> None:
    op = PendingOperation(tool_kind="file_write", paths=["config/.env"], summary="写环境变量")
    assert "敏感" in match_high_risk(op, rules)
