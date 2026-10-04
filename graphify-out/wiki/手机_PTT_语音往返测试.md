# 手机 PTT 语音往返测试

> 10 nodes · cohesion 0.20

## Key Concepts

- **phone()** (8 connections) — `tests/unit/test_mobile_audio.py`
- **test_mobile_ptt_round_trip_submits_transcript_as_remote_turn()** (7 connections) — `tests/unit/test_mobile_audio.py`
- **remote_events()** (6 connections) — `tests/unit/test_mobile_audio.py`
- **Any** (3 connections)
- **test_mobile_ptt_start_requires_dashscope_key()** (3 connections) — `tests/unit/test_mobile_audio.py`
- **dashscope_env()** (2 connections) — `tests/unit/test_mobile_audio.py`
- **fixture** (2 connections)
- **DesktopCommand** (1 connections)
- **接上真实事件扇出，收集只发给远程连接的事件。** (1 connections) — `tests/unit/test_mobile_audio.py`
- **script()** (1 connections) — `tests/unit/test_mobile_audio.py`

## Relationships

- [手机端 ASR 会话测试](手机端_ASR_会话测试.md) (6 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (4 shared connections)
- [角色卡绑定与命令测试](角色卡绑定与命令测试.md) (2 shared connections)
- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (1 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (1 shared connections)
- [Sidecar 主循环与停机](Sidecar_主循环与停机.md) (1 shared connections)
- [DashScope 任务脚本](DashScope_任务脚本.md) (1 shared connections)

## Source Files

- `tests/unit/test_mobile_audio.py`

## Audit Trail

- EXTRACTED: 20 (80%)
- INFERRED: 5 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*