import {
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useShallow } from "zustand/react/shallow";
import type { ApprovalMode, ConversationMode } from "@shared/contracts/protocol";
import { ChatStatusHint } from "../../components/ChatStatusHint";
import { ApprovalCard } from "../../components/cards/ApprovalCard";
import { BackIcon } from "../../components/cards/icons";
import { useMobileStore } from "../../lib/mobileStore";
import { navigateBack } from "../../lib/router";
import { RemoteCommandError } from "../../lib/wsClient";
import { useVoicePlayback } from "../../lib/voicePlayback";
import { ChatComposer, type ChatComposerTarget } from "./ChatComposer";
import { ChatTimeline } from "./ChatTimeline";
import { ChatVoiceBar } from "./ChatVoiceBar";
import { usePlaybackError, usePlaybackErrorCode, usePlaybackInterruption } from "./usePlaybackStatus";
import "./chat.css";

export interface ChatPageProps {
  conversationId: string;
}

/** 布局视口与可视视口相差超过这个值才视为软键盘占位，避免浏览器工具栏伸缩引起抖动。 */
const KEYBOARD_INSET_THRESHOLD_PX = 120;

/** 项目审批模式三档，与桌面一致。 */
const APPROVAL_MODES: Array<{ value: ApprovalMode; label: string }> = [
  { value: "request_approval", label: "请求批准" },
  { value: "review", label: "帮我审核" },
  { value: "full_auto", label: "完全允许运行" },
];

/** 驱动本地朗读。TTS 分片每次到达都会触发它，单独成组件，页面不随分片重新渲染。 */
function VoicePlaybackDriver() {
  useVoicePlayback();
  return null;
}

/**
 * 软键盘占位时让聊天容器贴合可视视口：在动画帧里写 CSS 变量，不触发 React 渲染。
 * visualViewport 是唯一可靠信号（dvh 只跟随浏览器工具栏，不跟随键盘）；不支持它的引擎
 * 由 chat.css 的 100dvh / 100vh 控制高度。iOS Safari 弹出键盘时会平移可视视口，
 * offsetTop 随之写入，容器跟着位移。双指缩放也会缩小可视视口，缩放时不按键盘处理。
 */
function useKeyboardViewport(containerRef: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const viewport = window.visualViewport;
    const node = containerRef.current;
    if (!viewport || !node) return;
    let frame: number | null = null;
    let applied = "";
    const apply = () => {
      frame = null;
      const keyboardOpen =
        viewport.scale === 1 &&
        window.innerHeight - viewport.height > KEYBOARD_INSET_THRESHOLD_PX;
      const height = `${Math.round(viewport.height)}px`;
      const top = `${Math.round(viewport.offsetTop)}px`;
      const next = keyboardOpen ? `${height} ${top}` : "";
      if (next === applied) return;
      applied = next;
      if (keyboardOpen) {
        node.style.setProperty("--chat-viewport-height", height);
        node.style.setProperty("--chat-viewport-top", top);
        node.dataset.keyboard = "open";
      } else {
        node.style.removeProperty("--chat-viewport-height");
        node.style.removeProperty("--chat-viewport-top");
        delete node.dataset.keyboard;
      }
    };
    const schedule = () => {
      if (frame === null) frame = requestAnimationFrame(apply);
    };
    apply();
    viewport.addEventListener("resize", schedule);
    viewport.addEventListener("scroll", schedule);
    return () => {
      if (frame !== null) cancelAnimationFrame(frame);
      viewport.removeEventListener("resize", schedule);
      viewport.removeEventListener("scroll", schedule);
    };
  }, [containerRef]);
}

/**
 * 手机端聊天页：消息与工具卡混合时间线、发给角色与交给助手两种输入、
 * 会话模式与审批模式切换、审批卡、按住说话与自动检测语音输入。
 * 只有角色自然语言回复可朗读，助手、工具、思考与系统消息保持静音。
 * 时间线、语音栏与朗读驱动各自订阅 store，页面只订阅标题、模式、审批与错误状态。
 */
