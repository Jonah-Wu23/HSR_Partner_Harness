import { navigate } from "../../lib/router";
import { useMobileStore } from "../../lib/mobileStore";
import "./ChatListPage.css";

function formatDateTime(isoString?: string | null): string {
  if (!isoString) return "";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    return `${y}-${m}-${d} ${hh}:${mm}`;
  } catch {
    return isoString;
  }
}

/**
 * V0.3.3 手机端会话列表页。
 *
 * 状态处理：
 * 1. 未水合 (!bootstrapped)：
 *    - 若连接处于异常态 (unreachable / auth_failed / disconnected)，展示真实错误与重试/重新配对入口；
 *    - 否则展示骨架屏 (Skeleton)。
 * 2. 零项目空态 (bootstrapped && projects.length === 0)：引导回桌面端创建项目。
 * 3. 项目分组渲染：按项目展示会话（过滤 archived），点击进入对应聊天。
 */
export function ChatListPage() {
  const projects = useMobileStore((state) => state.projects);
  const bootstrapped = useMobileStore((state) => state.bootstrapped);
  const connection = useMobileStore((state) => state.connection);
  const reconnect = useMobileStore((state) => state.reconnect);

  const isConnectionDown =
    connection === "unreachable" ||
    connection === "auth_failed" ||
    connection === "disconnected";

  return (
    <main className="page" data-testid="chat-list-page">
      <div className="chat-list-container">
        <header className="chat-list-header">
          <h1 className="page-title">聊天列表</h1>
        </header>

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
                    onClick={() => navigate({ name: "pair" })}
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
              const activeConversations = (project.conversations ?? []).filter(
                (c) => !c.archived,
              );
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
                        const timeText = formatDateTime(
                          conversation.updated_at || conversation.created_at,
                        );
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
      </div>
    </main>
  );
}
