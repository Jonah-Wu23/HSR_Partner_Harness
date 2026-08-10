import pytest

from pair_harness.core.sandbox import ProjectSandbox, SandboxViolation


def test_relative_path_inside_root_is_allowed(tmp_path) -> None:
    sandbox = ProjectSandbox(tmp_path)
    resolved = sandbox.resolve_write_path("src/main.py")
    assert resolved == (tmp_path / "src" / "main.py").resolve()


def test_dotdot_escape_is_rejected(tmp_path) -> None:
    sandbox = ProjectSandbox(tmp_path)
    with pytest.raises(SandboxViolation):
        sandbox.resolve_write_path("../outside.txt")


def test_absolute_path_outside_root_is_rejected(tmp_path) -> None:
    sandbox = ProjectSandbox(tmp_path)
    with pytest.raises(SandboxViolation):
        sandbox.resolve_write_path("C:/Windows/system32")


def test_absolute_path_inside_root_is_allowed(tmp_path) -> None:
    sandbox = ProjectSandbox(tmp_path)
    target = tmp_path / "inside.txt"
    resolved = sandbox.resolve_write_path(str(target))
    assert resolved == target.resolve()


def test_symlink_pointing_outside_is_rejected(tmp_path) -> None:
    sandbox = ProjectSandbox(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("当前环境不支持创建符号链接")
    with pytest.raises(SandboxViolation):
        sandbox.resolve_write_path("link.txt")


def test_enforce_cwd_defaults_to_root(tmp_path) -> None:
    sandbox = ProjectSandbox(tmp_path)
    assert sandbox.enforce_cwd(None) == tmp_path.resolve()


def test_enforce_cwd_rejects_outside_path(tmp_path) -> None:
    sandbox = ProjectSandbox(tmp_path)
    with pytest.raises(SandboxViolation):
        sandbox.enforce_cwd(str(tmp_path.parent))
