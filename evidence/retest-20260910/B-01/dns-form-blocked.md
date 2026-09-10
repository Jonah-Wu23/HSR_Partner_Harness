# B-01 第五形态（名称解析失败）受阻记录

## 尝试

按复测计划 §4.1 的第四种形态，把候选的对话端点指向 RFC 6761 保留域
`https://no-such-host-r1.invalid/v1`（保证不解析），使客户端在**自行解析**的路径上失败：

1. 停候选 → 改写 `%LOCALAPPDATA%\PairHarness\.env` 的 `PAIR_HARNESS_DIALOGUE_BASE_URL` → 重启候选（不带代理）；
2. 期望：候选正常运行、真实回合失败于 `getaddrinfo`，失败原因可见。

## 实际结果：**受阻**（候选无法进入可用运行态）

候选重启后 Remote Serve 端口始终未监听、Rust 侧报：

```
[sidecar] 致命启动失败：Sidecar 启动配置错误，已停止自动重连（退出码 2）
```

Sidecar 自身 stderr（未被日志级别过滤，完整 traceback）：

```
===== sidecar stderr session 2026-09-10T13:16:37.825Z stream_id=1 pid=30484 mode=real =====
INFO:__main__:启动接线 demo=False 来源=explicit_real
ERROR:__main__:sidecar startup failed
Traceback (most recent call last):
  File "__main__.py", line 167, in _run
  File "pair_harness\desktop_backend\application_service.py", line 7406, in build_configured_service
  File "pair_harness\desktop_backend\application_service.py", line 7279, in _build_service
  File "pair_harness\desktop_backend\engine_factory.py", line 308, in build_coding_engine
  File "pair_harness\desktop_backend\engine_factory.py", line 125, in _require_responses_backend
RuntimeError: codex 引擎要求 Responses API 后端，当前对话端点不兼容：https://no-such-host-r1.invalid/v1。codex-cli 无法对接 Chat Completions 端点（0.122+ 已移除 wire_api=chat）。请改用 DeepSeek 对话配置（委派将自动走 reasonix 引擎），或提供 Responses 兼容后端。
```

## 根因

Sidecar **启动阶段**即构建编码引擎（`build_configured_service` → `engine_factory.build_coding_engine`），
而 `_require_responses_backend`（`engine_factory.py:110-130`）对非 `*.openai.com` 端点直接抛 `RuntimeError`，
启动随即失败并退出（退出码 2 → Rust 归类为致命配置错误，停止自动重连）。

因此**无法**让候选以「不可解析端点」进入可用运行态，也就无法在真实回合里注入名称解析失败。
这与 B-03（剥离 Codex/Responses 要求）未交付直接相关：该启动期校验正是产品决策要求移除的三条之一。

## 沙盒侧的可用性（工具层已自检通过）

同一形态在工具层可用——`sandbox-selftest.json` 的 `dns_failure` 项：不经代理直连保留域得到
`ConnectError: [Errno 11001] getaddrinfo failed`，与「连接被拒」的
`ConnectError: All connection attempts failed` 在报文层可区分。
受限于候选侧的启动校验，该形态本轮**不计通过、不计失败**，记为受阻。

## 阻塞项与下一次尝试条件

- blocker：候选启动期端点校验拒绝非 OpenAI Responses 端点（B-03 未交付的连带效果）。
- next_action：B-03 交付（移除 Responses 依赖与校验）后，重跑本形态即可正常注入。
- 归属：产品决策 B-03 的开发轨交付，非测试侧可绕过的环境限制。

