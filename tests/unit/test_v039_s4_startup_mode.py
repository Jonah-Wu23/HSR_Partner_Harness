"""V0.3.9 S4 修复批次：Sidecar 启动模式判定单元测试（V039-S4-002）。

接线只由显式声明决定：--real → explicit_real，--demo → explicit_demo，
两者都没声明 → default_real（真实接线，没有 Key 也能启动并进入首次引导）；
同时声明两个模式是矛盾输入，如实报错而不挑一个执行。
"""

from __future__ import annotations

import argparse

import pytest

import pair_harness.desktop_backend.__main__ as backend_main
from pair_harness.desktop_backend.application_service import ServiceError


def _mode_args(*, real: bool = False, demo: bool = False) -> argparse.Namespace:
    return argparse.Namespace(real=real, demo=demo)


def test_explicit_real() -> None:
    """显式 --real：真实接线，来源如实标注。"""
    assert backend_main._resolve_startup_mode(_mode_args(real=True)) == (
        False,
        "explicit_real",
    )


def test_explicit_demo() -> None:
    """显式 --demo：脚本化演示适配器。"""
    assert backend_main._resolve_startup_mode(_mode_args(demo=True)) == (
        True,
        "explicit_demo",
    )


def test_undeclared_defaults_to_real() -> None:
    """未声明模式一律默认真实接线，不按账号配置做启发式判断。"""
    assert backend_main._resolve_startup_mode(_mode_args()) == (
        False,
        "default_real",
    )


def test_conflicting_mode_flags_are_reported() -> None:
    """同时声明 --real 与 --demo：如实报错，不挑一个执行。"""
    with pytest.raises(ServiceError) as excinfo:
        backend_main._resolve_startup_mode(_mode_args(real=True, demo=True))
    assert excinfo.value.code == "conflicting_start_mode"