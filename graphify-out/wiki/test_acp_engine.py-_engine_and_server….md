# test_acp_engine.py: engine_and_server(…

> 16 nodes · cohesion 0.15

## Key Concepts

- **FakeAcpServer** (11 connections) — `tests/unit/test_acp_engine.py`
- **engine_and_server()** (5 connections) — `tests/unit/test_acp_engine.py`
- **LegacyShapedServer** (5 connections) — `tests/unit/test_acp_engine.py`
- **OutOfSandboxServer** (5 connections) — `tests/unit/test_acp_engine.py`
- **.handle_request()** (5 connections) — `tests/unit/test_acp_engine.py`
- **.handle_request()** (2 connections) — `tests/unit/test_acp_engine.py`
- **.__init__()** (2 connections) — `tests/unit/test_acp_engine.py`
- **._put_completion()** (2 connections) — `tests/unit/test_acp_engine.py`
- **.handle_request()** (2 connections) — `tests/unit/test_acp_engine.py`
- **.handle_request()** (2 connections) — `tests/unit/test_acp_engine.py`
- **.handle_notify()** (1 connections) — `tests/unit/test_acp_engine.py`
- **.handle_response()** (1 connections) — `tests/unit/test_acp_engine.py`
- **fixture** (1 connections)
- **ACP 服务端脚本（reasonix v1.24 实测形状：session/update 封装）。** (1 connections) — `tests/unit/test_acp_engine.py`
- **真实联调出现的兼容形状：snake_case 字段、dict 结果文本、rejected 状态。** (1 connections) — `tests/unit/test_acp_engine.py`
- **工具目标路径在项目目录之外——触发编排器 TOOL_STARTED 分支的沙箱 break。** (1 connections) — `tests/unit/test_acp_engine.py`

## Relationships

- [ACP 引擎测试](ACP_引擎测试.md) (7 shared connections)
- [test_acp_engine.py: FakeTransport](test_acp_engine.py-_FakeTransport.md) (2 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (1 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (1 shared connections)

## Source Files

- `tests/unit/test_acp_engine.py`

## Audit Trail

- EXTRACTED: 29 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*