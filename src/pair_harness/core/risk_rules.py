from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from .contracts import PendingOperation


@dataclass(frozen=True)
class ShellRule:
    id: str
    label: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class RiskRules:
    version: int
    high_risk_tool_kinds: frozenset[str]
    shell_rules: tuple[ShellRule, ...]
    patch_max_files: int
    sensitive_paths: tuple[str, ...]


def load_risk_rules(path: Path) -> RiskRules:
    """从 YAML 加载高风险规则表。"""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RiskRules(
        version=int(data.get("version", 1)),
        high_risk_tool_kinds=frozenset(data.get("high_risk_tool_kinds", [])),
        shell_rules=tuple(
            ShellRule(
                id=r["id"],
                label=r["label"],
                patterns=tuple(r.get("patterns", [])),
            )
            for r in data.get("shell_rules", [])
        ),
        patch_max_files=int(data.get("patch_max_files", 5)),
        sensitive_paths=tuple(data.get("sensitive_paths", [])),
    )


def _default_rules_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "risk_rules.yaml"


def default_risk_rules() -> RiskRules:
    """加载项目默认规则表。"""
    return load_risk_rules(_default_rules_path())


def match_high_risk(op: PendingOperation, rules: RiskRules) -> str | None:
    """返回命中规则的中文 label；未命中返回 None。"""
    if op.tool_kind in rules.high_risk_tool_kinds:
        return f"高风险工具类型: {op.tool_kind}"

    if op.tool_kind == "shell" and op.command:
        for rule in rules.shell_rules:
            for pattern in rule.patterns:
                if re.search(pattern, op.command, re.IGNORECASE):
                    return rule.label

    if op.tool_kind == "patch" and op.patch_file_count is not None:
        if op.patch_file_count > rules.patch_max_files:
            return f"批量 patch: {op.patch_file_count} 个文件"

    for path in op.paths:
        for pattern in rules.sensitive_paths:
            if fnmatch(path, pattern):
                return f"敏感路径: {path}"

    return None
