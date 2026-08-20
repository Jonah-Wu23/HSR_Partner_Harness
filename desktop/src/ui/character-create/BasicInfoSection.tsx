import { useState } from "react";
import { AlertCircleIcon, CloseIcon, InfoIcon } from "./icons";
import type { CharacterFormData } from "./types";

interface BasicInfoSectionProps {
  formData: CharacterFormData;
  nameError: string | null;
  readOnly: boolean;
  onFieldChange: <K extends keyof CharacterFormData>(field: K, value: CharacterFormData[K]) => void;
  onClearNameError: () => void;
}

export function BasicInfoSection({
  formData,
  nameError,
  readOnly,
  onFieldChange,
  onClearNameError,
}: BasicInfoSectionProps) {
  const [tagInput, setTagInput] = useState("");
  const [showAvatarNotice, setShowAvatarNotice] = useState(false);

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onFieldChange("name", e.target.value);
    if (nameError) {
      onClearNameError();
    }
  };

  const handleAddTag = () => {
    const trimmed = tagInput.trim();
    if (!trimmed) return;
    if (!formData.tags.includes(trimmed)) {
      onFieldChange("tags", [...formData.tags, trimmed]);
    }
    setTagInput("");
  };

  const handleTagKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddTag();
    }
  };

  const handleRemoveTag = (indexToRemove: number) => {
    onFieldChange(
      "tags",
      formData.tags.filter((_, idx) => idx !== indexToRemove),
    );
  };

  const avatarChar = formData.name.trim() ? formData.name.trim().charAt(0) : "?";

  return (
    <section className="char-create-card" data-testid="section-basic">
      <div className="char-create-section-head">
        <h2 className="char-create-section-title">基础信息</h2>
        <span className="char-create-meta">必填 1 项</span>
      </div>

      <div className="char-create-field">
        <label className="char-create-label" htmlFor="f-name">
          名称 <span className="char-create-req">*</span>
        </label>
        <input
          id="f-name"
          className="char-create-input"
          type="text"
          placeholder="例如：卡芙卡"
          value={formData.name}
          onChange={handleNameChange}
          disabled={readOnly}
          aria-invalid={nameError ? "true" : "false"}
          aria-describedby={nameError ? "f-name-error" : undefined}
          autoComplete="off"
        />
        {nameError ? (
          <p className="char-create-field-error" id="f-name-error" role="alert">
            <AlertCircleIcon />
            {nameError}
          </p>
        ) : null}
      </div>

      <div className="char-create-field">
        <label className="char-create-label">头像</label>
        <div className="char-create-avatar-row">
          <div className="char-create-avatar-box" aria-hidden="true" data-testid="avatar-preview">
            {avatarChar}
          </div>
          <div className="char-create-avatar-ctrls">
            <button
              type="button"
              className="char-btn char-btn-secondary"
              style={{ minHeight: "32px", padding: "4px 12px", fontSize: "12.5px", alignSelf: "flex-start" }}
              onClick={() => setShowAvatarNotice(true)}
              disabled={readOnly}
            >
              设置头像
            </button>
            <span className="char-create-meta">未设置时使用名称首字符占位</span>
          </div>
        </div>
        {showAvatarNotice ? (
          <div
            className="char-create-notice-box"
            style={{ padding: "8px 12px", fontSize: "12px", marginTop: "4px" }}
            role="status"
          >
            <InfoIcon width="14" height="14" />
            <span>头像资产管理（选择/裁切/写盘）将于 V0.3.5 开放，当前使用名称首字符占位。</span>
          </div>
        ) : null}
      </div>

      <div className="char-create-field">
        <label className="char-create-label" htmlFor="f-tag-input">
          标签
        </label>
        <div className="char-create-tag-list" data-testid="tag-list">
          {formData.tags.map((tag, idx) => (
            <span key={`${tag}-${idx}`} className="char-create-tag-pill">
              {tag}
              <button
                type="button"
                className="char-create-tag-del"
                aria-label={`删除标签「${tag}」`}
                onClick={() => handleRemoveTag(idx)}
                disabled={readOnly}
              >
                <CloseIcon />
              </button>
            </span>
          ))}
          <input
            id="f-tag-input"
            className="char-create-input char-create-tag-input"
            type="text"
            placeholder="输入后回车添加"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={handleTagKeyDown}
            disabled={readOnly}
            aria-label="添加标签"
          />
        </div>
      </div>

      <div className="char-create-field">
        <label className="char-create-label" htmlFor="f-summary">
          简介
        </label>
        <input
          id="f-summary"
          className="char-create-input"
          type="text"
          placeholder="一句话介绍这个角色"
          value={formData.description}
          onChange={(e) => onFieldChange("description", e.target.value)}
          disabled={readOnly}
          autoComplete="off"
        />
      </div>
    </section>
  );
}
