import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type {
  ActiveTask,
  ApprovalMode,
  ConversationMode,
  Message,
  PendingApproval,
} from "@shared/contracts/protocol";
import { ApprovalCard } from "../../components/cards/ApprovalCard";
import { ArrowDownIcon, BackIcon, MicIcon, StopIcon } from "../../components/cards/icons";
import { DelegationCard, type DelegationStatus } from "../../components/cards/DelegationCard";
import { ToolCard } from "../../components/cards/ToolCard";
import { useMobileStore } from "../../lib/mobileStore";
import { navigateBack } from "../../lib/router";
import { useVoiceCapture } from "../../lib/useVoiceCapture";
import { useVoicePlayback } from "../../lib/voicePlayback";
import { ChatComposer, type ChatComposerTarget } from "./ChatComposer";
import { MessageBubble } from "./MessageBubble";
import { useChatTimeline, type TimelineItem } from "./useChatTimeline";
import "./chat.css";

export interface ChatPageProps {
  conversationId: string;
}

/** 委派卡状态映射：与桌面 presenters.presentDelegation 同语义
（活动任务匹配或 processing → running，failed/cancelled 同名，其余 completed）。 */
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

/** V0.3.4 缺陷 2：origin=character_delegation 的 user 消息不是用户气泡，
渲染为「来自 <角色名> 的委派」卡片（与桌面 presenters 判定一致）。 */
function isDelegationMessage(message: Message): boolean {
  return (
    message.source === "user" &&
    message.origin === "character_delegation" &&
    Boolean(message.delegation_id)
  );
}

/**
 * V0.3.5 手机端聊天页：
 * - 消息时间线与结构化工具卡片混合流（虚拟滚动优化）
 * - 消息来源清晰可区分，思考段默认折叠可展开
 * - 「发给角色」普通消息与「交给助手」委派输入明确区分（V0.3.4）
 * - 会话模式切换控件：委派仅协作模式可用，前置禁用并说明（V0.3.4）
 * - 审批卡可操作：批准/拒绝 + 双端仲裁收敛（V0.3.5）
 * - 手机语音输入：按住说话 / 自动检测 + 转写/TTS 状态反馈（V0.3.5）
 * - 全程仅角色自然语言回复可朗读；助手/工具/思考/系统消息静音
 * - 零 emoji，触控目标 ≥44px
 */
