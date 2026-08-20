import type { CharacterFormData } from "./types";

interface CharacterLivePreviewProps {
  formData: CharacterFormData;
  readOnly: boolean;
}

export function CharacterLivePreview({ formData, readOnly }: CharacterLivePreviewProps) {
  const avatarChar = formData.name.trim() ? formData.name.trim().charAt(0) : "?";

  return (
    <aside
      className="char-create-card char-create-preview-card"
      aria-label="角色卡实时预览"
      data-testid="live-preview"
    >
      <div className="char-create-section-head">
        <span className="char-create-meta">实时预览</span>
        <span
          className="char-create-meta"
          style={{
            border: "1px dashed var(--separator-strong, #3A4250)",
            padding: "2px 6px",
            borderRadius: "4px",
          }}
        >
          {readOnly ? "只读卡片" : "草稿预览"}
        </span>
      </div>

      <div className="char-create-preview-hero">
        <div className="char-create-avatar-box" aria-hidden="true">
          {avatarChar}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h3 className="char-create-preview-name" data-testid="preview-name">
            {formData.name.trim() ? (
              formData.name.trim()
            ) : (
              <span className="char-create-preview-placeholder">未填写名称</span>
            )}
          </h3>
          <span className="char-create-meta">
            {readOnly ? "v1 · 内置角色" : "v1 · 创建 · 草稿"}
          </span>
        </div>
      </div>

      <div className="char-create-tag-list" data-testid="preview-tags">
        {formData.tags.length > 0 ? (
          formData.tags.map((tag, idx) => (
            <span key={`${tag}-${idx}`} className="char-create-tag-pill">
              {tag}
            </span>
          ))
        ) : (
          <span className="char-create-preview-placeholder char-create-meta">
            未添加标签
          </span>
        )}
      </div>

      <p className="char-create-preview-summary" data-testid="preview-summary">
        {formData.description.trim() ? (
          formData.description.trim()
        ) : (
          <span className="char-create-preview-placeholder">未填写简介</span>
        )}
      </p>

      <div className="char-create-preview-voice">
        <span
          className="char-create-dot"
          style={{ background: "var(--text-muted, #6B7686)" }}
          aria-hidden="true"
        />
        <span>音色未配置 · 可在创建后前往「角色语音」</span>
      </div>
    </aside>
  );
}
