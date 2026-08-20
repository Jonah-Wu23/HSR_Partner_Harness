import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ConnectionBanner } from "../../components/ConnectionBanner";
import { ApprovalCard } from "../../components/cards/ApprovalCard";
import { ArrowDownIcon, BackIcon } from "../../components/cards/icons";
import { ToolCard } from "../../components/cards/ToolCard";
import { useMobileStore } from "../../lib/mobileStore";
import { navigate } from "../../lib/router";
import { DelegationComposer } from "./DelegationComposer";
import { MessageBubble } from "./MessageBubble";
import { useChatTimeline } from "./useChatTimeline";
import "./chat.css";

export interface ChatPageProps {
  conversationId: string;
}

/**
 * V0.3.3 手机端聊天页：
 * - 消息时间线与结构化工具卡片混合流（虚拟滚动优化）
 * - 消息来源清晰可区分，思考段默认折叠可展开
 * - 「交给助手」委派输入区与任务执行状态展示
 * - 等待审批只读卡片（严禁批准/拒绝按钮，标注「请在电脑端处理」）
 * - 全程静音，零 emoji，触控目标 ≥44px
 */
export function ChatPage({ conversationId }: ChatPageProps) {
  const conversation = useMobileStore(
    (state) => state.conversationsById[conversationId],
  );
  const openConversation = useMobileStore((state) => state.openConversation);
  const submitDelegation = useMobileStore((state) => state.submitDelegation);
  const allApprovals = useMobileStore((state) => state.approvals);
  const approvals = (allApprovals ?? []).filter(
    (a) => a.conversation_id === conversationId,
  );
  const connection = useMobileStore((state) => state.connection);

  const [loadError, setLoadError] = useState<string | null>(null);
  const [pinned, setPinned] = useState(true);
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

  const modeText =
    conversation?.last_mode === "collaboration"
      ? "协作模式"
      : "对话模式";

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

      {/* 连接状态条（W4 提供的全局连接提示） */}
      <ConnectionBanner connection={connection} />

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
            <p className="hint">输入任务交给助手执行，或在电脑端继续对话。</p>
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
                  {item.kind === "message" ? (
                    <MessageBubble message={item.message} />
                  ) : (
                    <ToolCard run={item.toolRun} />
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          items.map((item) =>
            item.kind === "message" ? (
              <MessageBubble key={item.id} message={item.message} />
            ) : (
              <ToolCard key={item.id} run={item.toolRun} />
            ),
          )
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

      {/* 委派输入区 */}
      <DelegationComposer
        onSubmit={async (text) => {
          await submitDelegation(text);
        }}
      />
    </main>
  );
}
