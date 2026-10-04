# Windows 电源状态读取

> 10 nodes · cohesion 0.31

## Key Concepts

- **UUID** (11 connections)
- **power.py** (10 connections) — `src/pair_harness/desktop_backend/power.py`
- **read_power_status()** (8 connections) — `src/pair_harness/desktop_backend/power.py`
- **_read_sleep_settings()** (4 connections) — `src/pair_harness/desktop_backend/power.py`
- **_check()** (3 connections) — `src/pair_harness/desktop_backend/power.py`
- **_build_reason()** (2 connections) — `src/pair_harness/desktop_backend/power.py`
- **_GUID** (2 connections) — `src/pair_harness/desktop_backend/power.py`
- **PowerStatus** (2 connections) — `src/pair_harness/desktop_backend/power.py`
- **读取电源状态。非 Windows 返回 supported=False 的形状；读取失败抛 PowerStatusError。** (1 connections) — `src/pair_harness/desktop_backend/power.py`
- **返回活动电源方案的名称与 AC/DC 睡眠超时（秒）。** (1 connections) — `src/pair_harness/desktop_backend/power.py`

## Relationships

- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (4 shared connections)
- [电源状态监控事件流](电源状态监控事件流.md) (3 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (2 shared connections)
- [角色卡管理命令处理](角色卡管理命令处理.md) (1 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (1 shared connections)
- [手机音频转写会话](手机音频转写会话.md) (1 shared connections)
- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (1 shared connections)
- [角色卡资产存储](角色卡资产存储.md) (1 shared connections)
- [角色卡仓储与归档](角色卡仓储与归档.md) (1 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/power.py`

## Audit Trail

- EXTRACTED: 30 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*