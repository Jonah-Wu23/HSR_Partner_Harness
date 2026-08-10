from __future__ import annotations

from pathlib import Path


class SandboxViolation(RuntimeError):
    """操作试图越过项目根目录。"""


class ProjectSandbox:
    """目录级沙箱：限制文件与命令操作在项目根目录之内。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve_write_path(self, path: str | Path) -> Path:
        """校验并解析写操作目标路径。

        规则：
        - 相对路径拼接到项目根目录；
        - 绝对路径保持原样；
        - 使用 :meth:`Path.resolve` 展开 ``..`` 和符号链接；
        - 结果必须位于 ``self.root`` 之下，否则抛出 :class:`SandboxViolation`；
        - Windows 下盘符不同一律视为越界。
        """
        target = Path(path)
        if not target.is_absolute():
            target = self.root / target
        try:
            resolved = target.resolve()
        except (OSError, RuntimeError) as exc:
            raise SandboxViolation(f"无法解析路径: {path}") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SandboxViolation(f"路径越界: {path}") from exc
        return resolved

    def enforce_cwd(self, cwd: str | Path | None) -> Path:
        """校验命令执行工作目录。``None`` 返回项目根目录。"""
        if cwd is None:
            return self.root
        return self.resolve_write_path(cwd)
