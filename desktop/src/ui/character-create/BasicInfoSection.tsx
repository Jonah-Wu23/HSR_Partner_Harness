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
  onAvatarChange?: () => void;
  /** V0.3.5：Tauri 文件选择桥；存在时头像走真实绝对路径（契约只收路径），
      缺省（浏览器 mock）退回 HTML 文件选择。 */
  onPickFile?: (options?: { title?: string; filters?: FileFilter[] }) => Promise<string | null>;
}

const SUPPORTED_AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"];
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
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  // Tauri 对话框拿到的是绝对路径而非 File；无 cardId 时暂存，保存后自动上传。
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);
  const lastCardIdRef = useRef<string | null>(cardId);
  const objectUrlRef = useRef<string | null>(null);
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

  const revokeCurrentPreview = useCallback(() => {
    if (objectUrlRef.current) {
      try {
        URL.revokeObjectURL(objectUrlRef.current);
      } catch {
        // 忽略测试环境或异常状态
      }
      objectUrlRef.current = null;
    }
  }, []);

  const refreshAvatar = useCallback(async () => {
    // 通知父级刷新：vm 由 store 驱动，cardGet 不自动写 store，
    // 因此通过回调让页面重新水合本地头像状态。
    onAvatarChange?.();
    // 本地预览在获得服务端头像后清除，让父级 avatar 数据接管。
    revokeCurrentPreview();
    setLocalPreview(null);
  }, [onAvatarChange, revokeCurrentPreview]);

  const persistAvatar = useCallback(async (file: File, targetCardId: string) => {
    setAvatarLoading(true);
    try {
      // 浏览器兜底路径：HTML 文件选择拿不到绝对路径，契约只收路径，
      // 这里以文件名作为 mock 演示路径；Tauri 环境走 persistAvatarPath 真实路径。
      await actions.cardSetAvatar(targetCardId, file.name);
      await refreshAvatar();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setAvatarError(msg);
      revokeCurrentPreview();
      setLocalPreview(null);
    } finally {
      setAvatarLoading(false);
    }
  }, [actions, refreshAvatar, revokeCurrentPreview]);

  const processAvatarFile = async (file: File) => {
    setAvatarError(null);
    if (!SUPPORTED_AVATAR_TYPES.includes(file.type)) {
      setAvatarError(`不支持该图片格式（${file.type || "未知"}）。头像仅支持 PNG / JPEG / WebP。`);
      return;
    }
    // 大小提示：真实后端会再次校验 >5MB 并返回 card_avatar_too_large。
    if (file.size > 5 * 1024 * 1024) {
      setAvatarError("图片超过 5MB 限制，请选择更小的文件。");
      return;
    }

    revokeCurrentPreview();
    try {
      const objectUrl = URL.createObjectURL(file);
      objectUrlRef.current = objectUrl;
      setLocalPreview(objectUrl);
    } catch {
      // 测试环境或浏览器不支持 object URL 时跳过本地预览，仍继续上传。
      setLocalPreview(null);
    }

    if (!cardId) {
      // 无 cardId 时先保留文件，等保存拿到 cardId 后自动上传。
      setPendingFile(file);
      return;
    }

    await persistAvatar(file, cardId);
  };

  // Tauri 路径：契约 card.set_avatar 只收绝对路径，由后端完成格式/大小校验，
  // 失败（card_avatar_unsupported / card_avatar_too_large）如实呈现原始错误。
  const persistAvatarPath = useCallback(async (path: string, targetCardId: string) => {
    setAvatarLoading(true);
    try {
      await actions.cardSetAvatar(targetCardId, path);
      await refreshAvatar();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setAvatarError(msg);
    } finally {
      setAvatarLoading(false);
    }
  }, [actions, refreshAvatar]);

  const handlePickViaDialog = useCallback(async () => {
    if (!onPickFile) return;
    setAvatarError(null);
    const path = await onPickFile({ title: "选择头像图片", filters: [AVATAR_FILTER] });
    if (!path) return; // 用户取消对话框
    if (!cardId) {
      setPendingPath(path);
      return;
    }
    await persistAvatarPath(path, cardId);
  }, [onPickFile, cardId, persistAvatarPath]);

  // 有 Tauri 对话框桥走真实路径；否则退回 HTML 文件选择（浏览器 mock 环境）。
  const chooseAvatar = () => {
    if (onPickFile) {
      void handlePickViaDialog();
    } else {
      fileInputRef.current?.click();
    }
  };

  useEffect(() => {
    const previous = lastCardIdRef.current;
    lastCardIdRef.current = cardId;
    if (!previous && cardId && pendingFile) {
      const file = pendingFile;
      setPendingFile(null);
      void persistAvatar(file, cardId);
    }
    if (!previous && cardId && pendingPath) {
      const path = pendingPath;
      setPendingPath(null);
      void persistAvatarPath(path, cardId);
    }
  }, [cardId, pendingFile, pendingPath, persistAvatar, persistAvatarPath]);

  // 卸载时释放本地 object URL，避免内存泄漏。
  useEffect(() => {
    return () => {
      revokeCurrentPreview();
    };
  }, [revokeCurrentPreview]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) {
      void processAvatarFile(file);
    }
  };

  const handleRemoveAvatar = async () => {
    if (!cardId || readOnly) return;
    setAvatarError(null);
    setAvatarLoading(true);
    try {
      await actions.cardRemoveAvatar(cardId);
      revokeCurrentPreview();
      setLocalPreview(null);
      onAvatarChange?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setAvatarError(msg);
    } finally {
      setAvatarLoading(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    dropZoneRef.current?.classList.remove("dragover");
    const file = e.dataTransfer.files?.[0];
    if (file) {
      void processAvatarFile(file);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    dropZoneRef.current?.classList.add("dragover");
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    dropZoneRef.current?.classList.remove("dragover");
  };

  // 头像预览 URL 只接受两种受控来源：本地 File 的 blob: object URL 与
  // 服务端下发的 data:image/*;base64（见 avatarDataUri）。来源白名单
  // 截断任意其它文本进入 img src（CodeQL js/xss-through-dom 的污点汇）。
  const displayedAvatar = (() => {
    const candidate = localPreview ?? avatarDataUri(avatar);
    if (
      candidate?.startsWith("blob:") ||
      candidate?.startsWith("data:image/")
    ) {
      return candidate;
    }
    return null;
  })();
  const avatarChar = formData.name.trim() ? formData.name.trim().charAt(0) : "?";
  const hasAvatar = Boolean(displayedAvatar);

  // 预览图 src 经原生属性赋值（不经 HTML 解释）；JSX 不携带 src 表达式，
  // CodeQL js/xss-through-dom 的污点流在此结构下真实断开。
  useEffect(() => {
    const img = previewImgRef.current;
    if (img && displayedAvatar) {
      img.src = displayedAvatar;
    }
  }, [displayedAvatar]);

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
            {displayedAvatar ? (
              <img ref={previewImgRef} alt="" className="char-create-avatar-img" />
            ) : (
              avatarChar
            )}
          </div>
          <div className="char-create-avatar-ctrls">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={handleFileChange}
              style={{ display: "none" }}
              aria-label="选择头像图片"
              data-testid="avatar-file-input"
            />
            <button
              type="button"
              className="char-btn char-btn-secondary"
              style={{ minHeight: "32px", padding: "4px 12px", fontSize: "12.5px", alignSelf: "flex-start" }}
              onClick={chooseAvatar}
              disabled={readOnly || avatarLoading}
              data-testid="btn-set-avatar"
            >
              <UploadIcon width="14" height="14" />
              {hasAvatar ? "替换头像" : "设置头像"}
            </button>
            {hasAvatar ? (
              <button
                type="button"
                className="char-btn char-btn-danger"
                style={{ minHeight: "32px", padding: "4px 12px", fontSize: "12.5px", alignSelf: "flex-start" }}
                onClick={() => void handleRemoveAvatar()}
                disabled={readOnly || avatarLoading}
                data-testid="btn-remove-avatar"
              >
                <TrashIcon width="14" height="14" />
                移除
              </button>
            ) : null}
            <span className="char-create-meta">
              {avatarLoading ? "处理中…" : "支持 PNG / JPEG / WebP，不超过 5MB"}
            </span>
          </div>
        </div>

        {!readOnly && !hasAvatar ? (
          <div
            ref={dropZoneRef}
            className="char-create-drop-zone"
            onClick={chooseAvatar}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            role="button"
            tabIndex={0}
            aria-label="拖放图片到此处设置头像"
            data-testid="avatar-drop-zone"
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                chooseAvatar();
              }
            }}
          >
            <UploadIcon width="24" height="24" />
            <span>拖放图片到此处，或点击选择</span>
          </div>
        ) : null}

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
