import { navigate } from "../../lib/router";
import { useMobileStore } from "../../lib/mobileStore";

/**
 * V0.3.3 手机端会话列表页（骨架，W4 做视觉与交互细化）。
 * 骨架即提供真实列表渲染，保证配对后链路可手动走通。
 */
export function ChatListPage() {
  const projects = useMobileStore((state) => state.projects);
  const bootstrapped = useMobileStore((state) => state.bootstrapped);

  return (
    <main className="page" data-testid="chat-list-page">
      <h1 className="page-title">聊天</h1>
      {!bootstrapped ? <p className="hint">加载中…</p> : null}
      {bootstrapped && projects.length === 0 ? (
        <p className="hint">还没有项目。回桌面端创建项目后，这里会出现它的聊天。</p>
      ) : null}
      {projects.map((project) => (
        <section key={project.project_id} className="card">
          <strong>{project.name}</strong>
          {(project.conversations ?? [])
            .filter((conversation) => !conversation.archived)
            .map((conversation) => (
              <p key={conversation.conversation_id} style={{ margin: "8px 0 0" }}>
                <a
                  href={`#/chat/${encodeURIComponent(conversation.conversation_id)}`}
                  onClick={(event) => {
                    event.preventDefault();
                    navigate({ name: "chat", conversationId: conversation.conversation_id });
                  }}
                >
                  {conversation.title || "新聊天"}
                </a>
              </p>
            ))}
        </section>
      ))}
    </main>
  );
}
