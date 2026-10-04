# 手机 ASR 会话管理器

> 7 nodes · cohesion 0.33

## Key Concepts

- **MobileAsrSessionManager** (26 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.cancel_all_for_connection()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.cancel_session()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.__init__()** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **静默取消（连接断开或超时），返回 conversation_id；未知会话返回 None。 识别器在后台收到流结束后自行收尾，不阻塞调用方。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **静默取消某连接的全部会话，返回被取消的 session_id。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **上行转写会话（voice.mobile_ptt_start / audio_chunk / ptt_stop）。…** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`

## Relationships

- [手机端 ASR 会话测试](手机端_ASR_会话测试.md) (11 shared connections)
- [手机音频转写会话](手机音频转写会话.md) (4 shared connections)
- [手机语音分片会话协议](手机语音分片会话协议.md) (3 shared connections)
- [语音运行时装配与中继](语音运行时装配与中继.md) (1 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (1 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (1 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/mobile_audio.py`

## Audit Trail

- EXTRACTED: 16 (55%)
- INFERRED: 13 (45%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*