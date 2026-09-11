# test_v038_t2_device_mutex.py: test_v038_t2_devic…

> 15 nodes · cohesion 0.20

## Key Concepts

- **test_v038_t2_device_mutex.py** (17 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **test_ws_authenticated_identity_survives_reconnect()** (10 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **asyncio** (9 connections)
- **test_remote_control_blocks_explicit_desktop_audio()** (6 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **test_mobile_tts_stop_also_stops_desktop_player()** (5 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **test_remote_control_requires_transport_identity()** (5 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **test_device_mutex_claim_and_release()** (4 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **test_revoke_device_releases_its_disconnected_control()** (4 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **test_remote_control_release_preserves_other_device()** (3 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **parametrize** (2 connections)
- **V0.3.8 D2：桌面与手机播放设备互斥与控制权链路测试。 覆盖： 1. remote.claim_control 登记活跃控制器； 2.…** (1 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **手机端发起的 voice.mobile_tts_stop 联动停止桌面本地播放器。** (1 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **remote.claim_control 和 release_control 正确切换控制器活跃状态。** (1 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **request()** (1 connections) — `tests/unit/test_v038_t2_device_mutex.py`
- **wait_disconnected()** (1 connections) — `tests/unit/test_v038_t2_device_mutex.py`

## Relationships

- [桌面协议编解码测试](桌面协议编解码测试.md) (6 shared connections)
- [V0.3.8 会话幂等测试](V0.3.8_会话幂等测试.md) (4 shared connections)
- [WebSocket 服务测试](WebSocket_服务测试.md) (4 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (4 shared connections)
- [委派与契约模型](委派与契约模型.md) (2 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (2 shared connections)
- [事件扇出](事件扇出.md) (2 shared connections)
- [test_v039_s4_voice_tts.py: EventLog](test_v039_s4_voice_tts.py-_EventLog.md) (1 shared connections)
- [V0.3.5 接线测试](V0.3.5_接线测试.md) (1 shared connections)
- [边车协议解析](边车协议解析.md) (1 shared connections)
- [PWA 静态资源路由](PWA_静态资源路由.md) (1 shared connections)

## Source Files

- `tests/unit/test_v038_t2_device_mutex.py`

## Audit Trail

- EXTRACTED: 37 (76%)
- INFERRED: 12 (24%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*