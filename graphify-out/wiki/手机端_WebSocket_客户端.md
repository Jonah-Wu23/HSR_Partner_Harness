# 手机端 WebSocket 客户端

> 21 nodes · cohesion 0.20

## Key Concepts

- **MobileWsClient** (23 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **RemoteCommandError** (9 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.connect()** (8 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.handleResponse()** (6 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.abandonSocket()** (5 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.setState()** (5 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.stopHeartbeat()** (5 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.disconnect()** (4 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.failAllPending()** (4 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.handleMessage()** (4 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.request()** (4 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.scheduleReconnect()** (4 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.handleProtocolError()** (3 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.startHeartbeat()** (3 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.notifyAppForeground()** (2 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.getAuthFailureReason()** (1 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.getState()** (1 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.isSocketConnected()** (1 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.onEvent()** (1 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.onStateChange()** (1 connections) — `desktop/mobile/src/lib/wsClient.ts`
- **.constructor()** (1 connections) — `desktop/mobile/src/lib/wsClient.ts`

## Relationships

- [手机端连接与鉴权](手机端连接与鉴权.md) (8 shared connections)
- [手机端会话状态与语音](手机端会话状态与语音.md) (2 shared connections)
- [手机端配对与连接测试](手机端配对与连接测试.md) (1 shared connections)
- [手机端路由与错误边界](手机端路由与错误边界.md) (1 shared connections)
- [手机端审批与委派卡片](手机端审批与委派卡片.md) (1 shared connections)

## Source Files

- `desktop/mobile/src/lib/wsClient.ts`

## Audit Trail

- EXTRACTED: 54 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*