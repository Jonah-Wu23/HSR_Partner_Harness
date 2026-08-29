import type { CharacterCardState } from "../../contracts/protocol";
import type { HarnessActions } from "../../contracts/actions";
import { avatarDataUri, isCardPublished, type CharacterFormData, type PublishStatus } from "./types";
import type { CardAvatarPayload } from "../../contracts/protocol";

interface CharacterLivePreviewProps {
  cardId: string | null;
  formData: CharacterFormData;
  avatar: CardAvatarPayload | null | undefined;
  readOnly: boolean;
  cardState?: CharacterCardState;
  publishStatus: PublishStatus;
  publishError: string | null;
  actions: HarnessActions;
  onPublish?: () => void;
  onStartChat?: () => void;
}

export function CharacterLivePreview({
  cardId,
  formData,
  avatar,
  readOnly,
  cardState,
  publishStatus,
  publishError,
  actions,
  onPublish,
  onStartChat,
}: CharacterLivePreviewProps) {
  const avatarChar = formData.name.trim() ? formData.name.trim().charAt(0) : "?";
  const avatarUri = avatarDataUri(avatar);
  const published = isCardPublished(cardState);

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
          {readOnly ? "只读卡片" : published ? "已发布" : "草稿预览"}
        </span>
      </div>

      <div className="char-create-preview-hero">
        <div className={`char-create-avatar-box ${avatarUri ? "has-image" : ""}`} aria-hidden="true" data-testid="preview-avatar">
          {avatarUri ? <img src={avatarUri} alt="" className="char-create-avatar-img" /> : avatarChar}
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
            {readOnly ? "v1 · 内置角色" : published ? "v1 · 已发布" : "v1 · 创建 · 草稿"}
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
          <span className="char-create-preview-placeholder char-create-meta">未添加标签</span>
        )}
      </div>

      <p className="char-create-preview-summary" data-testid="preview-summary">
        {formData.description.trim() ? (
          formData.description.trim()
        ) : (
          <span className="char-create-preview-placeholder">未填写简介</span>
        )}
      </p>

      {formData.first_mes.trim() ? (
        <div
          className="char-create-preview-quote"
          data-testid="preview-first-mes"
        >
          <div className="char-create-meta" style={{ marginBottom: "4px" }}>首句预览</div>
          <div style={{ fontStyle: "italic" }}>「{formData.first_mes.trim()}」</div>
        </div>
      ) : null}

      {formData.mes_example.trim() ? (
        <div
          className="char-create-preview-block"
          data-testid="preview-mes-example"
        >
          <div className="char-create-meta" style={{ marginBottom: "4px" }}>示例对话</div>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {formData.mes_example.trim()}
          </pre>
        </div>
      ) : null}

      <div
        className="char-create-preview-stats"
        data-testid="preview-stats"
      >
        <div className="char-create-preview-stat">
          <span className="char-create-meta">备选问候</span>
          <span className="char-create-meta" style={{ fontWeight: 600 }}>{formData.alternate_greetings.length} 条</span>
        </div>
        <div className="char-create-preview-stat">
          <span className="char-create-meta">系统提示</span>
          <span className="char-create-meta" style={{ fontWeight: 600 }}>{formData.system_prompt.length} 字</span>
        </div>
        <div className="char-create-preview-stat">
          <span className="char-create-meta">历史后指令</span>
          <span className="char-create-meta" style={{ fontWeight: 600 }}>{formData.post_history_instructions.length} 字</span>
        </div>
      </div>

      <div className="char-create-preview-voice">
        <span
          className="char-create-dot"
          style={{ background: "var(--text-muted, #6B7686)" }}
          aria-hidden="true"
        />
        <span>音色未配置 · 可在创建后前往「角色语音」</span>
      </div>

      {cardId && !readOnly ? (
        <div className="char-create-preview-actions">
          {published ? (
            <button
              type="button"
              className="char-btn char-btn-primary"
              style={{ width: "100%" }}
              onClick={() => onStartChat?.()}
              data-testid="btn-start-chat"
            >
              使用该角色开始对话
            </button>
          ) : (
            <button
              type="button"
              className="char-btn char-btn-primary"
              style={{ width: "100%" }}
              onClick={() => onPublish?.()}
              disabled={publishStatus === "publishing"}
              data-testid="btn-publish"
            >
              {publishStatus === "publishing" ? "发布中…" : "完成创建"}
            </button>
          )}
          {publishStatus === "error" && publishError ? (
            <div className="char-create-field-error" role="alert" data-testid="publish-error">
              <span style={{ color: "var(--danger, #DC2626)" }}>{publishError}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