export function ChatPage({ conversationId }: ChatPageProps) {
  const conversation = useMobileStore(
    (state) => state.conversationsById[conversationId],
  );
  const openConversation = useMobileStore((state) => state.openConversation);
  const submitDelegation = useMobileStore((state) => state.submitDelegation);
  const submitMessage = useMobileStore((state) => state.submitMessage);
  const setConversationMode = useMobileStore((state) => state.setConversationMode);
  const resolveApproval = useMobileStore((state) => state.resolveApproval);
  const stopVoicePlayback = useMobileStore((state) => state.stopVoicePlayback);
  const pair = useMobileStore((state) => state.pair);
  const activeTask = useMobileStore((state) => state.activeTask);
  const allApprovals = useMobileStore((state) => state.approvals);
  const allResolved = useMobileStore((state) => state.resolvedApprovals);
  const projects = useMobileStore((state) => state.projects);
  const setApprovalMode = useMobileStore((state) => state.setApprovalMode);

  const approvals = (allApprovals ?? []).filter(
    (a) => a.conversation_id === conversationId,
  );
  const resolvedApprovals = (allResolved ?? []).filter(
    (a) => a.conversation_id === conversationId,
  );

  const [loadError, setLoadError] = useState<string | null>(null);
  const [pinned, setPinned] = useState(true);
  const [target, setTarget] = useState<ChatComposerTarget>("character");
  const [modeSwitching, setModeSwitching] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [resolvingApprovalIds, setResolvingApprovalIds] = useState<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  const voice = useVoiceCapture(conversationId);
  const { playingMessageId } = useVoicePlayback(conversationId);

  // 装载会话
  useEffect(() => {
    setLoadError(null);
    void openConversation(conversationId).catch((err) => {
      const message = err instanceof Error ? err.message : "装载会话失败";
      setLoadError(message);
    });
  }, [conversationId, openConversation]);

  const { items, isStreaming } = useChatTimeline(conversationId);

  const shouldVirtualize = items.length > 40;
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 80,
    overscan: 6,
    getItemKey: (index) => items[index]?.id ?? index,
  });

  const checkPinned = () => {
    const node = scrollRef.current;
    if (!node) return;
    const isNearBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight < 80;
    setPinned(isNearBottom);
  };

  // 近底部自动跟随
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !pinned || items.length === 0) return;

    if (shouldVirtualize) {
      virtualizer.scrollToIndex(items.length - 1, { align: "end" });
    } else {
      node.scrollTop = node.scrollHeight;
    }
  }, [items.length, isStreaming, pinned, shouldVirtualize, virtualizer]);

  useEffect(() => {
    if (shouldVirtualize) {
      virtualizer.measure();
    }
  }, [items, shouldVirtualize, virtualizer]);

  const jumpToLatest = () => {
    const node = scrollRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
    setPinned(true);
  };

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
      // Let It Fail：切换失败如实展示真实错误；last_mode 以服务端事件为准不回滚猜测
      setModeError(err instanceof Error ? err.message : String(err));
    } finally {
      setModeSwitching(false);
    }
  };

  const handleSubmit = (text: string) =>
    target === "assistant" ? submitDelegation(text) : submitMessage(text);

  const handleResolve = async (approvalId: string, decision: string) => {
    setResolvingApprovalIds((prev) => new Set(prev).add(approvalId));
    try {
      await resolveApproval(approvalId, decision);
    } catch {
      // 错误（含 approval_already_resolved）已由 store 写入 resolvedApprovals，
      // 本端只需要让按钮退出提交中状态。
    } finally {
      setResolvingApprovalIds((prev) => {
        const next = new Set(prev);
        next.delete(approvalId);
        return next;
      });
    }
  };

  const characterName = pair?.character?.name || "角色";

  const renderTimelineItem = (item: TimelineItem, key?: string) => {
    if (item.kind === "tool_run") {
      return <ToolCard key={key ?? item.id} run={item.toolRun} />;
    }
    const message = item.message;
    if (isDelegationMessage(message)) {
      return (
        <DelegationCard
          key={key ?? item.id}
          delegationId={message.delegation_id ?? ""}
          fromName={characterName}
          summary={message.text}
          status={delegationStatusOf(message, activeTask)}
        />
      );
    }
    return (
      <MessageBubble
        key={key ?? item.id}
        message={message}
        playingMessageId={playingMessageId}
        onStopPlayback={() => {
          if (playingMessageId) {
            void stopVoicePlayback(playingMessageId);
          }
        }}
      />
    );
  };

  const showVoicePanel = voice.mode !== "off";

  return (
    <main className="mobile-chat-container" data-testid="chat-page">
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

      {/* 装载失败提示 */}
      {loadError ? (
        <div className="mobile-composer-error" style={{ margin: "8px 12px 0" }} role="alert">
          <span className="mobile-composer-error-text">会话装载失败：{loadError}</span>
        </div>
      ) : null}

      {/* V0.3.5：项目审批模式切换——真实调用 project.update_settings。
          三档与桌面一致：请求批准（request_approval）/帮我审核（review）/完全允许运行（full_auto）。 */}
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
                  disabled={project.approval_mode === item.value}
                  onClick={() =>
                    void setApprovalMode(project.project_id, item.value)
                  }
                >
                  {item.label}
                </button>
              ))}
            </div>
          </section>
        );
      })()}

      {/* 审批卡片区：待审批 + 已决收敛 */}
      {approvals.length > 0 || resolvedApprovals.length > 0 ? (
        <section className="mobile-chat-approvals" aria-label="审批操作">
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
                conversation_id: resolved.conversation_id ?? conversationId,
                operation: resolved.operation ?? {
                  tool_kind: "shell",
                  command: null,
                  paths: [],
                  patch_file_count: null,
                  summary: "",
                },
                reason: resolved.reason ?? "",
                task_id: resolved.task_id,
              } as PendingApproval}
              conversationTitle={conversation?.title}
              status="resolved"
              decision={resolved.decision}
              resolvedBy={resolved.resolved_by}
            />
          ))}
        </section>
      ) : null}

      {/* 消息滚动流 */}
      <div
        className="mobile-chat-scroll"
        ref={scrollRef}
        onScroll={checkPinned}
        data-testid="chat-scroll"
      >
        {items.length === 0 ? (
          <div className="mobile-chat-empty">
            <p>暂无消息</p>
            <p className="hint">给角色发消息，或切换到协作模式后把任务交给助手。</p>
          </div>
        ) : shouldVirtualize ? (
          <div
            className="mobile-virtual-container"
            style={{ height: `${virtualizer.getTotalSize()}px` }}
          >
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const item = items[virtualRow.index];
              if (!item) return null;

              return (
                <div
                  key={virtualRow.key}
                  ref={virtualizer.measureElement}
                  data-index={virtualRow.index}
                  className="mobile-virtual-row"
                  style={{
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  {renderTimelineItem(item)}
                </div>
              );
            })}
          </div>
        ) : (
          items.map((item) => renderTimelineItem(item, item.id))
        )}
      </div>

      {/* 回到最新悬浮按钮 */}
      {!pinned && items.length > 0 ? (
        <button
          type="button"
          className="mobile-jump-latest"
          onClick={jumpToLatest}
          aria-label="滚动回到最新消息"
        >
          <ArrowDownIcon />
          <span>回到最新</span>
        </button>
      ) : null}

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

        {/* V0.3.5 语音输入区 */}
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
          ) : showVoicePanel ? (
            <div className="mobile-voice-panel">
              <div className="mobile-voice-mode-switch" role="group" aria-label="语音输入模式">
                <button
                  type="button"
                  className={`mobile-voice-mode-btn${voice.mode === "hold" ? " active" : ""}`}
                  aria-pressed={voice.mode === "hold"}
                  data-testid="voice-mode-hold"
                  onClick={() => {
                    if (voice.mode === "auto") {
                      void voice.stopListening().then(() => voice.activateHold());
                    } else {
                      voice.activateHold();
                    }
                  }}
                >
                  按住说话
                </button>
                <button
                  type="button"
                  className={`mobile-voice-mode-btn${voice.mode === "auto" ? " active" : ""}`}
                  aria-pressed={voice.mode === "auto"}
                  data-testid="voice-mode-auto"
                  onClick={() => {
                    if (voice.mode === "hold") {
                      void voice.stopListening().then(() => voice.toggleAuto());
                    } else {
                      voice.toggleAuto();
                    }
                  }}
                >
                  自动检测
                </button>
              </div>

              {voice.mode === "hold" ? (
                <button
                  type="button"
                  className="mobile-voice-hold-btn"
                  data-testid="voice-hold-btn"
                  aria-label="按住说话"
                  onPointerDown={(e) => {
                    e.preventDefault();
                    voice.activateHold();
                  }}
                  onPointerUp={(e) => {
                    e.preventDefault();
                    voice.deactivateHold();
                  }}
                  onPointerLeave={(e) => {
                    e.preventDefault();
                    voice.deactivateHold();
                  }}
                  onPointerCancel={(e) => {
                    e.preventDefault();
                    voice.deactivateHold();
                  }}
                >
                  <MicIcon />
                  {voice.captureState === "recording" ? "聆听中…" : "按住说话"}
                </button>
              ) : (
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
              )}

              {voice.transcriptText ? (
                <p className="mobile-voice-transcript" data-testid="voice-transcript">
                  {voice.transcriptFinal ? "转写完成" : "转写中"}：{voice.transcriptText}
                </p>
              ) : null}

              {voice.captureError ? (
                <div className="mobile-voice-error" role="alert" data-testid="voice-capture-error">
                  <span>语音失败：{voice.captureError}</span>
                  <button
                    type="button"
                    className="mobile-voice-retry-btn"
                    data-testid="voice-retry-btn"
                    onClick={() => (voice.mode === "hold" ? voice.activateHold() : voice.toggleAuto())}
                  >
                    重试
                  </button>
                </div>
              ) : null}

              <button
                type="button"
                className="mobile-voice-close-btn"
                data-testid="voice-close-btn"
                onClick={() => voice.stopListening()}
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
                onClick={() => voice.toggleAuto()}
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
