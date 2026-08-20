import { useState } from "react";
import { InfoIcon, ArrowLeftIcon } from "./icons";
import type { CharacterFormData } from "./types";

interface AdvancedPlaceholderPanelProps {
  formData: CharacterFormData;
  onReturnToQuick: () => void;
}

interface TreeSection {
  id: string;
  name: string;
  group: string;
  description: string;
  targetVersion: string;
}

const ADVANCED_SECTIONS: TreeSection[] = [
  { id: "sys", name: "系统提示", group: "基础组", description: "最高优先级注入，约束整个会话的行为边界。", targetVersion: "V0.3.5" },
  { id: "post", name: "历史后指令", group: "基础组", description: "插在历史消息与用户输入之间，引导即时语气。", targetVersion: "V0.3.5" },
  { id: "altgreet", name: "备选问候", group: "基础组", description: "多条开场白轮换，支持场景随机选用。", targetVersion: "V0.3.5" },
  { id: "groupgreet", name: "群组问候", group: "基础组", description: "多角色会话首次发言时使用。", targetVersion: "V0.3.5" },
  { id: "worldbook", name: "世界书", group: "世界组", description: "常驻与关键词触发条目，构建角色专属世界知识。", targetVersion: "V0.3.7" },
  { id: "worldarch", name: "世界架构", group: "世界组", description: "时代背景、地理与社会价值观设定（HSR 扩展）。", targetVersion: "V0.3.7" },
  { id: "identity", name: "身份外貌", group: "人设组", description: "外貌特征、着装与感官印象。", targetVersion: "V0.3.7" },
  { id: "speech", name: "语言方式", group: "人设组", description: "说话口吻、称谓习惯与口癖。", targetVersion: "V0.3.7" },
  { id: "behavior", name: "行为状态", group: "人设组", description: "习惯动作、日常作息与状态机分支。", targetVersion: "V0.3.7" },
  { id: "psyche", name: "心理核心", group: "人设组", description: "核心动机、恐惧与内在矛盾。", targetVersion: "V0.3.7" },
  { id: "relation", name: "用户关系", group: "人设组", description: "与搭档用户的默认关系设定。", targetVersion: "V0.3.7" },
  { id: "stage", name: "关系阶段", group: "人设组", description: "好感度/信任度阶段定义与推进规则。", targetVersion: "V0.3.7" },
  { id: "timeline", name: "时间线", group: "人设组", description: "关键历史事件与相对时间锚点。", targetVersion: "V0.3.7" },
  { id: "narrule", name: "叙事规则", group: "人设组", description: "叙事视角、节奏与明确禁区。", targetVersion: "V0.3.7" },
  { id: "voice", name: "声音感官", group: "扩展组", description: "语气提示词与音色绑定信息。", targetVersion: "V0.3.5" },
  { id: "panel", name: "声明式面板", group: "扩展组", description: "自定义会话内信息展示卡片（保留但暂未运行）。", targetVersion: "V0.3.7" },
  { id: "raw", name: "原始数据", group: "扩展组", description: "完整 v3 JSON 契约结构核对视图。", targetVersion: "V0.3.5" },
];

export function AdvancedPlaceholderPanel({
  formData,
  onReturnToQuick,
}: AdvancedPlaceholderPanelProps) {
  const [selectedSectionId, setSelectedSectionId] = useState("sys");

  const selectedSection =
    ADVANCED_SECTIONS.find((s) => s.id === selectedSectionId) ?? ADVANCED_SECTIONS[0];

  const groups = Array.from(new Set(ADVANCED_SECTIONS.map((s) => s.group)));

  return (
    <div className="char-create-advanced-layout" data-testid="advanced-panel">
      {/* 分区导航树 */}
      <nav className="char-create-card" style={{ padding: "12px" }} aria-label="高级编辑分区">
        {groups.map((group) => (
          <div key={group} className="char-create-tree-group">
            <span className="char-create-tree-group-title">{group}</span>
            {ADVANCED_SECTIONS.filter((s) => s.group === group).map((section) => (
              <button
                key={section.id}
                type="button"
                className={`char-create-tree-item ${
                  selectedSection.id === section.id ? "active" : ""
                }`}
                onClick={() => setSelectedSectionId(section.id)}
              >
                <span>{section.name}</span>
                <span className="char-create-meta" style={{ fontSize: "10px" }}>
                  {section.targetVersion}
                </span>
              </button>
            ))}
          </div>
        ))}
      </nav>

      {/* 分区占位说明与草稿摘要 */}
      <div className="char-create-card char-create-advanced-pane">
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
              高级编辑器包含系统提示、世界书、身份外貌、叙事规则与 HSR 扩展字段的深度编辑能力。
              为确保数据严谨性，当前阶段不提供伪造的保存表单。您在快速创建中填写的草稿数据已完整保留。
            </div>
          </div>
        </div>

        <div
          style={{
            padding: "12px 16px",
            background: "var(--bg-card, #1C212B)",
            borderRadius: "var(--radius-sm, 8px)",
            border: "1px solid var(--separator, #2A303C)",
          }}
        >
          <div className="char-create-meta" style={{ marginBottom: "8px", fontWeight: 600 }}>
            当前草稿共享状态
          </div>
          <ul
            style={{
              margin: 0,
              paddingLeft: "20px",
              fontSize: "12.5px",
              color: "var(--text-secondary, #9AA3B2)",
              lineHeight: 1.8,
            }}
          >
            <li>角色名称：{formData.name || "（未填写）"}</li>
            <li>简介：{formData.description || "（未填写）"}</li>
            <li>已添加标签数：{formData.tags.length} 个</li>
            <li>性格设定长度：{formData.personality.length} 字</li>
          </ul>
        </div>

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
      </div>
    </div>
  );
}
