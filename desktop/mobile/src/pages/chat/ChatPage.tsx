import { useCallback, useEffect, useState } from "react";
import type {
  ActiveTask,
  ApprovalMode,
  ConversationMode,
  Message,
} from "@shared/contracts/protocol";
import { ChatStatusHint } from "../../components/ChatStatusHint";
import { ApprovalCard } from "../../components/cards/ApprovalCard";
import { BackIcon, MicIcon, StopIcon } from "../../components/cards/icons";
import { DelegationCard, type DelegationStatus } from "../../components/cards/DelegationCard";
import { ToolCard } from "../../components/cards/ToolCard";
import { ConversationList, type ConversationItemState } from "@shared/ui/conversation/ConversationList";
import { useMobileStore } from "../../lib/mobileStore";
import { navigateBack } from "../../lib/router";
import { RemoteCommandError } from "../../lib/wsClient";
import { useVoiceCapture } from "../../lib/useVoiceCapture";
import { useVoicePlayback } from "../../lib/voicePlayback";
import { ChatComposer, type ChatComposerTarget } from "./ChatComposer";
import { MessageBubble } from "./MessageBubble";
import { QueueItemRow } from "./QueueItemRow";
import { useChatTimeline, type TimelineItem } from "./useChatTimeline";
import { usePlaybackErrorCode, usePlaybackInterruption } from "./usePlaybackStatus";
import "./chat.css";

export interface ChatPageProps {
  conversationId: string;
}

/** 委派卡状态，与桌面 presenters.presentDelegation 同语义：
活动任务匹配或 processing 为 running，failed / cancelled 同名，其余为 completed。 */
function delegationStatusOf(
  message: Message,
  activeTask: ActiveTask | null,
): DelegationStatus {
  if (activeTask?.task_id && activeTask.task_id === message.delegation_id) {
    return "running";
  }
  if (message.status === "processing") return "running";
  if (message.status === "failed") return "failed";
  if (message.status === "cancelled") return "cancelled";
  return "completed";
}

/** origin=character_delegation 的 user 消息渲染为「来自 <角色名> 的委派」卡片，与桌面 presenters 判定一致。 */
function isDelegationMessage(message: Message): boolean {
  return (
    message.source === "user" &&
    message.origin === "character_delegation" &&
    Boolean(message.delegation_id)
  );
}

/**
 * 手机端聊天页：消息与工具卡混合时间线、发给角色与交给助手两种输入、
 * 会话模式与审批模式切换、审批卡、按住说话与自动检测语音输入。
 * 只有角色自然语言回复可朗读，助手、工具、思考与系统消息保持静音。
 */
