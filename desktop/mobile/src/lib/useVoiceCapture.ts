/**
 * V0.3.5 手机端语音输入 Hook。
 *
 * 封装两种交互模式：
 * - 按住说话：pointer down 开始，pointer up 结束。
 * - 自动检测：开始后由本地静音检测自动结束。
 *
 * 状态全部来自 mobileStore；本 Hook 只负责把 Web Audio 采集引擎与 store 动作串起来。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMobileStore, type MobileVoiceAvailability } from "./mobileStore";
import { createVoiceCaptureEngine } from "./voiceCapture";

export type VoiceInputMode = "off" | "hold" | "auto";

export interface VoiceCaptureStatus {
  mode: VoiceInputMode;
  /** 当前是否可用语音入口 */
  usable: boolean;
  /** 不可用时的人话原因（含文档指引） */
  disabledReason: string | null;
  /** 聆听中 / 转写中 / 空闲 */
  captureState: string;
  transcriptText: string | null;
  transcriptFinal: boolean;
  captureError: string | null;
  /** 激活按住模式 */
  activateHold(): void;
  /** 结束按住模式 */
  deactivateHold(): void;
  /** 切换自动检测模式 */
  toggleAuto(): void;
  /** 显式停止当前采集 */
  stopListening(): Promise<void>;
}

const DOCS_HINT = "浏览器麦克风需要 HTTPS；请参考 docs/手机远程语音说明.md 使用 Tailscale HTTPS 方案。";

function buildDisabledReason(
  connection: string,
  availability: MobileVoiceAvailability,
): string | null {
  if (connection !== "connected") {
    return connection === "connecting" || connection === "reconnecting"
      ? "等待与桌面端连接…"
      : "与桌面端连接已断开，无法使用语音。";
  }
  if (!availability.supported) {
    return "当前浏览器不支持麦克风采集。";
  }
  if (!availability.secureContext) {
    return `当前为 HTTP 局域网连接，${DOCS_HINT}`;
  }
  if (availability.micPermission === "denied") {
    return "麦克风权限被拒绝，请前往浏览器设置授权后重试。";
  }
  return null;
}

export function useVoiceCapture(conversationId: string): VoiceCaptureStatus {
  const connection = useMobileStore((state) => state.connection);
  const capture = useMobileStore((state) => state.voice.capture);
  const transcript = useMobileStore((state) => state.voice.transcript);
  const availability = useMobileStore((state) => state.voice.availability);
  const startVoiceCapture = useMobileStore((state) => state.startVoiceCapture);
  const sendAudioChunk = useMobileStore((state) => state.sendAudioChunk);
  const stopVoiceCapture = useMobileStore((state) => state.stopVoiceCapture);
  const refreshVoiceAvailability = useMobileStore((state) => state.refreshVoiceAvailability);

  const [mode, setMode] = useState<VoiceInputMode>("off");
  const engineRef = useRef<ReturnType<typeof createVoiceCaptureEngine> | null>(null);
  const stoppingRef = useRef(false);

  const disabledReason = buildDisabledReason(connection, availability);
  const usable = disabledReason === null;

  // 挂载时刷新一次可用性
  useEffect(() => {
    void refreshVoiceAvailability();
  }, [refreshVoiceAvailability]);

  const stopEngine = useCallback(() => {
    engineRef.current?.stop();
    engineRef.current = null;
  }, []);

  const stopSession = useCallback(async () => {
    if (stoppingRef.current) return;
    stoppingRef.current = true;
    stopEngine();
    if (capture.sessionId) {
      try {
        await stopVoiceCapture();
      } catch {
        // 错误已写入 store，这里不吞异常但不需要额外处理
      }
    }
    setMode("off");
    stoppingRef.current = false;
  }, [capture.sessionId, stopEngine, stopVoiceCapture]);

  const startSession = useCallback(async () => {
    if (!usable || capture.state !== "idle") return;
    try {
      const result = await startVoiceCapture(conversationId);
      const sessionId = result?.session_id;
      if (!sessionId) {
        throw new Error("服务端未返回语音会话 ID");
      }
      // 服务端会话建立后再取麦克风，避免无意义采集
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      await refreshVoiceAvailability();

      const engine = createVoiceCaptureEngine({
        onChunk: async (seq, base64) => {
          await sendAudioChunk(seq, base64);
        },
        onSilence: () => {
          // 自动检测模式下静音触发停止
          void stopSession();
        },
        onError: (err) => {
          // eslint-disable-next-line no-console
          console.error("语音采集引擎错误", err);
          void stopSession();
        },
        enableSilenceDetection: mode === "auto",
      });
      engineRef.current = engine;
      await engine.start(stream);
    } catch (err) {
      await refreshVoiceAvailability();
      // startVoiceCapture 已经把错误写进 store；采集引擎错误需要显式 stopSession 复位
      await stopSession();
    }
  }, [
    usable,
    capture.state,
    conversationId,
    startVoiceCapture,
    sendAudioChunk,
    stopSession,
    refreshVoiceAvailability,
    mode,
  ]);

  const activateHold = useCallback(() => {
    if (!usable) return;
    setMode("hold");
    void startSession();
  }, [usable, startSession]);

  const deactivateHold = useCallback(() => {
    if (mode !== "hold") return;
    void stopSession();
  }, [mode, stopSession]);

  const toggleAuto = useCallback(() => {
    if (!usable) return;
    if (mode === "auto") {
      void stopSession();
      return;
    }
    setMode("auto");
    void startSession();
  }, [usable, mode, startSession, stopSession]);

  const stopListening = useCallback(async () => {
    await stopSession();
  }, [stopSession]);

  // 自动模式下收到最终转写后复位
  useEffect(() => {
    if (mode === "auto" && transcript?.isFinal) {
      void stopSession();
    }
  }, [mode, transcript?.isFinal, stopSession]);

  // 当 capture 回到 idle 时确保模式也回到 off（错误/成功都会回到 idle）
  useEffect(() => {
    if (capture.state === "idle" && mode !== "off") {
      setMode("off");
    }
  }, [capture.state, mode]);

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      stopEngine();
    };
  }, [stopEngine]);

  return {
    mode,
    usable,
    disabledReason,
    captureState: capture.state,
    transcriptText: transcript?.text ?? null,
    transcriptFinal: transcript?.isFinal ?? false,
    captureError: capture.error,
    activateHold,
    deactivateHold,
    toggleAuto,
    stopListening,
  };
}
