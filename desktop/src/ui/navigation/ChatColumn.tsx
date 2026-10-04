import { useCallback, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { HarnessActions } from "../../contracts/actions";
import type { PairOption } from "../../contracts/protocol";
import type {
  ConversationViewModel,
  NavigationViewModel,
  ProjectViewModel,
} from "../../contracts/view-models";
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
import { Menu, type MenuItem } from "../primitives/Menu";
import { isSameDay, relativeTime } from "../format";
import { getPairAvatars, useCardAvatar } from "../../assets/pairs/avatars";

/** 新建菜单里两段之间的分隔项 id；Menu 没有分隔类型，用不可点击项承载。 */
const PAIR_MENU_SEPARATOR_ID = "pair-menu-separator";

interface ChatColumnProps {
  navigation: NavigationViewModel;
  theme: "dark" | "light";
  actions: HarnessActions;
  onCollapse: () => void;
}

interface InlineRenameInputProps {
  className: string;
  name: string;
  value: string;
  ariaLabel: string;
  onChange: (value: string) => void;
  onCommit: () => void;
  onCancel: () => void;
}

function InlineRenameInput({
  className,
  name,
  value,
  ariaLabel,
  onChange,
  onCommit,
  onCancel,
}: InlineRenameInputProps) {
  return (
    <input
      className={className}
      value={value}
      name={name}
      autoComplete="off"
      autoFocus
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter") onCommit();
        if (event.key === "Escape") onCancel();
      }}
      onBlur={onCommit}
      aria-label={ariaLabel}
    />
  );
}

interface ArchiveConfirmProps {
  label: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}
function ArchiveConfirm({ label, message, confirmLabel, onConfirm, onCancel }: ArchiveConfirmProps) {
  return (
    <div className="archive-confirm" role="alertdialog" aria-label={label}>
      <span>{message}</span>
      <div className="archive-confirm-actions">
        <button type="button" className="btn btn-danger-outline" onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          取消
        </button>
      </div>
    </div>
  );
}

/** 新建菜单项图标：内置搭档用静态头像，角色卡用卡头像；没有头像时用搭档主题双点。 */
function PairMenuIcon({ pair, actions }: { pair: PairOption; actions: HarnessActions }) {
  const avatars = pair.source === "builtin" ? getPairAvatars(pair.pair_id) : null;
  const cardAvatar = useCardAvatar(
    actions.fetchCardAvatar,
    pair.source === "card" ? pair.character_card_id : null,
    pair.character.avatar_version,
  );
  return (
    <span className="pair-menu-icon">
      {cardAvatar ? (
        <img src={cardAvatar} alt="" className="pair-menu-avatar" />
      ) : avatars ? (
        <span className="pair-menu-avatars">
          <img src={avatars.character} alt="" className="pair-menu-avatar" />
          <img src={avatars.assistant} alt="" className="pair-menu-avatar pair-menu-avatar-offset" />
        </span>
      ) : (
        <span className="pair-chip">
          <span className="pair-dot" style={{ background: pair.theme.character_primary }} />
          <span className="pair-dot" style={{ background: pair.theme.assistant_primary }} />
        </span>
      )}
    </span>
  );
}

/**
 * 会话行搭档芯片：conversation.character_identity 存在且来自角色卡时，角色侧显示卡名与卡头像；
 * 卡头像缺失或角色卡已删除（missing）时退回几何占位。没有角色身份时维持内置搭档渲染。
 */
function ConversationPairChip({
  conversation,
  pairs,
  actions,
}: {
  conversation: ConversationViewModel;
  pairs: PairOption[];
  actions: HarnessActions;
}) {
  const identity = conversation.character_identity ?? null;
  const item =
    conversation.binding_id !== undefined && conversation.binding_id !== null
      ? pairs.find((candidate) => candidate.binding_id === conversation.binding_id) ?? null
      : null;
  const baseItem =
    pairs.find(
      (candidate) => candidate.source === "builtin" && candidate.pair_id === conversation.pair_id,
    ) ?? null;
  const catalogItem = item ?? baseItem;
  const missing = identity?.missing === true;
  // 卡已删除（missing）时不请求头像，直接按几何占位降级。
  const cardId =
    identity?.source === "card" && !missing ? conversation.character_card_id ?? null : null;
  const cardAvatar = useCardAvatar(
    actions.fetchCardAvatar,
    cardId,
    identity?.avatar_version ?? null,
  );
  const avatars = getPairAvatars(catalogItem?.pair_id ?? conversation.pair_id);
  // 卡会话的角色侧只用卡头像；没有卡头像或已缺失时退回几何占位，不借用内置角色头像。
  const characterAvatar = cardAvatar ?? (cardId === null ? avatars?.character ?? null : null);
  const assistantAvatar = missing ? null : avatars?.assistant ?? null;
  const characterName =
    identity?.name || catalogItem?.character.name || conversation.pair_id || "未知搭档";
  const assistantName = catalogItem?.assistant.name ?? null;
  const title = assistantName ? `${characterName} × ${assistantName}` : characterName;

  const avatarsNode =
    characterAvatar && assistantAvatar ? (
      <span className="pair-chip-avatars">
        <img src={characterAvatar} alt="" className="pair-chip-avatar" />
        <img
          src={assistantAvatar}
          alt=""
          className="pair-chip-avatar pair-chip-avatar-offset"
        />
      </span>
    ) : catalogItem && !missing ? (
      <>
        <span className="pair-dot" style={{ background: catalogItem.theme.character_primary }} />
        <span className="pair-dot" style={{ background: catalogItem.theme.assistant_primary }} />
      </>
    ) : (
      <>
        <span className="pair-dot pair-dot-character" />
        <span className="pair-dot pair-dot-assistant" />
      </>
    );

  return (
    <span className="pair-chip" title={title}>
      {avatarsNode}
      <span className="pair-chip-name">{title}</span>
    </span>
  );
}

