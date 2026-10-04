# 手机端 TTS 音频播放

> 45 nodes · cohesion 0.07

## Key Concepts

- **voicePlayback.test.ts** (17 connections) — `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- **voicePlayback.ts** (16 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **createVoicePlaybackEngine()** (9 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **useVoicePlayback()** (8 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **FakeAudioBufferSourceNode** (6 connections) — `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- **VoicePlaybackEngine** (6 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **FakeAudioContext** (5 connections) — `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- **checkFinish()** (5 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **fail()** (5 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **pump()** (5 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **TTS_MAX_BUFFERED_PCM_BYTES** (4 connections) — `desktop/mobile/src/lib/mobileStore.ts`
- **MobileTtsChunk** (3 connections) — `desktop/mobile/src/lib/mobileStore.ts`
- **clearEndTimer()** (3 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **scheduleChunk()** (3 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **stopActiveSources()** (3 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **ensureRunningAudioContext()** (3 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **.stop()** (3 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **VoicePlaybackEngineOptions** (3 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- **MobileVoicePlayback** (2 connections) — `desktop/mobile/src/lib/mobileStore.ts`
- **TTS_SAMPLE_RATE** (2 connections) — `desktop/mobile/src/lib/mobileStore.ts`
- **createEngineHarness()** (2 connections) — `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- **EngineHarness** (2 connections) — `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- **FakeAudioBuffer** (2 connections) — `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- **.createBufferSource()** (2 connections) — `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- **END_SIGNAL_TIMEOUT_MS** (2 connections) — `desktop/mobile/src/lib/voicePlayback.ts`
- *... and 20 more nodes in this community*

## Relationships

- [手机端会话状态与语音](手机端会话状态与语音.md) (8 shared connections)
- [手机端配对与连接测试](手机端配对与连接测试.md) (6 shared connections)
- [手机端审批与委派卡片](手机端审批与委派卡片.md) (3 shared connections)

## Source Files

- `desktop/mobile/src/lib/__tests__/voicePlayback.test.ts`
- `desktop/mobile/src/lib/mobileStore.ts`
- `desktop/mobile/src/lib/voicePlayback.ts`
- `desktop/mobile/src/pages/chat/ChatPage.tsx`

## Audit Trail

- EXTRACTED: 82 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*