export function ChatPage({ conversationId }: ChatPageProps) {
  const containerRef = useRef<HTMLElement>(null);
  const conversation = useMobileStore(
    (state) => state.conversationsById[conversationId],
  );
  const projectId = conversation?.project_id ?? null;
  const projectApprovalMode = useMobileStore(
    (state) =>
      state.projects.find((project) => project.project_id === projectId)?.approval_mode ?? null,
  );
  const approvals = useMobileStore(
    useShallow((state) => state.approvals.filter((a) => a.conversation_id === conversationId)),
  );
  const resolvedApprovals = useMobileStore(
    useShallow((state) =>
      state.resolvedApprovals.filter((a) => a.conversation_id === conversationId),
    ),
  );
  const { connection, bootstrapped, syncError } = useMobileStore(
    useShallow((state) => ({
      connection: state.connection,
      bootstrapped: state.bootstrapped,
      syncError: state.syncError,
    })),
  );
  const openError = useMobileStore((state) =>
    state.openError?.conversationId === conversationId ? state.openError.message : null,
  );
  const {
    openConversation,
    submitDelegation,
    submitMessage,
    setConversationMode,
    resolveApproval,
    setApprovalMode,
    retrySync,
  } = useMobileStore(
    useShallow((state) => ({
      openConversation: state.openConversation,
      submitDelegation: state.submitDelegation,
      submitMessage: state.submitMessage,
      setConversationMode: state.setConversationMode,
      resolveApproval: state.resolveApproval,
      setApprovalMode: state.setApprovalMode,
      retrySync: state.retrySync,
    })),
  );

  const [target, setTarget] = useState<ChatComposerTarget>("character");
  const [modeSwitching, setModeSwitching] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [approvalModeSwitching, setApprovalModeSwitching] = useState(false);
  const [approvalModeError, setApprovalModeError] = useState<string | null>(null);
  const [resolvingApprovalIds, setResolvingApprovalIds] = useState<Set<string>>(new Set());
  // 审批提交的错误与已被另一端裁决的通知，按 approval_id 在页内展示。
  const [approvalErrors, setApprovalErrors] = useState<Record<string, string>>({});
  const [approvalNotices, setApprovalNotices] = useState<Record<string, string>>({});

  const playbackError = usePlaybackError();
  const playbackErrorCode = usePlaybackErrorCode();
  const playbackInterruption = usePlaybackInterruption(conversationId);

  // 装载会话：失败写入 store.openError，页面展示原始错误与重试入口。
  const loadConversation = useCallback(() => {
    openConversation(conversationId).catch((err: unknown) => {
      console.error("会话装载失败", conversationId, err);
    });
  }, [conversationId, openConversation]);

  // 在绘制前切换当前聊天，首帧就是该聊天的缓存时间线或骨架。
  useLayoutEffect(() => {
    loadConversation();
  }, [loadConversation]);

  useKeyboardViewport(containerRef);

  const mode: ConversationMode = conversation?.last_mode === "collaboration" ? "collaboration" : "chat";
  const modeText = mode === "collaboration" ? "协作模式" : "对话模式";
  const assistantBlocked = target === "assistant" && mode !== "collaboration";

  const handleModeChange = async (next: ConversationMode) => {
    if (modeSwitching || next === mode) return;
    setModeSwitching(true);
    setModeError(null);
    try {
      await setConversationMode(conversationId, next);
    } catch (err) {
      // last_mode 以服务端事件为准，这里只展示失败原因。
      setModeError(err instanceof Error ? err.message : String(err));
    } finally {
      setModeSwitching(false);
    }
  };

  // 显式带上本页的 conversationId：装载失败或切换途中也不会发到别的聊天。
  const handleSubmit = (text: string) =>
    target === "assistant"
      ? submitDelegation(conversationId, text)
      : submitMessage(conversationId, text);

  const handleApprovalModeChange = async (projectId: string, next: ApprovalMode) => {
    setApprovalModeSwitching(true);
    setApprovalModeError(null);
    try {
      await setApprovalMode(projectId, next);
    } catch (err) {
      setApprovalModeError(err instanceof Error ? err.message : String(err));
    } finally {
      setApprovalModeSwitching(false);
    }
  };

  const clearApprovalFeedback = (approvalId: string) => {
    setApprovalErrors((prev) => {
      if (!(approvalId in prev)) return prev;
      const next = { ...prev };
      delete next[approvalId];
      return next;
    });
    setApprovalNotices((prev) => {
      if (!(approvalId in prev)) return prev;
      const next = { ...prev };
      delete next[approvalId];
      return next;
    });
  };

  const handleResolve = async (approvalId: string, decision: string) => {
    setResolvingApprovalIds((prev) => new Set(prev).add(approvalId));
    clearApprovalFeedback(approvalId);
    try {
      await resolveApproval(approvalId, decision);
    } catch (err) {
      // approval_already_resolved 表示另一端已裁决，展示服务端原文作为通知；其余错误连同 code 展示。
      const code = err instanceof RemoteCommandError ? err.code : "";
      const message = err instanceof Error ? err.message : String(err);
      if (code === "approval_already_resolved") {
        setApprovalNotices((prev) => ({ ...prev, [approvalId]: message }));
      } else {
        setApprovalErrors((prev) => ({
          ...prev,
          [approvalId]: code ? `${code}：${message}` : message,
        }));
      }
    } finally {
      setResolvingApprovalIds((prev) => {
        const next = new Set(prev);
        next.delete(approvalId);
        return next;
      });
    }
  };

  return (
    <main className="mobile-chat-container" data-testid="chat-page" ref={containerRef}>
      <VoicePlaybackDriver />
      {/* 顶栏：返回按钮 + 标题与模式 + 状态 */}
      <header className="mobile-chat-header">
        <button
          type="button"
          className="mobile-chat-back-btn"
          onClick={() => navigateBack({ name: "list" })}
          aria-label="返回聊天列表"
        >
          <BackIcon />
          <span>返回</span>
        </button>

        <div className="mobile-chat-title-group">
          <h1 className="mobile-chat-title">
            {conversation?.title || "新聊天"}
          </h1>
          <span className="mobile-chat-subtitle">{modeText}</span>
        </div>
      </header>

      {/* 装载失败：停在本聊天，展示原始错误并提供重试 */}
      {openError ? (
        <div
          className="mobile-composer-error"
          style={{ margin: "8px 12px 0" }}
          role="alert"
          data-testid="chat-open-error"
        >
          <span className="mobile-composer-error-text">会话装载失败：{openError}</span>
          <button
            type="button"
            className="mobile-open-retry-btn"
            onClick={loadConversation}
            data-testid="chat-open-retry"
          >
            重试
          </button>
        </div>
      ) : syncError ? (
        <div
          className="mobile-composer-error"
          style={{ margin: "8px 12px 0" }}
          role="alert"
          data-testid="chat-sync-error"
        >
          <span className="mobile-composer-error-text">同步失败：{syncError}</span>
          <button
            type="button"
            className="mobile-open-retry-btn"
            onClick={() => {
              retrySync().catch((err: unknown) => console.error("重新同步失败", err));
            }}
            data-testid="chat-sync-retry"
          >
            重新同步
          </button>
        </div>
      ) : null}

      {/* 连接状态由顶部 ConnectionBanner 展示，这里只提示正在重新同步。 */}
      <ChatStatusHint
        resyncing={!bootstrapped && connection === "connected" && !syncError && !openError}
      />

      {/* 页级播放错误条：消息移出虚拟列表窗口后气泡内的提示不可见，错误码与原文在这里展示。 */}
      {playbackError ? (
        <div className="mobile-playback-error" role="alert" data-testid="playback-error-bar">
          <span className="mobile-playback-error-label">朗读失败</span>
          {playbackErrorCode ? (
            <code className="mobile-playback-error-code" data-testid="playback-error-code">
              {playbackErrorCode}
            </code>
          ) : null}
          <span className="mobile-playback-error-text" data-testid="playback-error-text">
            {playbackError}
          </span>
        </div>
      ) : null}

      {/* 朗读被打断（voice.playback_interrupted）；reason 有值才展示原因。 */}
      {playbackInterruption ? (
        <div
          className="mobile-playback-interrupted"
          role="status"
          data-testid="playback-interrupted"
        >
          <span className="mobile-playback-interrupted-text">已被新回复打断 / 已停止</span>
          {playbackInterruption.reason ? (
            <span
              className="mobile-playback-interrupted-reason"
              data-testid="playback-interrupted-reason"
            >
              {playbackInterruption.reason}
            </span>
          ) : null}
        </div>
      ) : null}

      {/* 项目审批模式切换（project.update_settings），三档与桌面一致；切换失败在本区展示。 */}
      {projectId && projectApprovalMode ? (
        <section className="mobile-approval-mode" aria-label="审批模式切换">
          <span className="mobile-approval-mode-label">审批模式</span>
          <div className="mobile-approval-mode-options" role="group">
            {APPROVAL_MODES.map((item) => (
              <button
                key={item.value}
                type="button"
                className={`mobile-approval-mode-option${
                  projectApprovalMode === item.value ? " is-active" : ""
                }`}
                data-testid={`approval-mode-${item.value}`}
                disabled={approvalModeSwitching || projectApprovalMode === item.value}
                onClick={() => void handleApprovalModeChange(projectId, item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          {approvalModeError ? (
            <p
              className="mobile-composer-hint mobile-composer-hint-error"
              role="alert"
              data-testid="approval-mode-error"
            >
              审批模式切换失败：{approvalModeError}
            </p>
          ) : null}
        </section>
      ) : null}

      {/* 审批卡片区：待审批 + 已决收敛 */}
      {approvals.length > 0 ||
      resolvedApprovals.length > 0 ||
      Object.keys(approvalErrors).length > 0 ||
      Object.keys(approvalNotices).length > 0 ? (
        <section className="mobile-chat-approvals" aria-label="审批操作">
          {Object.entries(approvalErrors).map(([approvalId, message]) => (
            <p
              key={`approval-error-${approvalId}`}
              className="mobile-approval-error"
              role="alert"
              data-testid="approval-resolve-error"
            >
              审批提交失败：{message}
            </p>
          ))}
          {Object.entries(approvalNotices).map(([approvalId, message]) => (
            <p
              key={`approval-notice-${approvalId}`}
              className="mobile-approval-notice"
              role="status"
              data-testid="approval-resolve-notice"
            >
              审批已由服务端终态收敛：{message}
            </p>
          ))}
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.approval_id}
              approval={approval}
              conversationTitle={conversation?.title}
              resolving={resolvingApprovalIds.has(approval.approval_id)}
              onApprove={() => void handleResolve(approval.approval_id, "allow")}
              onAllowForConversation={() =>
                void handleResolve(approval.approval_id, "allow_for_conversation")
              }
              onReject={() => void handleResolve(approval.approval_id, "deny")}
            />
          ))}
          {resolvedApprovals.map((resolved) => (
            <ApprovalCard
              key={resolved.approval_id}
              approval={{
                approval_id: resolved.approval_id,
                operation: resolved.operation,
                reason: resolved.request_reason,
              }}
              conversationTitle={conversation?.title}
              status="resolved"
              decision={resolved.decision}
              resolvedBy={resolved.resolved_by}
              actor={resolved.actor}
              resolutionReason={resolved.resolution_reason}
              errorCode={resolved.error_code}
              resolvedAt={resolved.resolved_at}
            />
          ))}
        </section>
      ) : null}

      {/* 消息滚动流 */}
      <ChatTimeline conversationId={conversationId} />

      {/* 输入区：会话模式切换 + 发送目标切换 + 语音入口 + 输入框 */}
      <footer className="mobile-composer" data-testid="chat-composer-area">
        <div className="mobile-chat-controls">
          <div className="mobile-segmented" role="group" aria-label="会话模式切换">
            <button
              type="button"
              className={`mobile-segmented-btn${mode === "chat" ? " active" : ""}`}
              aria-pressed={mode === "chat"}
              data-testid="mode-btn-chat"
              disabled={modeSwitching}
              onClick={() => void handleModeChange("chat")}
            >
              对话
            </button>
            <button
              type="button"
              className={`mobile-segmented-btn${mode === "collaboration" ? " active" : ""}`}
              aria-pressed={mode === "collaboration"}
              data-testid="mode-btn-collaboration"
              disabled={modeSwitching}
              onClick={() => void handleModeChange("collaboration")}
            >
              协作
            </button>
          </div>
          <div className="mobile-segmented" role="group" aria-label="发送目标切换">
            <button
              type="button"
              className={`mobile-segmented-btn${target === "character" ? " active" : ""}`}
              aria-pressed={target === "character"}
              data-testid="target-btn-character"
              onClick={() => setTarget("character")}
            >
              发给角色
            </button>
            <button
              type="button"
              className={`mobile-segmented-btn${target === "assistant" ? " active" : ""}`}
              aria-pressed={target === "assistant"}
              data-testid="target-btn-assistant"
              onClick={() => setTarget("assistant")}
            >
              交给助手
            </button>
          </div>
        </div>
        {modeError ? (
          <p className="mobile-composer-hint mobile-composer-hint-error" role="alert" data-testid="mode-switch-error">
            模式切换失败：{modeError}
          </p>
        ) : null}

        {/* 语音输入区 */}
        <ChatVoiceBar conversationId={conversationId} />

        <ChatComposer
          target={target}
          disabled={assistantBlocked}
          disabledHint={assistantBlocked
            ? "对话模式下助手不接收委派，请先切换到协作模式。"
            : null}
          onSubmit={handleSubmit}
        />
      </footer>
    </main>
  );
}