/** 224px 聊天栏：项目头、新建、搜索、分组会话列表、失效路径提醒、底栏。 */
export function ChatColumn({ navigation, theme, actions, onCollapse }: ChatColumnProps) {
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [editingProject, setEditingProject] = useState(false);
  const [editingProjectTitle, setEditingProjectTitle] = useState("");
  const [pendingArchive, setPendingArchive] = useState<ConversationViewModel | null>(null);
  const [pendingArchiveProject, setPendingArchiveProject] = useState<ProjectViewModel | null>(null);

  const currentProject = navigation.projects.find((project) => project.isCurrent) ?? null;
  const conversations = currentProject?.conversations ?? [];

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return conversations;
    return conversations.filter((conversation) =>
      conversation.title.toLowerCase().includes(keyword),
    );
  }, [conversations, query]);

  const groups = useMemo(() => {
    const now = new Date();
    const running = filtered.filter((conversation) => conversation.isRunning);
    const rest = filtered.filter((conversation) => !conversation.isRunning);
    const today = rest.filter((conversation) => isSameDay(new Date(conversation.updated_at), now));
    const earlier = rest.filter((conversation) => !isSameDay(new Date(conversation.updated_at), now));
    return [
      { id: "running", label: "运行中", items: running },
      { id: "today", label: "今天", items: today },
      { id: "earlier", label: "更早", items: earlier },
    ].filter((group) => group.items.length > 0);
  }, [filtered]);

  type FlatChatRow =
    | { kind: "header"; id: string; label: string }
    | { kind: "item"; conversation: ConversationViewModel };

  const flatRows = useMemo<FlatChatRow[]>(() => {
    const result: FlatChatRow[] = [];
    for (const group of groups) {
      result.push({ kind: "header", id: group.id, label: group.label });
      for (const item of group.items) {
        result.push({ kind: "item", conversation: item });
      }
    }
    return result;
  }, [groups]);

  const shouldVirtualize = flatRows.length > 40;
  const chatScrollRef = useRef<HTMLDivElement>(null);
  // getItemKey 只随行列表变化，虚拟器据此复用已测量的行高。
  const getRowKey = useCallback(
    (index: number) => {
      const row = flatRows[index];
      return row.kind === "header" ? `h-${row.id}` : row.conversation.conversation_id;
    },
    [flatRows],
  );
  const virtualizer = useVirtualizer({
    count: flatRows.length,
    getScrollElement: () => chatScrollRef.current,
    estimateSize: (index) => (flatRows[index].kind === "header" ? 28 : 64),
    overscan: 6,
    getItemKey: getRowKey,
  });

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
        <ConversationPairChip
          conversation={conversation}
          pairs={navigation.pairs}
          actions={actions}
        />
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
              <InlineRenameInput
                className="conv-rename-input"
                name="conversation-title"
                value={editingTitle}
                ariaLabel="重命名聊天"
                onChange={setEditingTitle}
                onCommit={() => commitRename(conversation.conversation_id)}
                onCancel={() => setEditingId(null)}
              />
            </div>
            {meta}
          </div>
        ) : (
          <>
            <button
              type="button"
              className="conversation-row-main"
              onClick={() =>
                // 点击聊天打开或聚焦本窗口标签，不改其他窗口的导航。
                void actions.openConversationTab(conversation.conversation_id)
              }
              aria-current={conversation.isCurrent ? "page" : undefined}
            >
              <div className="conv-title-row">
                {conversation.isRunning ? <span className="conv-running-dot" aria-hidden /> : null}
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

  const pairsList = navigation.pairs;
  const currentSelectedConv = conversations.find(
    (c) => c.conversation_id === navigation.currentConversationId,
  );
  // 菜单项 id 是绑定 id；旧会话没有 binding_id 时按内置搭档推导，仅用于选中标记。
  const defaultBindingId = currentSelectedConv
    ? (currentSelectedConv.binding_id ??
      (currentSelectedConv.character_card_id ? null : `builtin:${currentSelectedConv.pair_id}`))
    : null;

  // 内置搭档段在前，角色卡段在后，两段之间放一个不可点击的分隔项。
  const builtinOptions = pairsList.filter((pair) => pair.source === "builtin");
  const cardOptions = pairsList.filter((pair) => pair.source === "card");
  const pairMenuItem = (pair: PairOption): MenuItem => ({
    id: pair.binding_id,
    label: `${pair.character.name} × ${pair.assistant.name}`,
    icon: <PairMenuIcon pair={pair} actions={actions} />,
  });
  const pairMenuItems: MenuItem[] = [
    ...builtinOptions.map(pairMenuItem),
    ...(builtinOptions.length > 0 && cardOptions.length > 0
      ? [{ id: PAIR_MENU_SEPARATOR_ID, label: "", disabled: true }]
      : []),
    ...cardOptions.map(pairMenuItem),
  ];

  return (
    <div className="chat-column-inner">
      <div className="chat-header">
        {editingProject && currentProject ? (
          <InlineRenameInput
            className="project-rename-input"
            name="project-title"
            value={editingProjectTitle}
            ariaLabel="重命名项目"
            onChange={setEditingProjectTitle}
            onCommit={commitProjectRename}
            onCancel={() => setEditingProject(false)}
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
              { id: "archive", label: "归档项目", icon: <DeleteIcon />, danger: true, disabled: !currentProject },
            ]}
            onSelect={(id) => {
              if (id === "rename" && currentProject) {
                setEditingProjectTitle(currentProject.name);
                setEditingProject(true);
              } else if (id === "archive" && currentProject) {
                setPendingArchiveProject(currentProject);
              }
            }}
          />
        </div>
      </div>

      <div className="new-chat-wrapper">
        <Menu
          ariaLabel="选择搭档新建聊天"
          align="left"
          selectedId={defaultBindingId ?? undefined}
          trigger={({ open }) => (
            <button
              type="button"
              className={`new-chat-btn${open ? " is-active" : ""}`}
              disabled={!currentProject || pathBroken}
            >
              <AddConversationIcon />
              新建聊天
            </button>
          )}
          items={pairMenuItems}
          onSelect={(bindingId) => {
            // 分隔项不可点击；其余项都是配对目录里的绑定 id。
            if (bindingId === PAIR_MENU_SEPARATOR_ID) return;
            void actions.createConversation(navigation.currentProjectId, undefined, bindingId);
          }}
        />
      </div>

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
        <ArchiveConfirm
          label="确认归档聊天"
          message={`确定归档“${pendingArchive.title}”吗？`}
          confirmLabel="归档"
          onConfirm={() => {
            void actions.archiveConversation(pendingArchive.conversation_id);
            setPendingArchive(null);
          }}
          onCancel={() => setPendingArchive(null)}
        />
      ) : null}

      {pendingArchiveProject ? (
        <ArchiveConfirm
          label="确认归档项目"
          message={`确定归档项目“${pendingArchiveProject.name}”吗？其中的聊天会一起归档。`}
          confirmLabel="归档项目"
          onConfirm={() => {
            void actions.archiveProject(pendingArchiveProject.project_id);
            setPendingArchiveProject(null);
          }}
          onCancel={() => setPendingArchiveProject(null)}
        />
      ) : null}

      <div className="chat-groups" ref={chatScrollRef}>
        {!currentProject ? (
          <div className="nav-empty">
            <span>还没有项目</span>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => void actions.createProject()}
            >
              新建项目
            </button>
          </div>
        ) : conversations.length === 0 ? (
          <div className="nav-empty">还没有聊天，点击上方新建</div>
        ) : groups.length === 0 ? (
          <div className="nav-empty">没有匹配的聊天</div>
        ) : shouldVirtualize ? (
          <div
            className="chat-groups-virtual"
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              position: "relative",
              width: "100%",
            }}
          >
            {virtualizer.getVirtualItems().map((vItem) => {
              const row = flatRows[vItem.index];
              return (
                <div
                  key={vItem.key}
                  ref={virtualizer.measureElement}
                  data-index={vItem.index}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${vItem.start}px)`,
                  }}
                >
                  {row.kind === "header" ? (
                    <div className="chat-group-label">{row.label}</div>
                  ) : (
                    renderRow(row.conversation)
                  )}
                </div>
              );
            })}
          </div>
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
