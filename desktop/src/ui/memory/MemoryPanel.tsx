import { useEffect, useState } from "react";

import type { HarnessActions } from "../../contracts/actions";
import type { PairMemory } from "../../contracts/protocol";
import { isCharacterIdentityAvailable } from "../../presenters/conversationIdentity";
import { findPairAssistantName } from "../../presenters/memoryScope";
import { selectWindowCharacterIdentity, useDesktopStore } from "../../stores/desktopStore";
import { MemoryContentEditor, parseMemoryContent } from "./MemoryContentEditor";

interface MemoryPanelProps {
  /** 记忆命令入口（memory.list/create/update/delete）。 */
  actions: HarnessActions;
}

/** 作用域五分量的展示顺序：账号、项目、配对配置、角色、助手身份。 */
const SCOPE_FIELDS: Array<{
  key: keyof PairMemory["scope"];
  label: string;
  /** 分量在 testid 里的名字，与上下文状态条的作用域栏一致。 */
  testId: string;
  /** 该分量的可读名取自哪个 prop；缺省表示服务端原值就是展示值。 */
  nameKey?: "characterName" | "assistantName";
}> = [
  { key: "account_id", label: "账号", testId: "account" },
  { key: "project_id", label: "项目", testId: "project" },
  { key: "pair_id", label: "配对配置", testId: "pair" },
  { key: "character_ref", label: "角色", testId: "character", nameKey: "characterName" },
  { key: "assistant_identity", label: "助手身份", testId: "assistant", nameKey: "assistantName" },
];

