import { CloseIcon } from "../assets/icons/icons";
import type { ChatTabsViewModel } from "../contracts/view-models";

export interface ExtendedChatTabsViewModel extends ChatTabsViewModel {
  /** 待真实接线：逻辑轨 store 本地未读推导后下发 */
  unreadCount?: number;
  /** 待真实接线：任务/回合完成反馈状态 */
  isCompleted?: boolean;
}

interface ChatTabsProps {
  tabs: ExtendedChatTabsViewModel[];
  onSelect: (conversationId: string) => void;
  onClose: (conversationId: string) => void;
  onOpenWindow: (conversationId: string) => void;
}

/** 标签状态点：运行中 > 等待审批 > 排队中 > 已完成（一次只显示一个最高优先级状态）。 */
function tabStatus(tab: ExtendedChatTabsViewModel): { className: string; label: string } | null {
  if (tab.isRunning) return { className: "is-running", label: "运行中" };
  if (tab.isWaitingApproval) return { className: "is-approval", label: "等待审批" };
  if (tab.isQueued) return { className: "is-queued", label: "排队中" };
  if (tab.isCompleted) return { className: "is-completed", label: "已完成" };
  return null;
}

/**
 * V0.3.2 M5 / V0.3.9 V01：聊天标签栏——本窗口打开的聊天标签。
 * 标题来自会话记录（conversation.changed 实时更新）；状态点反映该聊天
 * 自己的运行/排队/待审批/已完成状态与本地未读徽章。
 */
export function ChatTabs({ tabs, onSelect, onClose, onOpenWindow }: ChatTabsProps) {
  if (tabs.length === 0) return null;
  return (
    <div className="chat-tabs-wrap">
      <div className="chat-tabs" role="tablist" aria-label="打开的聊天" data-testid="chat-tabs">
        {tabs.map((tab) => {
          const status = tabStatus(tab);
          const hasUnread = typeof tab.unreadCount === "number" && tab.unreadCount > 0;
          return (
            <div
              key={tab.conversationId}
              className={`chat-tab${tab.isActive ? " is-active" : ""}`}
            >
              <button
                type="button"
                role="tab"
                aria-selected={tab.isActive}
                className="chat-tab-main"
                onClick={() => onSelect(tab.conversationId)}
                title={tab.title}
              >
                {status ? (
                  <span
                    className={`chat-tab-dot ${status.className}`}
                    aria-hidden
                    title={status.label}
                  />
                ) : null}
                <span className="chat-tab-title">{tab.title}</span>
                {hasUnread ? (
                  <span
                    className="chat-tab-unread-badge"
                    aria-label={`${tab.unreadCount} 条未读`}
                  >
                    {tab.unreadCount! > 99 ? "99+" : tab.unreadCount}
                  </span>
                ) : null}
              </button>
              <button
                type="button"
                className="icon-btn chat-tab-close"
                aria-label={`关闭标签：${tab.title}`}
                title="关闭标签（不影响正在运行的任务）"
                onClick={() => onClose(tab.conversationId)}
              >
                <CloseIcon />
              </button>
              <button
                type="button"
                className="icon-btn chat-tab-window"
                aria-label={`在新窗口打开：${tab.title}`}
                title="在独立窗口打开此聊天"
                onClick={() => onOpenWindow(tab.conversationId)}
              >
                ↗
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
