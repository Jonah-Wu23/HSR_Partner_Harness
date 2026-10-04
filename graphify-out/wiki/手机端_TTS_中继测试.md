# 手机端 TTS 中继测试

> 16 nodes · cohesion 0.22

## Key Concepts

- **test_mobile_tts.py** (15 connections) — `tests/unit/test_mobile_tts.py`
- **test_new_reply_preempts_relay_without_reporting_failure()** (9 connections) — `tests/unit/test_mobile_tts.py`
- **_accept_text()** (6 connections) — `tests/unit/test_mobile_tts.py`
- **phone_events()** (6 connections) — `tests/unit/test_mobile_tts.py`
- **test_completed_synthesis_relays_audio_chunks_then_end()** (6 connections) — `tests/unit/test_mobile_tts.py`
- **test_supplier_failure_is_reported_to_phone()** (6 connections) — `tests/unit/test_mobile_tts.py`
- **_tts_events()** (5 connections) — `tests/unit/test_mobile_tts.py`
- **_relayed_pcm()** (4 connections) — `tests/unit/test_mobile_tts.py`
- **Any** (3 connections)
- **completed()** (3 connections) — `tests/unit/test_mobile_tts.py`
- **completed()** (2 connections) — `tests/unit/test_mobile_tts.py`
- **held_until_cancelled()** (2 connections) — `tests/unit/test_mobile_tts.py`
- **throttled()** (2 connections) — `tests/unit/test_mobile_tts.py`
- **fixture** (1 connections)
- **手机端在线订阅事件扇出；开发机 Key 让作者音色可用，WS 地址指向本机回放端点。** (1 connections) — `tests/unit/test_mobile_tts.py`
- **按 seq 顺序拼出下发给手机的某条回复的 PCM。** (1 connections) — `tests/unit/test_mobile_tts.py`

## Relationships

- [DashScope 任务脚本](DashScope_任务脚本.md) (5 shared connections)
- [语音设备抢占互斥](语音设备抢占互斥.md) (5 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (4 shared connections)
- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (2 shared connections)
- [DashScope 模拟服务端](DashScope_模拟服务端.md) (1 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (1 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (1 shared connections)
- [Sidecar 主循环与停机](Sidecar_主循环与停机.md) (1 shared connections)

## Source Files

- `tests/unit/test_mobile_tts.py`

## Audit Trail

- EXTRACTED: 36 (78%)
- INFERRED: 10 (22%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*