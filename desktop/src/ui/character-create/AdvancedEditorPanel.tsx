import { useState } from "react";
import { ChevronDownIcon, ChevronRightIcon, PlusIcon, InfoIcon, ArrowLeftIcon } from "./icons";
import { isPlainObject } from "./mufy/mufyValues";
import { MufyAdvancedEditor } from "./mufy/MufyAdvancedEditor";
import { WorldBookEditor } from "./world-book/WorldBookEditor";
import type { CharacterFormData } from "./types";

interface AdvancedEditorPanelProps {
  formData: CharacterFormData;
  readOnly: boolean;
  /** 当前整卡 v3 JSON 草稿（含未保存编辑）；原始数据视图与世界书 / mufy 编辑器都以它为数据源。 */
  cardJson: Record<string, unknown> | null;
  onFieldChange: <K extends keyof CharacterFormData>(field: K, value: CharacterFormData[K]) => void;
  /** 世界书编辑后回传完整 character_book，由创作页合并回整卡 JSON 再走 card.update。 */
  onCharacterBookChange: (book: Record<string, unknown>) => void;
  /** mufy 高级设定编辑后回传完整 extensions.hsr，由创作页合并回整卡 JSON 再走 card.update。 */
  onHsrChange: (hsr: Record<string, unknown>) => void;
  onReturnToQuick: () => void;
}

interface TreeSection {
  id: string;
  name: string;
  group: string;
  description: string;
  targetVersion: string;
  editable: boolean;
}

const ADVANCED_SECTIONS: TreeSection[] = [
  { id: "sys", name: "系统提示", group: "基础组", description: "最高优先级注入，约束整个会话的行为边界。", targetVersion: "V0.3.5", editable: true },
  { id: "post", name: "历史后指令", group: "基础组", description: "插在历史消息与用户输入之间，引导即时语气。", targetVersion: "V0.3.5", editable: true },
  { id: "altgreet", name: "备选问候", group: "基础组", description: "多条开场白轮换，支持场景随机选用。", targetVersion: "V0.3.5", editable: true },
  { id: "groupgreet", name: "群组问候", group: "基础组", description: "多角色会话首次发言时使用。", targetVersion: "V0.3.5", editable: true },
  { id: "mesexample", name: "示例对话", group: "基础组", description: "含 <START> 分隔的示例对话，帮助模型把握语气与格式。", targetVersion: "V0.3.5", editable: true },
  { id: "worldbook", name: "世界书", group: "世界书", description: "条目增删改与书级设置：决定这条设定什么时候进入角色的脑子。", targetVersion: "V0.3.7", editable: true },
  { id: "mufy", name: "mufy 高级设定", group: "mufy 高级", description: "世界架构、身份外貌、语言方式、行为状态、心理核心、用户关系、关系阶段、时间线、叙事规则与声明式面板，按 mufy 模板分块编辑。", targetVersion: "V0.3.7", editable: true },
  { id: "voice", name: "声音感官", group: "扩展组", description: "语气提示词与音色绑定信息。", targetVersion: "V0.3.5", editable: false },
  { id: "raw", name: "原始数据", group: "扩展组", description: "完整 v3 JSON 契约结构核对视图。", targetVersion: "V0.3.5", editable: false },
];

