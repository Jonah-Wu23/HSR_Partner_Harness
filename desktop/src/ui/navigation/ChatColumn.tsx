import { useMemo, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { ConversationViewModel, NavigationViewModel } from "../../contracts/view-models";
import {
  AddConversationIcon,
  CheckIcon,
  CloseIcon,
  CollapseIcon,
  DarkModeIcon,
  DeleteIcon,
  EditIcon,
  LightModeIcon,
  MoreIcon,
  SearchIcon,
  SettingIcon,
  WarningIcon,
} from "../../assets/icons/icons";
import { Menu } from "../primitives/Menu";
import { isSameDay, relativeTime } from "../format";

interface ChatColumnProps {
  navigation: NavigationViewModel;
  theme: "dark" | "light";
  actions: HarnessActions;
  onCollapse: () => void;
}

/** 224px 聊天栏：项目头、新建、搜索、分组会话列表、失效路径提醒、底栏。 */
export function ChatColumn({ navigation, theme, actions, onCollapse }: ChatColumnProps) {
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [editingProject, setEditingProject] = useState(false);
  const [editingProjectTitle, setEditingProjectTitle] = useState("");
  const [pendingArchive, setPendingArchive] = useState<ConversationViewModel | null>(null);

  const currentProject = navigation.projects.find((project) => project.isCurrent) ?? null;
  // presenters 在运行时将 conversations 标注为 ConversationViewModel，接口未重声明，这里显式收窄。
  const conversations = (currentProject?.conversations ?? []) as ConversationViewModel[];

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return conversations;
    return conversations.filter((conversation) =>
      conversation.title.toLowerCase().includes(keyword),
    );
  }, [conversations, query]);

  const groups = useMemo(() => {
    const now = new Date();
    const running = filtered.filter((conversation) => conversation.isTaskOrigin);
    const rest = filtered.filter((conversation) => !conversation.isTaskOrigin);
    const today = rest.filter((conversation) => isSameDay(new Date(conversation.updated_at), now));
    const earlier = rest.filter((conversation) => !isSameDay(new Date(conversation.updated_at), now));
    return [
      { id: "running", label: "运行中", items: running },
      { id: "today", label: "今天", items: today },
      { id: "earlier", label: "更早", items: earlier },
    ].filter((group) => group.items.length > 0);
  }, [filtered]);

  const pathBroken = currentProject !== null && !currentProject.path_available;

  const commitRename = (conversationId: string) => {
    const title = editingTitle.trim();
    setEditingId(null);
    if (title) void actions.renameConversation(conversationId, title);
  };

  const commitProjectRename = () => {
    if (!currentProject) return;
    const title = editingProjectTitle.trim();
    setEditingProject(false);
    if (title) void actions.renameProject(currentProject.project_id, title);
  };

  const renderRow = (conversation: ConversationViewModel) => {
    const editing = editingId === conversation.conversation_id;
    const meta = (
      <div className="conv-meta">
        <span
          className="pair-chip"
          title={`${navigation.currentPair.character.name} × ${navigation.currentPair.assistant.name}`}
        >
          <span className="pair-dot pair-dot-character" />
          <span className="pair-dot pair-dot-assistant" />
        </span>
        <span className="conv-time">{relativeTime(conversation.updated_at)}</span>
      </div>
    );
    return (
      <div
        key={conversation.conversation_id}
        className={`conversation-row${conversation.isCurrent ? " is-current" : ""}`}
      >
        {editing ? (
          <div className="conversation-row-main conversation-row-editing">
            <div className="conv-title-row">
              <input
                className="conv-rename-input"
                value={editingTitle}
                name="conversation-title"
                autoComplete="off"
                autoFocus
                onChange={(event) => setEditingTitle(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitRename(conversation.conversation_id);
                  if (event.key === "Escape") setEditingId(null);
                }}
                onBlur={() => commitRename(conversation.conversation_id)}
                aria-label="重命名聊天"
              />
            </div>
            {meta}
          </div>
        ) : (
          <>
            <button
              type="button"
              className="conversation-row-main"
              onClick={() => void actions.selectConversation(conversation.conversation_id)}
              aria-current={conversation.isCurrent ? "page" : undefined}
            >
              <div className="conv-title-row">
                {conversation.isTaskOrigin ? <span className="conv-running-dot" aria-hidden /> : null}
                <span className="conv-title">{conversation.title}</span>
              </div>
              {meta}
            </button>
            <span className="conv-more">
              <Menu
                ariaLabel="聊天操作"
                trigger={() => (
                  <button type="button" className="icon-btn" aria-label="更多操作">
                    <MoreIcon />
                  </button>
                )}
                items={[
                  { id: "rename", label: "重命名", icon: <EditIcon /> },
                  { id: "archive", label: "归档", icon: <DeleteIcon />, danger: true },
                ]}
                onSelect={(id) => {
                  if (id === "rename") {
                    setEditingTitle(conversation.title);
                    setEditingId(conversation.conversation_id);
                  } else if (id === "archive") {
                    setPendingArchive(conversation);
                  }
                }}
              />
            </span>
          </>
        )}
      </div>
    );
  };

  return (
    <div className="chat-column-inner">
      <div className="chat-header">
        {editingProject && currentProject ? (
          <input
            className="project-rename-input"
            value={editingProjectTitle}
            name="project-title"
            autoComplete="off"
            autoFocus
            onChange={(event) => setEditingProjectTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commitProjectRename();
              if (event.key === "Escape") setEditingProject(false);
            }}
            onBlur={commitProjectRename}
            aria-label="重命名项目"
          />
        ) : (
          <span className="chat-project-name" title={currentProject?.name ?? ""}>
            {currentProject?.name ?? "未选择项目"}
          </span>
        )}
        {currentProject ? (
          <span
            className={`path-badge ${pathBroken ? "path-badge-broken" : "path-badge-ok"}`}
            title={pathBroken ? "项目文件夹不可用" : "路径正常"}
          >
            {pathBroken ? <WarningIcon /> : <CheckIcon />}
          </span>
        ) : null}
        <div className="chat-actions">
          <Menu
            ariaLabel="项目操作"
            trigger={() => (
              <button type="button" className="icon-btn" aria-label="项目操作">
                <MoreIcon />
              </button>
            )}
            items={[
              { id: "rename", label: "重命名项目", icon: <EditIcon /> },
              { id: "settings", label: "项目设置", icon: <SettingIcon />, disabled: true },
            ]}
            onSelect={(id) => {
              if (id === "rename" && currentProject) {
                setEditingProjectTitle(currentProject.name);
                setEditingProject(true);
              }
            }}
          />
        </div>
      </div>

      <button
        type="button"
        className="new-chat-btn"
        disabled={!currentProject || pathBroken}
        onClick={() => void actions.createConversation(navigation.currentProjectId)}
      >
        <AddConversationIcon />
        新建聊天
      </button>

      <div className="chat-search">
        <SearchIcon />
        <input
          type="search"
          placeholder="搜索聊天…"
          value={query}
          name="chat-search"
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
          aria-label="搜索聊天"
        />
        {query ? (
          <button
            type="button"
            className="icon-btn"
            aria-label="清空搜索"
            onClick={() => setQuery("")}
          >
            <CloseIcon />
          </button>
        ) : null}
      </div>

      {pathBroken ? (
        <div className="path-warning-banner" role="alert">
          <span className="path-warning-text">
            <WarningIcon />
            项目文件夹不可用，聊天只读
          </span>
          <span className="path-warning-path" title={currentProject.root_path}>
            {currentProject.root_path}
          </span>
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => void actions.repairProjectPath(currentProject.project_id)}
            title="重新选择项目文件夹"
          >
            重新选择文件夹
          </button>
        </div>
      ) : null}

      {pendingArchive ? (
        <div className="archive-confirm" role="alertdialog" aria-label="确认归档聊天">
          <span>
            确定归档“{pendingArchive.title}”吗？
          </span>
          <div className="archive-confirm-actions">
            <button
              type="button"
              className="btn btn-danger-outline"
              onClick={() => {
                void actions.archiveConversation(pendingArchive.conversation_id);
                setPendingArchive(null);
              }}
            >
              归档
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setPendingArchive(null)}>
              取消
            </button>
          </div>
        </div>
      ) : null}

      <div className="chat-groups">
        {!currentProject ? (
          <div className="nav-empty">还没有项目</div>
        ) : conversations.length === 0 ? (
          <div className="nav-empty">还没有聊天，点击上方新建</div>
        ) : groups.length === 0 ? (
          <div className="nav-empty">没有匹配的聊天</div>
        ) : (
          groups.map((group) => (
            <section key={group.id} aria-label={group.label}>
              <div className="chat-group-label">{group.label}</div>
              {group.items.map(renderRow)}
            </section>
          ))
        )}
      </div>

      <div className="nav-footer">
        <button
          type="button"
          className="icon-btn"
          onClick={() => actions.switchTheme(theme === "dark" ? "light" : "dark")}
          title={theme === "dark" ? "切换为浅色主题" : "切换为深色主题"}
          aria-label="切换主题"
        >
          {theme === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
        </button>
        <div className="nav-footer-spacer" />
        <button
          type="button"
          className="icon-btn"
          onClick={onCollapse}
          title="收起聊天栏"
          aria-label="收起聊天栏"
        >
          <CollapseIcon />
        </button>
      </div>
    </div>
  );
}
