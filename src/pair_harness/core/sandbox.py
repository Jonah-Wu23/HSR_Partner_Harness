from __future__ import annotations

from pathlib import Path


class SandboxViolation(RuntimeError):
    """操作试图越过项目根目录。"""


class ProjectSandbox:
    """路径级沙箱：校验工具上报的目标路径都在项目根目录之内。

    编排器在引擎申请工具权限（approval.requested）和工具开始
    （tool.started）时，用事件里的路径调用 :meth:`resolve_write_path`，
    越界即否决。它只检查引擎上报的路径，不隔离 shell 命令运行时实际
    访问的文件；命令的工作目录是 Reasonix 会话打开时传入的项目目录。
    """

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
