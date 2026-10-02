import pytest

from pair_harness.core.sandbox import ProjectSandbox, SandboxViolation


@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
def test_path_inside_root_is_allowed(tmp_path, absolute: bool) -> None:
    target = tmp_path / "src" / "main.py"
    path = str(target) if absolute else "src/main.py"
    assert ProjectSandbox(tmp_path).resolve_write_path(path) == target.resolve()


@pytest.mark.parametrize("path", ["../outside.txt", "C:/Windows/system32"])
def test_path_outside_root_is_rejected(tmp_path, path: str) -> None:
    with pytest.raises(SandboxViolation):
        ProjectSandbox(tmp_path).resolve_write_path(path)


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
