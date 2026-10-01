/**
 * 手机端语音输入 Hook。
 *
 * 封装两种交互模式：
 * - 按住说话：pointer down 开始，pointer up 结束。
 * - 自动检测：开始后由本地静音检测自动结束。
 *
 * 状态来自 mobileStore；本 Hook 把 Web Audio 采集引擎与 store 动作串起来。
 * 启动顺序：先拿到麦克风，再建服务端会话（voice.mobile_ptt_start），最后启动引擎；
 * 麦克风失败不会留下空会话。启动在途可被 pointerup / 卸载 / 新一次按压作废，
 * 作废时停掉麦克风轨道，服务端会话已建立则补发停止。
 * mode 只表示采集模式，复位交给「capture 回到 idle」的 effect。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMobileStore, type MobileVoiceAvailability } from "./mobileStore";
import { createVoiceCaptureEngine } from "./voiceCapture";

export type VoiceInputMode = "off" | "hold" | "auto";

/** 真正会启动采集的模式（off 表示没有采集）。 */
export type ActiveVoiceInputMode = "hold" | "auto";

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
  /** 最近一次尝试启动的采集模式；从未尝试过为 null */
  lastAttemptMode: ActiveVoiceInputMode | null;
  /** 开始按住说话（pointerdown） */
  beginHoldCapture(): void;
  /** 结束按住说话（pointerup / pointercancel / 失焦） */
  endHoldCapture(): void;
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
  const reportVoiceCaptureError = useMobileStore((state) => state.reportVoiceCaptureError);
  const refreshVoiceAvailability = useMobileStore((state) => state.refreshVoiceAvailability);

  const [mode, setMode] = useState<VoiceInputMode>("off");
  /**
   * 正在申请麦克风的启动代次（getUserMedia 未返回时 store 仍是 idle）。
   * 期间界面按「准备中」展示，复位 effect 不收回 mode。
   */
  const acquiringRef = useRef<number | null>(null);
  const [acquiring, setAcquiring] = useState(false);
  const engineRef = useRef<ReturnType<typeof createVoiceCaptureEngine> | null>(null);
  /**
   * 在途停止：Promise 连同它停的是哪个会话一起缓存。停止请求最坏要等服务端尾超时
   * （约 5s），这段时间里 store 可能已被 is_final 事件置 idle、用户也可能已经建起
   * 新会话；只按「有没有在途」复用，会把新会话的停止交给旧 Promise 吞掉。
   * 用可等待的 Promise 而不是布尔互斥，交接启动才能真的等到旧会话停稳，
   * 而不是被直接放行后撞上 startVoiceCapture 的前置校验（按压被静默丢弃）。
   */
  const stopPromiseRef = useRef<{
    promise: Promise<void>;
    sessionId: string | null;
  } | null>(null);
  const disposedRef = useRef(false);
  /**
   * 最近一次「想开始采集」的模式。启动失败后 capture 回 idle、mode 被复位 effect
   * 收回 off，错误块只能靠它判断该给哪个重试入口（auto 给按钮，hold 给按压提示）。
   */
  const lastAttemptModeRef = useRef<ActiveVoiceInputMode | null>(null);
  /**
   * 启动代次：每次「开始按压 / 切换自动检测 / 停止 / 卸载」都自增。
   * startSession 入口记下当时的值，每个 await 之后校验，不一致说明这次启动已被
   * 取消（pointerup 早于会话建立就是这种情况），必须清理而不是继续采集。
   */
  const generationRef = useRef(0);

  const disabledReason = buildDisabledReason(connection, availability);
  const usable = disabledReason === null;

  // 挂载时刷新一次可用性
  useEffect(() => {
    void refreshVoiceAvailability();
  }, [refreshVoiceAvailability]);

  const markAcquiring = useCallback((owner: number | null) => {
    acquiringRef.current = owner;
    setAcquiring(owner !== null);
  }, []);

  const stopSession = useCallback((explicitSessionId?: string): Promise<void> => {
    // 本次要停的会话：显式优先，其次读 store 实时值（渲染闭包里的旧值可能是 null，
    // startVoiceCapture 刚成功但尚未触发重渲染时尤其如此）。
    const targetId =
      explicitSessionId ?? useMobileStore.getState().voice.capture.sessionId;
    const inFlight = stopPromiseRef.current;
    // 只有在途停止就是冲着同一个会话去的才复用：目标不同（旧会话的停止还在途、
    // 新会话已经建立）必须各自发一次停止，否则新会话会被旧 Promise 吞掉、
    // 泄漏到 watchdog。目标相同时，调用方 await 到的是它真正停稳。
    if (inFlight && inFlight.sessionId === targetId) return inFlight.promise;
    // 本地采集立即开始收尾：引擎交出尾部样本并等全部分片上行完成。
    const engine = engineRef.current;
    engineRef.current = null;
    const engineStopped = engine ? engine.stop() : Promise.resolve();
    const previous = inFlight?.promise ?? Promise.resolve();
    const doStop = async () => {
      try {
        await engineStopped;
      } catch (error) {
        console.error("语音采集引擎停止失败", error);
        reportVoiceCaptureError(error instanceof Error ? error.message : String(error));
      }
      if (!targetId) return;
      try {
        // 分片全部发完才发停止；目标会话一路透传到 store，补发停止要打向本次启动那一个。
        await stopVoiceCapture(targetId);
      } catch {
        // store 已把错误写入 capture.error 并记录日志
      }
    };
    // 串在在途停止之后：旧会话先关、本次停止再发，服务端按序处理。
    // doStop 体内不 reject（错误已写入 store），拒绝分支保证链上没有未处理的拒绝。
    const stopPromise = previous.then(
      () => doStop(),
      () => doStop(),
    );
    stopPromiseRef.current = { promise: stopPromise, sessionId: targetId };
    const clearStopPromise = () => {
      const current = stopPromiseRef.current;
      if (current?.promise === stopPromise) stopPromiseRef.current = null;
    };
    // 注册在调用方 await 之前，结算时先清缓存再恢复调用方。
    void stopPromise.then(clearStopPromise, clearStopPromise);
    return stopPromise;
  }, [reportVoiceCaptureError, stopVoiceCapture]);

  const startSession = useCallback(
    async (targetMode: ActiveVoiceInputMode) => {
      if (!usable) return;
      const generation = generationRef.current;
      /** 本次启动是否已被取消（更晚的按压 / 停止 / 卸载）。 */
      const cancelled = () =>
        generation !== generationRef.current || disposedRef.current;
      // 读 store 实时状态：渲染闭包里的 capture.state 可能已经过期。
      if (useMobileStore.getState().voice.capture.state !== "idle") {
        // 接替上一段采集：先停旧会话，再启动新会话。
        await stopSession();
        if (cancelled()) return;
      }
      // 交接期间 store 会短暂回到 idle，复位 effect 可能把刚按下的模式收回 off；
      // 这里重新声明，并在同一时刻标记「申请麦克风中」挡住复位。
      setMode(targetMode);
      markAcquiring(generation);
      /** 尚未移交引擎的麦克风流；移交前的任何退出都由 finally 停掉轨道。 */
      let stream: MediaStream | null = null;
      let sessionId: string | null = null;
      let stage: "microphone" | "session" | "engine" = "microphone";
      try {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } finally {
          if (acquiringRef.current === generation) markAcquiring(null);
        }
        if (cancelled()) return;

        stage = "session";
        const result = await startVoiceCapture(conversationId);
        sessionId = result.session_id;
        if (cancelled()) {
          // 启动在途被取消（pointerup 早于会话建立、或卸载）：显式携带 sessionId
          // 补发停止，避免服务端会话泄漏到 watchdog 超时。
          await stopSession(sessionId);
          return;
        }

        stage = "engine";
        const engine = createVoiceCaptureEngine({
          onChunk: async (seq, base64) => {
            await sendAudioChunk(seq, base64);
          },
          onSilence: () => {
            void stopSession();
          },
          onError: (err) => {
            console.error("语音采集引擎错误", err);
            void stopSession();
          },
          enableSilenceDetection: targetMode === "auto",
        });
        engineRef.current = engine;
        const owned = stream;
        stream = null;
        await engine.start(owned);
        if (cancelled()) {
          await stopSession(sessionId);
        }
      } catch (err) {
        console.error(`语音采集启动失败（${stage}）`, err);
        // 会话阶段的失败已由 store 写入 capture.error；麦克风与引擎阶段在这里写入，
        // 权限被拒、没有麦克风等原因原样展示。
        if (stage !== "session") {
          reportVoiceCaptureError(err instanceof Error ? err.message : String(err));
        }
        if (sessionId) await stopSession(sessionId);
      } finally {
        stream?.getTracks().forEach((track) => track.stop());
        await refreshVoiceAvailability();
      }
    },
    [
      usable,
      conversationId,
      markAcquiring,
      startVoiceCapture,
      sendAudioChunk,
      stopSession,
      reportVoiceCaptureError,
      refreshVoiceAvailability,
    ],
  );

  const beginHoldCapture = useCallback(() => {
    if (!usable) return;
    // 新一次按压作废上一次在途启动（短按后再按一次就是开始一次新采集）。
    generationRef.current += 1;
    lastAttemptModeRef.current = "hold";
    setMode("hold");
    void startSession("hold");
  }, [usable, startSession]);

  /** 作废在途启动：startSession 在下一个 await 之后发现代次变化，自行释放麦克风与会话。 */
  const cancelPendingStart = useCallback(() => {
    generationRef.current += 1;
    if (acquiringRef.current !== null) markAcquiring(null);
  }, [markAcquiring]);

  const endHoldCapture = useCallback(() => {
    // 无论服务端会话是否已建立，都要让在途启动失效（会话未建立时 store 仍是 idle，
    // 光看状态会漏掉这半边）。
    cancelPendingStart();
    if (useMobileStore.getState().voice.capture.state === "idle") return;
    void stopSession();
  }, [cancelPendingStart, stopSession]);

  const toggleAuto = useCallback(() => {
    if (!usable) return;
    const state = useMobileStore.getState().voice.capture.state;
    if (mode === "auto" && (state !== "idle" || acquiringRef.current !== null)) {
      // 已在自动检测采集中：本次点击是停止
      cancelPendingStart();
      void stopSession();
      return;
    }
    generationRef.current += 1;
    lastAttemptModeRef.current = "auto";
    setMode("auto");
    void startSession("auto");
  }, [usable, mode, cancelPendingStart, startSession, stopSession]);

  const stopListening = useCallback(async () => {
    cancelPendingStart();
    await stopSession();
  }, [cancelPendingStart, stopSession]);

  // 自动模式下收到最终转写后复位
  useEffect(() => {
    if (mode === "auto" && transcript?.isFinal) {
      void stopSession();
    }
  }, [mode, transcript?.isFinal, stopSession]);

  // 当 capture 回到 idle 时确保模式也回到 off（错误/成功都会回到 idle）；
  // 申请麦克风期间 store 本来就是 idle，不算回到 idle。
  useEffect(() => {
    if (capture.state === "idle" && !acquiring && mode !== "off") {
      setMode("off");
    }
  }, [capture.state, acquiring, mode]);

  // 组件卸载时清理：停本地采集之外，还必须向服务端补发 voice.mobile_ptt_stop，
  // 否则录制中离开页面（返回键/切页）会让服务端会话泄漏到 watchdog 超时。
  // 停止失败（如已断连）照常写入 store 的 capture.error。
  useEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      generationRef.current += 1;
      void stopSession();
    };
  }, [stopSession]);

  return {
    mode,
    usable,
    disabledReason,
    captureState: acquiring ? "starting" : capture.state,
    transcriptText: transcript?.text ?? null,
    transcriptFinal: transcript?.isFinal ?? false,
    captureError: capture.error,
    lastAttemptMode: lastAttemptModeRef.current,
    beginHoldCapture,
    endHoldCapture,
    toggleAuto,
    stopListening,
  };
}
