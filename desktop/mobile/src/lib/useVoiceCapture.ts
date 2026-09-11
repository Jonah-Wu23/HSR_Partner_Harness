/**
 * V0.3.5 手机端语音输入 Hook。
 *
 * 封装两种交互模式：
 * - 按住说话：pointer down 开始，pointer up 结束。
 * - 自动检测：开始后由本地静音检测自动结束。
 *
 * 状态全部来自 mobileStore；本 Hook 只负责把 Web Audio 采集引擎与 store 动作串起来。
 *
 * V0.3.9 P1 修复（按住说话整条交互不可用）：
 * - 启动前置判断改为读取 store 实时状态，不再用渲染闭包里的旧 capture.state
 *   （面板只能经「语音」触发器打开，用户必然先处于 auto 录制态，旧值判断会让
 *   「按住说话」的启动静默 return）；
 * - 启动在途可取消：generationRef 让 pointerup / 卸载 / 新一次按压能作废在途启动，
 *   并在服务端会话建立后补发停止，不泄漏会话；
 * - mode 只表示采集模式，复位交给「capture 回到 idle」的 effect，stopSession 不再
 *   顺带把 mode 置 off（否则音频错误会连带关掉面板）。
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
  const refreshVoiceAvailability = useMobileStore((state) => state.refreshVoiceAvailability);

  const [mode, setMode] = useState<VoiceInputMode>("off");
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

  const stopEngine = useCallback(() => {
    engineRef.current?.stop();
    engineRef.current = null;
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
    // 本地采集立即停：别人的在途停止不能当作「本地也已经停了」。
    stopEngine();
    const previous = inFlight?.promise ?? Promise.resolve();
    const doStop = async () => {
      if (!targetId) return;
      try {
        // 目标会话一路透传到 store：补发停止要打向本次启动那一个。
        await stopVoiceCapture(targetId);
      } catch {
        // 错误已写入 store，这里不吞异常但不需要额外处理
      }
      // 这里不 setMode("off")：mode 只表示采集模式，复位统一交给下面
      // 「capture 回到 idle」的 effect，否则停止采集会连带关掉整个语音面板。
    };
    // 串在在途停止之后：旧会话先关、本次停止再发，服务端按序处理。
    // doStop 体内不 reject 是不变量（异常已在其中吞掉并写入 store），
    // 拒绝分支只作防御，免得链上出现未处理的拒绝。
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
  }, [stopEngine, stopVoiceCapture]);

  const startSession = useCallback(
    async (targetMode: ActiveVoiceInputMode) => {
      if (!usable) return;
      const generation = generationRef.current;
      /** 本次启动是否已被取消（更晚的按压 / 停止 / 卸载）。 */
      const cancelled = () =>
        generation !== generationRef.current || disposedRef.current;
      let sessionId: string | null = null;
      try {
        // 读 store 实时状态：渲染闭包里的 capture.state 可能已经过期，
        // 用它做前置判断会让「自动检测录制中点按住说话」的启动被静默吞掉。
        if (useMobileStore.getState().voice.capture.state !== "idle") {
          // 接替上一段采集：先停旧会话，再启动新会话。
          await stopSession();
          if (cancelled()) return;
        }
        // 交接期间 store 会短暂回到 idle，「capture 回到 idle 就把 mode 置 off」的
        // effect 可能正好在那一刻把刚按下的 hold / 刚点的 auto 冲掉；这里按本次
        // 启动的目标模式重新声明一次，之后 state 进入 starting 就不会再被复位。
        setMode(targetMode);
        const result = await startVoiceCapture(conversationId);
        sessionId = result?.session_id ?? null;
        if (!sessionId) {
          throw new Error("服务端未返回语音会话 ID");
        }
        if (cancelled()) {
          // 启动在途被取消（pointerup 早于会话建立、或卸载）：服务端会话刚建立
          // 就没人接管了，显式携带 sessionId 补发停止，避免泄漏到 watchdog 超时。
          await stopSession(sessionId);
          return;
        }
        // 服务端会话建立后再取麦克风，避免无意义采集
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        await refreshVoiceAvailability();
        if (cancelled()) {
          // 麦克风到手但已被取消：不建引擎，直接关闭服务端会话。
          await stopSession(sessionId);
          return;
        }

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
          // 用本次调用显式传入的目标模式，而不是可能尚未更新的 React state
          // （Codex P1：setMode 之后紧接 startSession 仍闭包捕获旧 mode）。
          enableSilenceDetection: targetMode === "auto",
        });
        engineRef.current = engine;
        await engine.start(stream);
        if (cancelled()) {
          // 采集已经跑起来但已被取消：立即停引擎与服务端会话。
          await stopSession();
          return;
        }
      } catch (err) {
        await refreshVoiceAvailability();
        // 服务端会话可能已建立（getUserMedia/引擎失败）：显式携带刚返回的
        // sessionId 通知服务端关闭，不复位会泄漏直到 watchdog 超时。
        await stopSession(sessionId ?? undefined);
      }
    },
    [
      usable,
      conversationId,
      startVoiceCapture,
      sendAudioChunk,
      stopSession,
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

  const endHoldCapture = useCallback(() => {
    // 无论服务端会话是否已建立，都要让在途启动失效：startSession 会在下一个
    // await 之后发现代次不一致并补发停止（会话未建立时 store 仍可能是 idle，
    // 光看状态会漏掉这半边）。
    generationRef.current += 1;
    if (useMobileStore.getState().voice.capture.state === "idle") return;
    void stopSession();
  }, [stopSession]);

  const toggleAuto = useCallback(() => {
    if (!usable) return;
    const state = useMobileStore.getState().voice.capture.state;
    if (mode === "auto" && state !== "idle") {
      // 已在自动检测采集中：本次点击是停止
      generationRef.current += 1;
      void stopSession();
      return;
    }
    generationRef.current += 1;
    lastAttemptModeRef.current = "auto";
    setMode("auto");
    void startSession("auto");
  }, [usable, mode, startSession, stopSession]);

  const stopListening = useCallback(async () => {
    generationRef.current += 1;
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

  // 组件卸载时清理：停本地采集之外，还必须向服务端补发 voice.mobile_ptt_stop，
  // 否则录制中离开页面（返回键/切页）会让服务端会话泄漏到 watchdog 超时。
  // 停止失败（如已断连）照常写入 store 的 capture.error，不伪造成功。
  useEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      generationRef.current += 1;
      stopEngine();
      void stopSession();
    };
  }, [stopEngine, stopSession]);

  return {
    mode,
    usable,
    disabledReason,
    captureState: capture.state,
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
