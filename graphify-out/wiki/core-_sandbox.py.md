# core: sandbox.py

> 19 nodes · cohesion 0.19

## Key Concepts

- **ProjectSandbox** (16 connections) — `src/pair_harness/core/sandbox.py`
- **SandboxViolation** (10 connections) — `src/pair_harness/core/sandbox.py`
- **test_sandbox.py** (8 connections) — `tests/unit/test_sandbox.py`
- **.resolve_write_path()** (5 connections) — `src/pair_harness/core/sandbox.py`
- **sandbox.py** (4 connections) — `src/pair_harness/core/sandbox.py`
- **.enforce_cwd()** (4 connections) — `src/pair_harness/core/sandbox.py`
- **Path** (3 connections)
- **test_absolute_path_outside_root_is_rejected()** (3 connections) — `tests/unit/test_sandbox.py`
- **test_dotdot_escape_is_rejected()** (3 connections) — `tests/unit/test_sandbox.py`
- **test_enforce_cwd_rejects_outside_path()** (3 connections) — `tests/unit/test_sandbox.py`
- **test_symlink_pointing_outside_is_rejected()** (3 connections) — `tests/unit/test_sandbox.py`
- **.__init__()** (2 connections) — `src/pair_harness/core/sandbox.py`
- **test_absolute_path_inside_root_is_allowed()** (2 connections) — `tests/unit/test_sandbox.py`
- **test_enforce_cwd_defaults_to_root()** (2 connections) — `tests/unit/test_sandbox.py`
- **test_relative_path_inside_root_is_allowed()** (2 connections) — `tests/unit/test_sandbox.py`
- **RuntimeError** (1 connections)
- **目录级沙箱：限制文件与命令操作在项目根目录之内。 设计偏差说明（O4.6）：本类只是“路径约束”，不是执行沙箱—— - 对 shell…** (1 connections) — `src/pair_harness/core/sandbox.py`
- **校验并解析写操作目标路径。 规则： - 相对路径拼接到项目根目录； - 绝对路径保持原样； - 使用 :meth:`Path.resolve` 展开…** (1 connections) — `src/pair_harness/core/sandbox.py`
- **校验命令执行工作目录。``None`` 返回项目根目录。** (1 connections) — `src/pair_harness/core/sandbox.py`

## Relationships

- [会话编排器](会话编排器.md) (5 shared connections)
- [委派与契约模型](委派与契约模型.md) (3 shared connections)

## Source Files

- `src/pair_harness/core/sandbox.py`
- `tests/unit/test_sandbox.py`

## Audit Trail

- EXTRACTED: 28 (68%)
- INFERRED: 13 (32%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*