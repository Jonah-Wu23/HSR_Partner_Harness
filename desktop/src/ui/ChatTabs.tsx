import { CloseIcon } from "../assets/icons/icons";
import type { ChatTabsViewModel } from "../contracts/view-models";

interface ChatTabsProps {
  tabs: ChatTabsViewModel[];
  onSelect: (conversationId: string) => void;
  onClose: (conversationId: string) => void;
  onOpenWindow: (conversationId: string) => void;
}

/** 标签状态点：运行中 > 等待审批 > 排队中（一次只显示一个最高优先级状态）。 */
function tabStatus(tab: ChatTabsViewModel): { className: string; label: string } | null {
  if (tab.isRunning) return { className: "is-running", label: "运行中" };
  if (tab.isWaitingApproval) return { className: "is-approval", label: "等待审批" };
  if (tab.isQueued) return { className: "is-queued", label: "排队中" };
  return null;
}

/**
 * V0.3.2 M5：聊天标签栏——本窗口打开的聊天标签。
 * 标题来自会话记录（conversation.changed 实时更新）；状态点只反映该聊天
 * 自己的运行/排队/待审批状态，标签是否激活不影响任务执行；
 * 关闭只移除本窗口视图，不取消任务、不关闭会话。
 */
export function ChatTabs({ tabs, onSelect, onClose, onOpenWindow }: ChatTabsProps) {
  if (tabs.length === 0) return null;
  return (
    <div className="chat-tabs-wrap">
      <div className="chat-tabs" role="tablist" aria-label="打开的聊天" data-testid="chat-tabs">
        {tabs.map((tab) => {
          const status = tabStatus(tab);
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
