from __future__ import annotations

from pathlib import Path


class SandboxViolation(RuntimeError):
    """操作试图越过项目根目录。"""


class ProjectSandbox:
    """目录级沙箱：限制文件与命令操作在项目根目录之内。

    设计偏差说明（O4.6）：本类只是“路径约束”，不是执行沙箱——
    - 对 shell 命令只能锁定工作目录（enforce_cwd），无法阻止命令
      访问 cwd 之外的文件（如读取绝对路径、访问系统目录）；
    - 真正的执行边界在引擎侧策略：Codex app-server 的 workspace-write
      策略（设计 §6.3 修订），演示引擎路径下也只是兜底目录拦截；
    - 容器隔离不进入 MVP（设计 §6.4 附录）。
    不要依据本类判断“命令已被安全隔离”；后续扩展防护时应在引擎策略
    层（而非此处）加强。
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

    def enforce_cwd(self, cwd: str | Path | None) -> Path:
        """校验命令执行工作目录。``None`` 返回项目根目录。"""
        if cwd is None:
            return self.root
        return self.resolve_write_path(cwd)
