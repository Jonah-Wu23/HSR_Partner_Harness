import { useState } from "react";
import { ChevronDownIcon, ChevronRightIcon, GripVerticalIcon, PlusIcon, InfoIcon, ArrowLeftIcon } from "./icons";
import type { CharacterFormData } from "./types";

interface AdvancedEditorPanelProps {
  formData: CharacterFormData;
  readOnly: boolean;
  cardJson: Record<string, unknown> | null;
  onFieldChange: <K extends keyof CharacterFormData>(field: K, value: CharacterFormData[K]) => void;
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
  { id: "worldbook", name: "世界书", group: "世界组", description: "常驻与关键词触发条目，构建角色专属世界知识。", targetVersion: "V0.3.7", editable: false },
  { id: "worldarch", name: "世界架构", group: "世界组", description: "时代背景、地理与社会价值观设定（HSR 扩展）。", targetVersion: "V0.3.7", editable: false },
  { id: "identity", name: "身份外貌", group: "人设组", description: "外貌特征、着装与感官印象。", targetVersion: "V0.3.7", editable: false },
  { id: "speech", name: "语言方式", group: "人设组", description: "说话口吻、称谓习惯与口癖。", targetVersion: "V0.3.7", editable: false },
  { id: "behavior", name: "行为状态", group: "人设组", description: "习惯动作、日常作息与状态机分支。", targetVersion: "V0.3.7", editable: false },
  { id: "psyche", name: "心理核心", group: "人设组", description: "核心动机、恐惧与内在矛盾。", targetVersion: "V0.3.7", editable: false },
  { id: "relation", name: "用户关系", group: "人设组", description: "与搭档用户的默认关系设定。", targetVersion: "V0.3.7", editable: false },
  { id: "stage", name: "关系阶段", group: "人设组", description: "好感度/信任度阶段定义与推进规则。", targetVersion: "V0.3.7", editable: false },
  { id: "timeline", name: "时间线", group: "人设组", description: "关键历史事件与相对时间锚点。", targetVersion: "V0.3.7", editable: false },
  { id: "narrule", name: "叙事规则", group: "人设组", description: "叙事视角、节奏与明确禁区。", targetVersion: "V0.3.7", editable: false },
  { id: "voice", name: "声音感官", group: "扩展组", description: "语气提示词与音色绑定信息。", targetVersion: "V0.3.5", editable: false },
  { id: "panel", name: "声明式面板", group: "扩展组", description: "自定义会话内信息展示卡片（保留但暂未运行）。", targetVersion: "V0.3.7", editable: false },
  { id: "raw", name: "原始数据", group: "扩展组", description: "完整 v3 JSON 契约结构核对视图。", targetVersion: "V0.3.5", editable: false },
];

export function AdvancedEditorPanel({
  formData,
  readOnly,
  cardJson,
  onFieldChange,
  onReturnToQuick,
}: AdvancedEditorPanelProps) {
  const [selectedSectionId, setSelectedSectionId] = useState("sys");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [editingGreetingIndex, setEditingGreetingIndex] = useState<number | null>(null);
  const [editingGreetingText, setEditingGreetingText] = useState("");

  const selectedSection = ADVANCED_SECTIONS.find((s) => s.id === selectedSectionId) ?? ADVANCED_SECTIONS[0];
  const groups = Array.from(new Set(ADVANCED_SECTIONS.map((s) => s.group)));

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
      case "raw":
        return (
          <div className="char-create-advanced-pane">
            <div className="char-create-section-head">
              <h2 className="char-create-section-title">原始数据</h2>
              <span className="char-create-meta">只读</span>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              角色卡的完整 JSON 快照，仅供核对，不支持在此编辑。
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
              <span className="char-create-meta">规划交付：{selectedSection.targetVersion}</span>
            </div>
            <p className="char-create-meta" style={{ fontSize: "13px", color: "var(--text-secondary, #9AA3B2)" }}>
              {selectedSection.description}
            </p>
            <div className="char-create-notice-box" role="note">
              <InfoIcon width="16" height="16" />
              <div>
                <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                  完整字段编辑随 {selectedSection.targetVersion} 交付
                </div>
                <div>
                  {selectedSection.id === "voice"
                    ? "角色音色绑定与试听请在「角色语音」页完成；此处仅保留语气提示词占位。"
                    : "该分区属于高级角色卡能力，当前阶段不提供伪造的保存表单，确保数据严谨性。您在快速创建与其他已开放分区中填写的内容已完整保留。"}
                </div>
              </div>
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
