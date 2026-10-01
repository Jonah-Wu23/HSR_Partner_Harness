import { useState } from "react";
import { MicIcon, StopIcon } from "../../components/cards/icons";
import { useVoiceCapture } from "../../lib/useVoiceCapture";

export interface ChatVoiceBarProps {
  conversationId: string;
}

/**
 * 聊天页语音输入区：按住说话与自动检测。采集状态与转写只在这里订阅，
 * 说话时转写更新不会让整页重新渲染。
 */
export function ChatVoiceBar({ conversationId }: ChatVoiceBarProps) {
  const voice = useVoiceCapture(conversationId);
  // 语音面板开合与采集模式相互独立：打开面板不开始采集，采集失败也不关面板。
  const [voicePanelOpen, setVoicePanelOpen] = useState(false);

  return (
    <div className="mobile-voice-bar" data-testid="voice-bar">
      {!voice.usable ? (
        <div className="mobile-voice-disabled" role="note" data-testid="voice-disabled-reason">
          <span className="mobile-voice-disabled-icon" aria-hidden="true">
            <MicIcon />
          </span>
          <span className="mobile-voice-disabled-text">
            语音不可用：{voice.disabledReason}
          </span>
        </div>
      ) : voicePanelOpen ? (
        <div className="mobile-voice-panel">
          {/* 按住说话：pointerdown 起采，抬起 / 取消即停止并发最终转写 */}
          <button
            type="button"
            className="mobile-voice-hold-btn"
            data-testid="voice-hold-btn"
            aria-label="按住说话"
            onPointerDown={(e) => {
              e.preventDefault();
              // 捕获指针：手指轻微滑出按钮不再误中断，抬起 / 取消仍派发到本元素。
              e.currentTarget.setPointerCapture?.(e.pointerId);
              voice.beginHoldCapture();
            }}
            onPointerUp={(e) => {
              e.preventDefault();
              voice.endHoldCapture();
            }}
            onPointerCancel={(e) => {
              e.preventDefault();
              voice.endHoldCapture();
            }}
            onLostPointerCapture={() => {
              voice.endHoldCapture();
            }}
            onContextMenu={(e) => {
              // 抑制长按弹出的系统菜单：长按期间必须一直属于采集
              e.preventDefault();
            }}
          >
            <MicIcon />
            {voice.captureState === "recording" ? "聆听中…" : "按住说话"}
          </button>

          {voice.mode === "hold" && voice.captureState !== "idle" ? (
            <span className="mobile-voice-listening" data-testid="voice-hold-status">
              <span className="mobile-voice-listening-dot" aria-hidden="true" />
              {voice.captureState === "recording"
                ? "聆听中，抬起发送"
                : voice.captureState === "starting"
                  ? "准备中…"
                  : "正在结束…"}
            </span>
          ) : null}

          {/* 自动检测：点击开始，再点停止（本地静音检测自动收尾） */}
          <div className="mobile-voice-mode-switch" role="group" aria-label="自动检测语音输入">
            <button
              type="button"
              className={`mobile-voice-mode-btn${voice.mode === "auto" ? " active" : ""}`}
              aria-pressed={voice.mode === "auto"}
              data-testid="voice-auto-toggle-btn"
              onClick={() => voice.toggleAuto()}
            >
              自动检测
            </button>
          </div>

          {voice.mode === "auto" ? (
            <div className="mobile-voice-auto">
              <span className="mobile-voice-listening">
                <span className="mobile-voice-listening-dot" aria-hidden="true" />
                {voice.captureState === "recording" ? "聆听中，检测到静音自动停止" : "准备中…"}
              </span>
              <button
                type="button"
                className="mobile-voice-stop-btn"
                data-testid="voice-stop-btn"
                onClick={() => voice.stopListening()}
                aria-label="停止语音输入"
              >
                <StopIcon />
                停止
              </button>
            </div>
          ) : null}

          {voice.transcriptText ? (
            <p className="mobile-voice-transcript" data-testid="voice-transcript">
              {voice.transcriptFinal ? "转写完成" : "转写中"}：{voice.transcriptText}
            </p>
          ) : null}

          {voice.captureError ? (
            <div className="mobile-voice-error" role="alert" data-testid="voice-capture-error">
              <span>语音失败：{voice.captureError}</span>
              {/* 重试入口按「最近一次尝试的模式」给，不看当前 mode：
                  启动失败后 capture 回 idle，复位 effect 会把 mode 收回 off，
                  按 mode 判断会让自动检测的重试按钮永远不可达。 */}
              {voice.lastAttemptMode === "auto" ? (
                <button
                  type="button"
                  className="mobile-voice-retry-btn"
                  data-testid="voice-retry-btn"
                  onClick={() => voice.toggleAuto()}
                >
                  重试
                </button>
              ) : (
                // 按住说话是按压语义：重试就是再按住一次大按钮，
                // 不给 click 启动入口（click 不构成一次按压）。
                <span data-testid="voice-hold-retry-hint">请再次按住说话重试</span>
              )}
            </div>
          ) : null}

          <button
            type="button"
            className="mobile-voice-close-btn"
            data-testid="voice-close-btn"
            onClick={() => {
              // 先停采集再合面板：停止失败会由 store 写入 captureError，
              // 面板合上不再展示，故停止动作必须真的发出去（不因合面板跳过）。
              void voice.stopListening();
              setVoicePanelOpen(false);
            }}
          >
            关闭语音
          </button>
        </div>
      ) : (
        <div className="mobile-voice-trigger-row">
          <button
            type="button"
            className="mobile-voice-trigger-btn"
            data-testid="voice-trigger-btn"
            onClick={() => setVoicePanelOpen(true)}
            aria-label="语音输入"
          >
            <MicIcon />
            <span>语音</span>
          </button>
        </div>
      )}
    </div>
  );
}