export function AdvancedEditorPanel({
  formData,
  readOnly,
  cardJson,
  onFieldChange,
  onCharacterBookChange,
  onHsrChange,
  onReturnToQuick,
}: AdvancedEditorPanelProps) {
  const [selectedSectionId, setSelectedSectionId] = useState("sys");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [editingGreetingIndex, setEditingGreetingIndex] = useState<number | null>(null);
  const [editingGreetingText, setEditingGreetingText] = useState("");

  const selectedSection = ADVANCED_SECTIONS.find((s) => s.id === selectedSectionId) ?? ADVANCED_SECTIONS[0];
  const groups = Array.from(new Set(ADVANCED_SECTIONS.map((s) => s.group)));

  // 世界书与 mufy 编辑器的数据都从整卡 JSON 草稿中取出；结构异常时交给子编辑器如实呈现。
  const cardData = isPlainObject(cardJson?.data) ? (cardJson?.data as Record<string, unknown>) : {};
  const characterBook = (cardData.character_book ?? null) as Record<string, unknown> | null;
  const extensions = isPlainObject(cardData.extensions) ? (cardData.extensions as Record<string, unknown>) : {};
  const hsr = (extensions.hsr ?? null) as Record<string, unknown> | null;

  const handleBookChange = (next: Record<string, unknown>) => {
    if (readOnly) return;
    onCharacterBookChange(next);
  };

  const handleHsrChange = (next: Record<string, unknown>) => {
    if (readOnly) return;
    onHsrChange(next);
  };

  const toggleGroup = (group: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const handleGreetingAdd = () => {
    if (readOnly) return;
    onFieldChange("alternate_greetings", [...formData.alternate_greetings, ""]);
    const newIndex = formData.alternate_greetings.length;
    setEditingGreetingIndex(newIndex);
    setEditingGreetingText("");
  };

  const handleGreetingUpdate = (index: number, text: string) => {
    if (readOnly) return;
    const next = [...formData.alternate_greetings];
    next[index] = text;
    onFieldChange("alternate_greetings", next);
  };

  const handleGreetingRemove = (index: number) => {
    if (readOnly) return;
    const next = formData.alternate_greetings.filter((_, idx) => idx !== index);
    onFieldChange("alternate_greetings", next);
    if (editingGreetingIndex === index) {
      setEditingGreetingIndex(null);
    }
  };

  const handleGreetingMove = (index: number, direction: -1 | 1) => {
    if (readOnly) return;
    const target = index + direction;
    if (target < 0 || target >= formData.alternate_greetings.length) return;
    const next = [...formData.alternate_greetings];
    [next[index], next[target]] = [next[target], next[index]];
    onFieldChange("alternate_greetings", next);
    if (editingGreetingIndex === index) setEditingGreetingIndex(target);
  };

  const startEditGreeting = (index: number) => {
    setEditingGreetingIndex(index);
    setEditingGreetingText(formData.alternate_greetings[index] ?? "");
  };

  const finishEditGreeting = () => {
    if (editingGreetingIndex === null) return;
    handleGreetingUpdate(editingGreetingIndex, editingGreetingText);
    setEditingGreetingIndex(null);
  };

  const renderEditor = () => {
    switch (selectedSection.id) {
      case "sys":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">系统提示</h2>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              作为最高优先级注入，约束角色在整个会话中的行为边界。
            </p>
            <div className="char-create-field">
              <label className="char-create-label" htmlFor="f-system-prompt">系统提示内容</label>
              <textarea
                id="f-system-prompt"
                className="char-create-textarea"
                style={{ minHeight: "220px" }}
                value={formData.system_prompt}
                onChange={(e) => onFieldChange("system_prompt", e.target.value)}
                disabled={readOnly}
                data-testid="f-system-prompt"
              />
              <span className="char-create-char-count">
                {formData.system_prompt.length} 字
              </span>
            </div>
          </div>
        );
      case "post":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">历史后指令</h2>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              插入在对话历史之后、最新用户输入之前，用于长期校准。
            </p>
            <div className="char-create-field">
              <label className="char-create-label" htmlFor="f-post-history">后指令内容</label>
              <textarea
                id="f-post-history"
                className="char-create-textarea"
                style={{ minHeight: "160px" }}
                value={formData.post_history_instructions}
                onChange={(e) => onFieldChange("post_history_instructions", e.target.value)}
                disabled={readOnly}
                data-testid="f-post-history"
              />
              <span className="char-create-char-count">
                {formData.post_history_instructions.length} 字
              </span>
            </div>
          </div>
        );
      case "altgreet":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">备选问候</h2>
              <span className="char-create-meta">{formData.alternate_greetings.length} 条</span>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              新会话开始时随机选用一条，替代默认问候。
            </p>
            <div className="char-create-greeting-list" data-testid="alternate-greetings-list">
              {formData.alternate_greetings.map((greeting, idx) => (
                <div
                  key={`greet-${idx}`}
                  className={`char-create-greeting-item ${editingGreetingIndex === idx ? "editing" : ""}`}
                  data-testid={`greeting-item-${idx}`}
                >
                  {editingGreetingIndex === idx ? (
                    <div className="char-create-field" style={{ flex: 1, minWidth: 0 }}>
                      <textarea
                        className="char-create-textarea"
                        value={editingGreetingText}
                        onChange={(e) => setEditingGreetingText(e.target.value)}
                        disabled={readOnly}
                        autoFocus
                        data-testid={`greeting-input-${idx}`}
                      />
                    </div>
                  ) : (
                    <div className="char-create-greeting-text" data-testid={`greeting-text-${idx}`}>
                      {greeting || <span className="char-create-preview-placeholder">空问候语</span>}
                    </div>
                  )}
                  <div className="char-create-greeting-actions">
                    {editingGreetingIndex === idx ? (
                      <button
                        type="button"
                        className="char-btn char-btn-secondary"
                        style={{ minHeight: "28px", padding: "2px 10px", fontSize: "12px" }}
                        onClick={finishEditGreeting}
                        disabled={readOnly}
                        data-testid={`greeting-done-${idx}`}
                      >
                        完成
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="char-btn char-btn-ghost"
                        style={{ minHeight: "28px", padding: "2px 10px", fontSize: "12px" }}
                        onClick={() => startEditGreeting(idx)}
                        disabled={readOnly}
                        data-testid={`greeting-edit-${idx}`}
                      >
                        编辑
                      </button>
                    )}
                    <button
                      type="button"
                      className="char-btn char-btn-ghost"
                      style={{ minHeight: "28px", padding: "2px 10px", fontSize: "12px" }}
                      onClick={() => handleGreetingMove(idx, -1)}
                      disabled={readOnly || idx === 0}
                      aria-label="上移"
                      data-testid={`greeting-up-${idx}`}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="char-btn char-btn-ghost"
                      style={{ minHeight: "28px", padding: "2px 10px", fontSize: "12px" }}
                      onClick={() => handleGreetingMove(idx, 1)}
                      disabled={readOnly || idx === formData.alternate_greetings.length - 1}
                      aria-label="下移"
                      data-testid={`greeting-down-${idx}`}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="char-btn char-btn-danger"
                      style={{ minHeight: "28px", padding: "2px 10px", fontSize: "12px" }}
                      onClick={() => handleGreetingRemove(idx)}
                      disabled={readOnly}
                      aria-label="删除"
                      data-testid={`greeting-del-${idx}`}
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="char-btn char-btn-secondary"
              style={{ alignSelf: "flex-start" }}
              onClick={handleGreetingAdd}
              disabled={readOnly}
              data-testid="btn-add-greeting"
            >
              <PlusIcon width="14" height="14" />
              新增问候
            </button>
          </div>
        );
      case "groupgreet":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">群组问候</h2>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              多角色会话中首次发言时使用；多行将被拆分为多条问候。
            </p>
            <div className="char-create-field">
              <label className="char-create-label" htmlFor="f-group-greet">群组问候内容</label>
              <textarea
                id="f-group-greet"
                className="char-create-textarea"
                style={{ minHeight: "160px" }}
                value={formData.group_only_greetings}
                onChange={(e) => onFieldChange("group_only_greetings", e.target.value)}
                disabled={readOnly}
                data-testid="f-group-greet"
              />
              <span className="char-create-char-count">
                {formData.group_only_greetings.length} 字
              </span>
            </div>
          </div>
        );
      case "mesexample":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">示例对话</h2>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              用 <code>&lt;START&gt;</code> 分隔多条示例，帮助模型把握角色语气、格式与互动节奏。
            </p>
            <div className="char-create-field">
              <label className="char-create-label" htmlFor="f-mes-example">示例对话内容</label>
              <textarea
                id="f-mes-example"
                className="char-create-textarea"
                style={{ minHeight: "220px" }}
                value={formData.mes_example}
                onChange={(e) => onFieldChange("mes_example", e.target.value)}
                disabled={readOnly}
                data-testid="f-mes-example"
              />
              <span className="char-create-char-count">
                {formData.mes_example.length} 字
              </span>
            </div>
          </div>
        );
      case "worldbook":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">世界书</h2>
              <span className="char-create-meta">character_book</span>
            </div>
            <WorldBookEditor book={characterBook} onChange={handleBookChange} readOnly={readOnly} />
          </div>
        );
      case "mufy":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">mufy 高级设定</h2>
              <span className="char-create-meta">extensions.hsr</span>
            </div>
            <MufyAdvancedEditor hsr={hsr} onChange={handleHsrChange} readOnly={readOnly} />
          </div>
        );
      case "voice":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">声音感官</h2>
            </div>
            <div className="char-create-notice-box" role="note">
              <InfoIcon width="16" height="16" />
              <div>
                <div style={{ fontWeight: 600, marginBottom: "4px" }}>编辑入口在「角色语音」页</div>
                <div>
                  角色音色的绑定、创建与试听在「角色语音」页完成；高级设定中的 voice_profile 会在
                  mufy 高级设定分区里以受管理字段的形式只读展示。
                </div>
              </div>
            </div>
          </div>
        );
      case "raw":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">原始数据</h2>
              <span className="char-create-meta">只读</span>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              角色卡完整 JSON 的实时快照，包含世界书与 mufy 高级设定的最新编辑（含尚未保存的部分），
              供熟悉酒馆卡结构的用户做字段级核对。此视图只读，引导式编辑请使用左侧各分区。
            </p>
            <pre className="char-create-json-view" data-testid="raw-json-view">
              {JSON.stringify(cardJson ?? {}, null, 2)}
            </pre>
          </div>
        );
      default:
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">{selectedSection.name}</h2>
            </div>
            <div className="char-create-notice-box" role="note">
              <InfoIcon width="16" height="16" />
              <div>该分区暂未提供编辑入口。</div>
            </div>
          </div>
        );
    }
  };

  return (
    <div className="char-create-advanced-layout" data-testid="advanced-panel">
      <nav className="char-create-card" style={{ padding: "12px" }} aria-label="高级编辑分区">
        {groups.map((group) => {
          const collapsed = collapsedGroups.has(group);
          const sections = ADVANCED_SECTIONS.filter((s) => s.group === group);
          return (
            <div key={group} className="char-create-tree-group">
              <button
                type="button"
                className="char-create-tree-group-title"
                onClick={() => toggleGroup(group)}
                aria-expanded={!collapsed}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  width: "100%",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  padding: "4px 8px",
                }}
              >
                {collapsed ? <ChevronRightIcon width="12" height="12" /> : <ChevronDownIcon width="12" height="12" />}
                {group}
              </button>
              {!collapsed ? (
                <div className="char-create-tree-items">
                  {sections.map((section) => (
                    <button
                      key={section.id}
                      type="button"
                      className={`char-create-tree-item ${selectedSection.id === section.id ? "active" : ""}`}
                      onClick={() => setSelectedSectionId(section.id)}
                      data-testid={`tree-item-${section.id}`}
                    >
                      <span>{section.name}</span>
                      <span
                        className="char-create-meta"
                        style={{
                          fontSize: "10px",
                          color: section.editable ? "var(--gold, #B08D57)" : undefined,
                        }}
                      >
                        {section.targetVersion}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </nav>

      <section className="char-create-card char-create-advanced-pane" aria-label="分区编辑区">
        {renderEditor()}
        <div style={{ display: "flex", justifyContent: "flex-start", marginTop: "8px" }}>
          <button
            type="button"
            className="char-btn char-btn-secondary"
            onClick={onReturnToQuick}
            data-testid="btn-return-quick"
          >
            <ArrowLeftIcon />
            返回快速创建
          </button>
        </div>
      </section>
    </div>
  );
}
