import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircleIcon, CloseIcon, UploadIcon, TrashIcon } from "./icons";
import { avatarDataUri, type CharacterFormData } from "./types";
import type { HarnessActions } from "../../contracts/actions";
import type { CardAvatarPayload } from "../../contracts/protocol";
import type { FileFilter } from "../../services/backend";

interface BasicInfoSectionProps {
  cardId: string | null;
  formData: CharacterFormData;
  avatar: CardAvatarPayload | null | undefined;
  nameError: string | null;
  readOnly: boolean;
  actions: HarnessActions;
  onFieldChange: <K extends keyof CharacterFormData>(field: K, value: CharacterFormData[K]) => void;
  onClearNameError: () => void;
  /** 头像设置或移除后重新读取该卡详情；读取失败时 reject。 */
  onAvatarChange: (cardId: string) => Promise<void>;
  /** 系统文件对话框；card.set_avatar 只收绝对路径。 */
  onPickFile: (options?: { title?: string; filters?: FileFilter[] }) => Promise<string | null>;
}

const AVATAR_FILTER: FileFilter = { name: "图片", extensions: ["png", "jpg", "jpeg", "webp"] };

export function BasicInfoSection({
  cardId,
  formData,
  avatar,
  nameError,
  readOnly,
  actions,
  onFieldChange,
  onClearNameError,
  onAvatarChange,
  onPickFile,
}: BasicInfoSectionProps) {
  const [tagInput, setTagInput] = useState("");
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(false);
  // 服务端 data URI 头像先转成 object URL 再交给 img.src，img.src 只收到浏览器生成的
  // blob: URL。data:image/svg+xml 可携带脚本，CodeQL js/xss-through-dom 会把它判为 HTML 解释 sink。
  const [cardAvatarUrl, setCardAvatarUrl] = useState<string | null>(null);
  const cardAvatarUrlRef = useRef<string | null>(null);
  // 无 cardId 时暂存选中的头像路径，首次保存拿到 cardId 后上传。
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const lastCardIdRef = useRef<string | null>(cardId);
  const previewImgRef = useRef<HTMLImageElement | null>(null);

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

  // 后端读取文件并判定格式与大小，失败（card_avatar_unsupported / card_avatar_too_large）
  // 显示原始错误；上传成功后重新读取卡详情的失败同样显示。
  const persistAvatarPath = useCallback(async (path: string, targetCardId: string) => {
    setAvatarLoading(true);
    try {
      await actions.cardSetAvatar(targetCardId, path);
      await onAvatarChange(targetCardId);
    } catch (err) {
      setAvatarError(err instanceof Error ? err.message : String(err));
    } finally {
      setAvatarLoading(false);
    }
  }, [actions, onAvatarChange]);

  const chooseAvatar = async () => {
    setAvatarError(null);
    const path = await onPickFile({ title: "选择头像图片", filters: [AVATAR_FILTER] });
    if (!path) return; // 用户取消对话框
    if (!cardId) {
      setPendingPath(path);
      return;
    }
    await persistAvatarPath(path, cardId);
  };

  useEffect(() => {
    const previous = lastCardIdRef.current;
    lastCardIdRef.current = cardId;
    if (!previous && cardId && pendingPath) {
      const path = pendingPath;
      setPendingPath(null);
      void persistAvatarPath(path, cardId);
    }
  }, [cardId, pendingPath, persistAvatarPath]);

  const handleRemoveAvatar = async (targetCardId: string) => {
    setAvatarError(null);
    setAvatarLoading(true);
    try {
      await actions.cardRemoveAvatar(targetCardId);
      await onAvatarChange(targetCardId);
    } catch (err) {
      setAvatarError(err instanceof Error ? err.message : String(err));
    } finally {
      setAvatarLoading(false);
    }
  };

  const avatarChar = formData.name.trim() ? formData.name.trim().charAt(0) : "?";
  const hasAvatar = Boolean(cardAvatarUrl);

  // 服务端 data URI → object URL 的异步转换；替换、移除时释放旧 URL。
  useEffect(() => {
    const dataUri = avatarDataUri(avatar);
    if (!dataUri) {
      if (cardAvatarUrlRef.current) {
        URL.revokeObjectURL(cardAvatarUrlRef.current);
        cardAvatarUrlRef.current = null;
      }
      setCardAvatarUrl(null);
      return;
    }
    let revoked = false;
    fetch(dataUri)
      .then((res) => res.blob())
      .then((blob) => {
        if (revoked) return;
        const objectUrl = URL.createObjectURL(blob);
        if (cardAvatarUrlRef.current) {
          URL.revokeObjectURL(cardAvatarUrlRef.current);
        }
        cardAvatarUrlRef.current = objectUrl;
        setCardAvatarUrl(objectUrl);
      })
      .catch((err: unknown) => {
        if (!revoked) setAvatarError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      revoked = true;
    };
  }, [avatar]);

  // 组件卸载时释放当前卡头像的 object URL。
  useEffect(() => {
    return () => {
      if (cardAvatarUrlRef.current) {
        URL.revokeObjectURL(cardAvatarUrlRef.current);
      }
    };
  }, []);

  // 预览图 src 经原生属性赋值。写入 img.src（HTML 解释上下文）前断言
  // 字符串不含 HTML meta 字符（" ' & < >），blob: object URL 恒能通过。
  useEffect(() => {
    const img = previewImgRef.current;
    if (img && cardAvatarUrl && !/["'&<>]/.test(cardAvatarUrl)) {
      img.src = cardAvatarUrl;
    }
  }, [cardAvatarUrl]);

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
          <div
            className={`char-create-avatar-box ${hasAvatar ? "has-image" : ""}`}
            aria-hidden="true"
            data-testid="avatar-preview"
          >
            {hasAvatar ? (
              <img ref={previewImgRef} alt="" className="char-create-avatar-img" />
            ) : (
              avatarChar
            )}
          </div>
          <div className="char-create-avatar-ctrls">
            <button
              type="button"
              className="char-btn char-btn-secondary"
              style={{ minHeight: "32px", padding: "4px 12px", fontSize: "12.5px", alignSelf: "flex-start" }}
              onClick={() => void chooseAvatar()}
              disabled={readOnly || avatarLoading}
              data-testid="btn-set-avatar"
            >
              <UploadIcon width="14" height="14" />
              {hasAvatar ? "替换头像" : "设置头像"}
            </button>
            {hasAvatar && cardId ? (
              <button
                type="button"
                className="char-btn char-btn-danger"
                style={{ minHeight: "32px", padding: "4px 12px", fontSize: "12.5px", alignSelf: "flex-start" }}
                onClick={() => void handleRemoveAvatar(cardId)}
                disabled={readOnly || avatarLoading}
                data-testid="btn-remove-avatar"
              >
                <TrashIcon width="14" height="14" />
                移除
              </button>
            ) : null}
            <span className="char-create-meta">
              {avatarLoading
                ? "处理中…"
                : pendingPath
                  ? "已选择头像，保存后上传"
                  : "支持 PNG / JPEG / WebP，不超过 5MB"}
            </span>
          </div>
        </div>

        {avatarError ? (
          <div
            className="char-create-field-error"
            style={{ marginTop: "4px" }}
            role="alert"
            data-testid="avatar-error"
          >
            <AlertCircleIcon />
            {avatarError}
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
