import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ActiveTask, ConversationMode, Message } from "@shared/contracts/protocol";
import { ApprovalCard } from "../../components/cards/ApprovalCard";
import { ArrowDownIcon, BackIcon } from "../../components/cards/icons";
import { DelegationCard, type DelegationStatus } from "../../components/cards/DelegationCard";
import { ToolCard } from "../../components/cards/ToolCard";
import { useMobileStore } from "../../lib/mobileStore";
import { navigate } from "../../lib/router";
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
 * V0.3.3 手机端聊天页：
 * - 消息时间线与结构化工具卡片混合流（虚拟滚动优化）
 * - 消息来源清晰可区分，思考段默认折叠可展开
 * - 「发给角色」普通消息与「交给助手」委派输入明确区分（V0.3.4）
 * - 会话模式切换控件：委派仅协作模式可用，前置禁用并说明（V0.3.4）
 * - 等待审批只读卡片（严禁批准/拒绝按钮，标注「请在电脑端处理」）
 * - 全程静音，零 emoji，触控目标 ≥44px
 */
export function ChatPage({ conversationId }: ChatPageProps) {
  const conversation = useMobileStore(
    (state) => state.conversationsById[conversationId],
  );
  const openConversation = useMobileStore((state) => state.openConversation);
  const submitDelegation = useMobileStore((state) => state.submitDelegation);
  const submitMessage = useMobileStore((state) => state.submitMessage);
  const setConversationMode = useMobileStore((state) => state.setConversationMode);
  const pair = useMobileStore((state) => state.pair);
  const activeTask = useMobileStore((state) => state.activeTask);
  const allApprovals = useMobileStore((state) => state.approvals);
  const approvals = (allApprovals ?? []).filter(
    (a) => a.conversation_id === conversationId,
  );

  const [loadError, setLoadError] = useState<string | null>(null);
  const [pinned, setPinned] = useState(true);
  const [target, setTarget] = useState<ChatComposerTarget>("character");
  const [modeSwitching, setModeSwitching] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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
    return <MessageBubble key={key ?? item.id} message={message} />;
  };

  return (
    <main className="mobile-chat-container" data-testid="chat-page">
      {/* 顶栏：返回按钮 + 标题与模式 + 状态 */}
      <header className="mobile-chat-header">
        <button
          type="button"
          className="mobile-chat-back-btn"
          onClick={() => navigate({ name: "list" })}
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

      {/* 等待审批只读卡片区 */}
      {approvals.length > 0 ? (
        <section className="mobile-chat-approvals" aria-label="待审批操作">
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.approval_id}
              approval={approval}
              conversationTitle={conversation?.title}
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

      {/* 输入区：会话模式切换 + 发送目标切换 + 输入框（V0.3.4 缺陷 3/4） */}
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