/** 记忆列表条目。 */
function MemoryItem({
  memory,
  editing,
  draft,
  saving,
  confirmingDelete,
  removing,
  characterName,
  assistantName,
  onStartEdit,
  onDraftChange,
  onCancelEdit,
  onSave,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  memory: PairMemory;
  editing: boolean;
  draft: string;
  saving: boolean;
  /** 正在等用户确认删除（展示确认弹窗）。 */
  confirmingDelete: boolean;
  /** memory.delete 请求在途（按钮禁用）。 */
  removing: boolean;
  /** 当前会话的角色显示名；null 表示身份不可用，作用域栏回退原始 character_ref。 */
  characterName: string | null;
  /** 本条记忆 pair_id 对应的助手显示名；null 表示目录里没有匹配项，回退原始 assistant_identity。 */
  assistantName: string | null;
  onStartEdit: () => void;
  onDraftChange: (value: string) => void;
  onCancelEdit: () => void;
  onSave: () => void;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const active = memory.status === "active";
  const parsed = parseMemoryContent(draft);
  const scopeNames = { characterName, assistantName };
  return (
    <article
      className="settings-status-card"
      data-testid={`memory-item-${memory.memory_id}`}
      style={{ gap: "8px" }}
    >
      <div className="settings-row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <code style={{ fontSize: "12px" }}>{memory.memory_id}</code>
        <span
          className={active ? "field-ok" : "field-error"}
          data-testid={`memory-status-${memory.memory_id}`}
          style={{ fontSize: "12px" }}
        >
          {active ? "生效中" : "已删除"}
        </span>
      </div>

      <div className="settings-hint" style={{ fontSize: "12px" }}>
        最近更新：{memory.updated_at || "未报告"}
      </div>

      {/* 作用域五分量由服务端下发；角色与助手身份显示可读名，服务端原值留在 title */}
      <dl className="context-strip-scope-facts" data-testid={`memory-scope-${memory.memory_id}`}>
        {SCOPE_FIELDS.map((field) => {
          const raw = memory.scope[field.key];
          const name = field.nameKey ? scopeNames[field.nameKey] : null;
          const readable = name?.trim() ? name : null;
          return (
            <div key={field.key} style={{ display: "flex", gap: "6px" }}>
              <dt>{field.label}</dt>
              <dd
                title={readable ? raw : undefined}
                data-testid={`memory-scope-${memory.memory_id}-${field.testId}`}
              >
                {readable ?? (raw || "未报告")}
              </dd>
            </div>
          );
        })}
      </dl>

      {editing ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <MemoryContentEditor
            value={draft}
            onChange={onDraftChange}
            disabled={saving}
            testId={`memory-edit-${memory.memory_id}`}
            ariaLabel="记忆内容（JSON 对象）"
          />
          <div className="settings-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || !parsed.ok}
              onClick={onSave}
            >
              {saving ? "正在保存…" : "保存修改"}
            </button>
            <button type="button" className="btn btn-outline" disabled={saving} onClick={onCancelEdit}>
              取消
            </button>
          </div>
        </div>
      ) : (
        <>
          <pre
            data-testid={`memory-content-${memory.memory_id}`}
            style={{ margin: 0, fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-all" }}
          >
            {JSON.stringify(memory.content, null, 2)}
          </pre>
          <div className="settings-row">
            <button type="button" className="btn btn-outline" disabled={!active} onClick={onStartEdit}>
              编辑
            </button>
            {active ? (
              <button
                type="button"
                className="btn btn-danger-outline"
                disabled={removing}
                onClick={onRequestDelete}
              >
                删除
              </button>
            ) : null}
          </div>
        </>
      )}

      {confirmingDelete ? (
        <div className="settings-confirm" role="alertdialog" aria-label="删除记忆确认">
          <div style={{ fontWeight: 600 }}>确认删除这条记忆？</div>
          <p className="settings-hint" style={{ fontSize: "12px" }}>
            删除会写入服务端（status=deleted），该记忆不再参与装配；记录本身仍保留可查。
          </p>
          <div className="settings-confirm-actions">
            <button type="button" className="btn btn-danger-outline" onClick={onConfirmDelete}>
              确认删除
            </button>
            <button type="button" className="btn btn-outline" onClick={onCancelDelete}>
              取消
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

/**
 * 设置中心「长期记忆」页。
 *
 * 作用域（account/project/pair/character_ref/assistant_identity 五分量）由服务端
 * 按会话解析，界面只传 conversation_id。读取失败由 listMemories 写入
 * memoryPanel.error 后显示；新增、修改、删除失败显示后端错误原文。
 *
 * 列出的记忆都属于本窗口活动会话的作用域，因此角色显示名取该会话的 character_identity，
 * 助手显示名按每条记忆的 pair_id 在搭档目录里查；两者都拿不到时回退服务端原值，
 * 与上下文状态条的作用域栏同一口径。
 */
export function MemoryPanel({ actions }: MemoryPanelProps) {
  const conversationId = useDesktopStore((state) => state.activeConversationId);
  const memoryPanel = useDesktopStore((state) => state.memoryPanel);
  const memories = useDesktopStore((state) =>
    conversationId ? state.memoriesByConversation[conversationId] ?? null : null,
  );
  const characterIdentity = useDesktopStore(selectWindowCharacterIdentity);
  const pairs = useDesktopStore((state) => state.pairs);

  const [draft, setDraft] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    // 换聊天时清掉上一份记录上的编辑与确认状态。
    setEditingId(null);
    setEditDraft("");
    setEditError(null);
    setConfirmDeleteId(null);
    if (!conversationId) return;
    void actions.listMemories({ conversationId });
  }, [conversationId, actions]);

  if (!conversationId) {
    return (
      <section className="settings-page" data-testid="memory-panel">
        <p className="settings-hint">
          长期记忆按会话解析作用域，当前窗口没有打开的聊天，无法确定要读写哪一份记忆。
        </p>
      </section>
    );
  }

  const listed = memories ?? [];
  const addParsed = parseMemoryContent(draft);
  const characterName = isCharacterIdentityAvailable(characterIdentity) ? characterIdentity.name : null;

  /** 变更后重新读取服务端列表。 */
  const reload = () => void actions.listMemories({ conversationId });

  const runAdd = async () => {
    if (!addParsed.ok) return;
    setAdding(true);
    setAddError(null);
    try {
      await actions.createMemory(addParsed.content, { conversationId });
      setDraft("");
      reload();
    } catch (error) {
      setAddError(error instanceof Error ? error.message : String(error));
    } finally {
      setAdding(false);
    }
  };

  const runSave = async (memoryId: string) => {
    const parsed = parseMemoryContent(editDraft);
    if (!parsed.ok) return;
    setSavingId(memoryId);
    setEditError(null);
    try {
      await actions.updateMemory(memoryId, parsed.content, { conversationId });
      setEditingId(null);
      reload();
    } catch (error) {
      setEditError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavingId(null);
    }
  };

  const runDelete = async (memoryId: string) => {
    setDeletingId(memoryId);
    setConfirmDeleteId(null);
    setEditError(null);
    try {
      await actions.deleteMemory(memoryId, { conversationId });
      reload();
    } catch (error) {
      setEditError(error instanceof Error ? error.message : String(error));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <section className="settings-page" data-testid="memory-panel">
      <p className="settings-hint">
        长期记忆按 account / project / pair / character_ref / assistant_identity 五分量隔离，
        作用域由服务端按当前会话解析。同一作用域内的聊天共享这些记忆，更换助手身份不会读到旧助手的记忆。
      </p>

      {memoryPanel.loading ? (
        <p className="settings-hint" role="status">
          正在读取长期记忆…
        </p>
      ) : null}

      {memoryPanel.error ? (
        <div className="settings-status-card" role="alert">
          <p className="field-error" data-testid="memory-list-error">
            读取长期记忆失败：{memoryPanel.error}
          </p>
          <div className="settings-row">
            <button type="button" className="btn btn-outline" onClick={reload}>
              重试
            </button>
          </div>
        </div>
      ) : null}

      <h3 className="settings-subhead">
        当前聊天的记忆（{listed.length}）
      </h3>

      {!memoryPanel.loaded ? (
        <p className="settings-hint">尚未读取。</p>
      ) : listed.length === 0 ? (
        <p className="settings-hint" data-testid="memory-empty">
          该聊天作用域内暂无记忆记录。
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }} data-testid="memory-list">
          {listed.map((memory) => (
            <MemoryItem
              key={memory.memory_id}
              memory={memory}
              editing={editingId === memory.memory_id}
              draft={editDraft}
              saving={savingId === memory.memory_id}
              confirmingDelete={confirmDeleteId === memory.memory_id}
              removing={deletingId === memory.memory_id}
              characterName={characterName}
              assistantName={findPairAssistantName(pairs, memory.scope.pair_id)}
              onStartEdit={() => {
                setEditingId(memory.memory_id);
                setEditDraft(JSON.stringify(memory.content, null, 2));
                setEditError(null);
              }}
              onDraftChange={setEditDraft}
              onCancelEdit={() => {
                setEditingId(null);
                setEditError(null);
              }}
              onSave={() => void runSave(memory.memory_id)}
              onRequestDelete={() => setConfirmDeleteId(memory.memory_id)}
              onCancelDelete={() => setConfirmDeleteId(null)}
              onConfirmDelete={() => void runDelete(memory.memory_id)}
            />
          ))}
        </div>
      )}

      {editError ? (
        <p className="field-error" role="alert" data-testid="memory-write-error">
          记忆操作失败：{editError}
        </p>
      ) : null}

      <h3 className="settings-subhead">新增记忆</h3>
      <p className="settings-hint">
        内容是一个 JSON 对象，字段由你与模型约定。新增的记忆写入当前聊天的作用域。
      </p>
      <MemoryContentEditor
        value={draft}
        onChange={setDraft}
        disabled={adding}
        testId="memory-create-content"
        ariaLabel="新增记忆内容（JSON 对象）"
      />
      <div className="settings-row">
        <button
          type="button"
          className="btn btn-primary"
          data-testid="memory-create-submit"
          disabled={adding || !addParsed.ok}
          onClick={() => void runAdd()}
        >
          {adding ? "正在写入…" : "新增记忆"}
        </button>
      </div>
      {addError ? (
        <p className="field-error" role="alert" data-testid="memory-create-error">
          新增记忆失败：{addError}
        </p>
      ) : null}
    </section>
  );
}
