import { useState } from "react";
import { navigate } from "../../lib/router";
import { useMobileStore } from "../../lib/mobileStore";
import { NotificationPreferences } from "../../components/NotificationPreferences";
import { PowerStatusBanner } from "../../components/PowerStatusBanner";
import { formatLocalDateTime } from "../../components/formatTime";
import { ConversationBadgeRow } from "./ConversationBadges";
import { ConnectionDetails } from "./ConnectionDetails";
import {
  deriveConversationBadges,
  useConversationBadgeSource,
} from "./useConversationBadges";
import "./ChatListPage.css";

/**
 * 手机端会话列表页。
 *
 * 1. 首次同步完成前：连接异常（unreachable / auth_failed / disconnected）时展示原因与重试或重新配对入口；
 *    连接正常但同步失败时展示原始错误与重新同步入口；其余情况展示骨架屏。
 * 2. 没有项目时引导回桌面端创建项目。
 * 3. 按项目分组展示未归档的会话，点击进入对应聊天。
 */
export function ChatListPage() {
  const projects = useMobileStore((state) => state.projects);
  const bootstrapped = useMobileStore((state) => state.bootstrapped);
  const connection = useMobileStore((state) => state.connection);
  const reconnect = useMobileStore((state) => state.reconnect);
  const syncError = useMobileStore((state) => state.syncError);
  const retrySync = useMobileStore((state) => state.retrySync);
  const powerStatus = useMobileStore((state) => state.powerStatus);
  const badgeSource = useConversationBadgeSource();
  const [repairError, setRepairError] = useState<string | null>(null);
  const [repairing, setRepairing] = useState(false);

  // 「知道了」只收起当前这条警示；电脑状态再次变化（新的 checked_at）时重新出现。
  const [dismissedCheckedAt, setDismissedCheckedAt] = useState<string | null>(null);
  const visiblePowerStatus =
    powerStatus && (!dismissedCheckedAt || powerStatus.checked_at !== dismissedCheckedAt)
      ? powerStatus
      : null;

  const isConnectionDown =
    connection === "unreachable" ||
    connection === "auth_failed" ||
    connection === "disconnected";

  return (
    <main className="page" data-testid="chat-list-page">
      <div className="chat-list-container">
        {/* 电源状态条置于页面所有内容之上。 */}
        {visiblePowerStatus ? (
          <div className="chat-list-power">
            <PowerStatusBanner
              status={visiblePowerStatus}
              onDismiss={() => setDismissedCheckedAt(visiblePowerStatus.checked_at)}
            />
          </div>
        ) : null}

        <header className="chat-list-header">
          <h1 className="page-title">聊天列表</h1>
        </header>
        {repairError && <p role="alert">{repairError}</p>}

        {/* 1. 未水合状态 */}
        {!bootstrapped && (
          <>
            {isConnectionDown ? (
              <section className="card error-state-card" data-testid="chat-list-error">
                <h2 className="error-state-title">数据同步失败</h2>
                <p className="error-state-desc">
                  {connection === "unreachable" &&
                    "无法连接到电脑桌面端，请确认 Sidecar 已以 --serve 运行且网络通畅。"}
                  {connection === "auth_failed" &&
                    "配对鉴权已失效或设备已被撤销，请重新配对。"}
                  {connection === "disconnected" &&
                    "当前与桌面端未建立连接，请重试连接。"}
                </p>
                {connection === "auth_failed" ? (
                  <button
                    type="button"
                    className="primary chat-list-retry-btn"
                    disabled={repairing}
                    onClick={async () => {
                      // 与 ConnectionBanner 一致：先清凭据再跳转，否则被路由守卫弹回。
                      setRepairError(null);
                      setRepairing(true);
                      try {
                        await useMobileStore.getState().disconnect();
                        navigate({ name: "pair" });
                      } catch (error) {
                        console.error("重新配对前释放控制权失败", error);
                        setRepairError(error instanceof Error ? error.message : String(error));
                      } finally {
                        setRepairing(false);
                      }
                    }}
                    data-testid="chat-list-btn-repair"
                  >
                    重新配对
                  </button>
                ) : (
                  <button
                    type="button"
                    className="primary chat-list-retry-btn"
                    onClick={() => reconnect()}
                    data-testid="chat-list-btn-retry"
                  >
                    重试连接
                  </button>
                )}
              </section>
            ) : syncError ? (
              <section className="card error-state-card" data-testid="chat-list-sync-error">
                <h2 className="error-state-title">数据同步失败</h2>
                <p className="error-state-desc" data-testid="chat-list-sync-error-text">
                  {syncError}
                </p>
                <button
                  type="button"
                  className="primary chat-list-retry-btn"
                  onClick={() => {
                    retrySync().catch((error: unknown) => {
                      console.error("重新同步失败", error);
                    });
                  }}
                  data-testid="chat-list-btn-resync"
                >
                  重新同步
                </button>
              </section>
            ) : (
              <div
                className="skeleton-wrapper"
                data-testid="chat-list-skeleton"
                role="status"
                aria-label="正在加载会话列表"
              >
                <div className="skeleton-card">
                  <div className="skeleton-shimmer skeleton-title" />
                  <div className="skeleton-shimmer skeleton-row" />
                  <div className="skeleton-shimmer skeleton-row" />
                </div>
                <div className="skeleton-card">
                  <div className="skeleton-shimmer skeleton-title" />
                  <div className="skeleton-shimmer skeleton-row" />
                </div>
              </div>
            )}
          </>
        )}

        {/* 2. 零项目空态 */}
        {bootstrapped && projects.length === 0 && (
          <section className="card empty-state-card" data-testid="chat-list-empty">
            <h2 className="empty-state-title">暂无项目</h2>
            <p className="empty-state-desc">
              还没有项目。请在电脑端创建项目后，手机端将自动同步项目与聊天。
            </p>
          </section>
        )}

        {/* 3. 正常列表渲染 */}
        {bootstrapped && projects.length > 0 && (
          <div className="project-list" data-testid="chat-list-content">
            {projects.map((project) => {
              const activeConversations = project.conversations.filter((c) => !c.archived);
              return (
                <section
                  key={project.project_id}
                  className="card project-section"
                  data-testid={`project-card-${project.project_id}`}
                >
                  <div className="project-section-header">
                    <h2 className="project-name">{project.name}</h2>
                    <span className="project-count-badge">
                      {activeConversations.length} 个聊天
                    </span>
                  </div>

                  {activeConversations.length === 0 ? (
                    <p className="empty-conv-text">暂无活跃聊天</p>
                  ) : (
                    <div className="conversation-group">
                      {activeConversations.map((conversation) => {
                        const timeText = formatLocalDateTime(conversation.updated_at, "minute");
                        const isCollab = conversation.last_mode === "collaboration";
                        return (
                          <a
                            key={conversation.conversation_id}
                            href={`#/chat/${encodeURIComponent(conversation.conversation_id)}`}
                            className="conversation-row"
                            data-testid={`conversation-item-${conversation.conversation_id}`}
                            onClick={(event) => {
                              event.preventDefault();
                              navigate({
                                name: "chat",
                                conversationId: conversation.conversation_id,
                              });
                            }}
                          >
                            <div className="conversation-info">
                              <span className="conversation-title">
                                {conversation.title || "新聊天"}
                              </span>
                              {timeText && (
                                <time className="conversation-meta-time">
                                  {timeText}
                                </time>
                              )}
                              <ConversationBadgeRow
                                conversationId={conversation.conversation_id}
                                badges={deriveConversationBadges(
                                  conversation.conversation_id,
                                  badgeSource,
                                )}
                              />
                            </div>
                            <span
                              className={`conversation-mode-tag ${
                                isCollab ? "tag-collab" : "tag-chat"
                              }`}
                            >
                              {isCollab ? "委派" : "对话"}
                            </span>
                          </a>
                        );
                      })}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}

        {/* 连接详情抽屉，默认收起。 */}
        {bootstrapped ? <ConnectionDetails /> : null}

        {/* 通知偏好是壳内本地能力，同步失败时也可查看。 */}
        <NotificationPreferences />
      </div>
    </main>
  );
}