export function ChatPage({ conversationId }: ChatPageProps) {
  const conversation = useMobileStore(
    (state) => state.conversationsById[conversationId],
  );
  const openConversation = useMobileStore((state) => state.openConversation);
  const submitDelegation = useMobileStore((state) => state.submitDelegation);
  const submitMessage = useMobileStore((state) => state.submitMessage);
  const withdrawQueueItem = useMobileStore((state) => state.withdrawQueueItem);
  const editQueueItem = useMobileStore((state) => state.editQueueItem);
  const prioritizeQueueItem = useMobileStore((state) => state.prioritizeQueueItem);
  const setConversationMode = useMobileStore((state) => state.setConversationMode);
  const resolveApproval = useMobileStore((state) => state.resolveApproval);
  const stopVoicePlayback = useMobileStore((state) => state.stopVoicePlayback);
  const pair = useMobileStore((state) => state.pair);
  const activeTask = useMobileStore((state) => state.activeTask);
  const allApprovals = useMobileStore((state) => state.approvals);
  const allResolved = useMobileStore((state) => state.resolvedApprovals);
  const projects = useMobileStore((state) => state.projects);
  const setApprovalMode = useMobileStore((state) => state.setApprovalMode);
  const connection = useMobileStore((state) => state.connection);
  const bootstrapped = useMobileStore((state) => state.bootstrapped);
  const openError = useMobileStore((state) =>
    state.openError?.conversationId === conversationId ? state.openError.message : null,
  );
  const syncError = useMobileStore((state) => state.syncError);
  const retrySync = useMobileStore((state) => state.retrySync);

  const approvals = allApprovals.filter((a) => a.conversation_id === conversationId);
  const resolvedApprovals = allResolved.filter((a) => a.conversation_id === conversationId);

  const [target, setTarget] = useState<ChatComposerTarget>("character");
  const [modeSwitching, setModeSwitching] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [approvalModeSwitching, setApprovalModeSwitching] = useState(false);
  const [approvalModeError, setApprovalModeError] = useState<string | null>(null);
  const [resolvingApprovalIds, setResolvingApprovalIds] = useState<Set<string>>(new Set());
  // 审批提交的错误与已被另一端裁决的通知，按 approval_id 在页内展示。
  const [approvalErrors, setApprovalErrors] = useState<Record<string, string>>({});
  const [approvalNotices, setApprovalNotices] = useState<Record<string, string>>({});
  // 软键盘占位高度（visualViewport 驱动）；键盘未占位或引擎不支持时为 null。
  const [keyboardViewportHeight, setKeyboardViewportHeight] = useState<number | null>(null);
  // 语音面板开合与采集模式相互独立：打开面板不开始采集，采集失败也不关面板。
  const [voicePanelOpen, setVoicePanelOpen] = useState(false);

  const voice = useVoiceCapture(conversationId);
  const { playingMessageId, playbackMessageId, playbackError } = useVoicePlayback();
  const playbackErrorCode = usePlaybackErrorCode();
  const playbackInterruption = usePlaybackInterruption(conversationId);

  // 装载会话：失败写入 store.openError，页面展示原始错误与重试入口。
  const loadConversation = useCallback(() => {
    openConversation(conversationId).catch((err: unknown) => {
      console.error("会话装载失败", conversationId, err);
    });
  }, [conversationId, openConversation]);

  useEffect(() => {
    loadConversation();
  }, [loadConversation]);

  // 软键盘：visualViewport 是唯一可靠信号（dvh 只跟随浏览器工具栏，不跟随键盘）；
  // 不支持 visualViewport 的引擎由 chat.css 的 100dvh / 100vh 控制高度。
  // 布局视口与可视视口相差超过 120px 才视为键盘占位，避免工具栏伸缩引起抖动。
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const sync = () => {
      const inset = Math.round(window.innerHeight - viewport.height);
      setKeyboardViewportHeight(inset > 120 ? Math.round(viewport.height) : null);
    };
    sync();
    viewport.addEventListener("resize", sync);
    viewport.addEventListener("scroll", sync);
    return () => {
      viewport.removeEventListener("resize", sync);
      viewport.removeEventListener("scroll", sync);
    };
  }, []);

  const items = useChatTimeline(conversationId);

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

  const characterName = pair?.character?.name || "角色";
  const pairNames = { character: pair?.character?.name, assistant: pair?.assistant?.name };

  const renderTimelineItem = (item: TimelineItem, itemState: ConversationItemState) => {
    if (item.kind === "tool_run") {
      return (
        <ToolCard
          run={item.toolRun}
          expanded={itemState.isExpanded(`tool:${item.toolRun.tool_call_id}`)}
          onExpandedChange={(expanded) => itemState.setExpanded(`tool:${item.toolRun.tool_call_id}`, expanded)}
        />
      );
    }
    if (item.kind === "queue_item") {
      // 命令失败由排队行内展示。
      return (
        <QueueItemRow
          queueItem={item.queueItem}
          onWithdraw={() => withdrawQueueItem(item.queueItem.queue_item_id)}
          onPrioritize={() => prioritizeQueueItem(item.queueItem.queue_item_id)}
          onEdit={(text) => editQueueItem(item.queueItem.queue_item_id, text)}
        />
      );
    }
    const message = item.message;
    if (isDelegationMessage(message)) {
      return (
        <DelegationCard
          delegationId={message.delegation_id ?? ""}
          fromName={characterName}
          summary={message.text}
          status={delegationStatusOf(message, activeTask)}
        />
      );
    }
    return (
      <MessageBubble
        message={message}
        pairNames={pairNames}
        itemState={itemState}
        playingMessageId={playingMessageId}
        playbackError={
          message.message_id === playbackMessageId ? playbackError : null
        }
        onStopPlayback={() => {
          if (!playingMessageId) return;
          // 停止失败已写入 playback.error，由页级播放错误条展示。
          stopVoicePlayback(playingMessageId).catch((err: unknown) => {
            console.error("停止朗读失败", playingMessageId, err);
          });
        }}
      />
    );
  };

  // 键盘占位时把聊天容器压到 visualViewport 高度，其余时候由 chat.css 控制。
  const viewportStyle = keyboardViewportHeight
    ? { height: `${keyboardViewportHeight}px`, maxHeight: `${keyboardViewportHeight}px` }
    : undefined;

  return (
    <main className="mobile-chat-container" data-testid="chat-page" style={viewportStyle}>
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
      {(() => {
        const project = projects.find(
          (item) => item.project_id === conversation?.project_id,
        );
        if (!project) return null;
        const approvalModes: Array<{ value: ApprovalMode; label: string }> = [
          { value: "request_approval", label: "请求批准" },
          { value: "review", label: "帮我审核" },
          { value: "full_auto", label: "完全允许运行" },
        ];
        return (
          <section className="mobile-approval-mode" aria-label="审批模式切换">
            <span className="mobile-approval-mode-label">审批模式</span>
            <div className="mobile-approval-mode-options" role="group">
              {approvalModes.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={`mobile-approval-mode-option${
                    project.approval_mode === item.value ? " is-active" : ""
                  }`}
                  data-testid={`approval-mode-${item.value}`}
                  disabled={approvalModeSwitching || project.approval_mode === item.value}
                  onClick={() => void handleApprovalModeChange(project.project_id, item.value)}
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
        );
      })()}

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
      <ConversationList
        conversationId={conversationId}
        items={items}
        getItemKey={(item) => item.id}
        estimateSize={80}
        overscan={6}
        scrollClassName="mobile-chat-scroll"
        contentClassName="mobile-virtual-container"
        rowClassName="mobile-virtual-row"
        scrollTestId="chat-scroll"
        tabIndex={-1}
        emptyContent={(
          <div className="mobile-chat-empty">
            <p>暂无消息</p>
            <p className="hint">给角色发消息，或切换到协作模式后把任务交给助手。</p>
          </div>
        )}
        renderItem={renderTimelineItem}
        renderJumpButton={(jump) => (
          <button
            type="button"
            className="mobile-jump-latest"
            onClick={jump}
            aria-label="滚动回到最新消息"
          >
            <span>回到最新</span>
          </button>
        )}
      />

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
