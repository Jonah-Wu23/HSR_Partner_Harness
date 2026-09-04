import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { CardGetResult, CardExportJsonResult, CardExportPngResult } from "../../contracts/protocol";
import { CARD_EXPORT_FAILED } from "../../contracts/protocol";
import type { DesktopBackend } from "../../services/backend";
import {
  AlertCircleIcon,
  AlertTriangleIcon,
  CheckIcon,
  FileImageIcon,
  FileJsonIcon,
  FolderIcon,
  RetryIcon,
} from "./CharacterTransferIcons";

import "./character-transfer.css";

interface CharacterExportFlowProps {
  cardId: string;
  cardName: string;
  backend?: DesktopBackend;
  actions: HarnessActions;
  onClose: () => void;
  onSuccess?: () => void;
}

type ExportFormat = "json" | "png";

type ExportPhase =
  | { kind: "loadingCard" }
  | { kind: "readonly"; message: string }
  | { kind: "confirm"; card: CardGetResult }
  | { kind: "exporting"; path: string }
  | { kind: "success"; format: ExportFormat; json?: CardExportJsonResult; png?: CardExportPngResult }
  | { kind: "error"; title: string; message: string; guideAvatar: boolean };

const JSON_FILTER = { name: "Character Card JSON", extensions: ["json"] };
const PNG_FILTER = { name: "PNG Character Card", extensions: ["png"] };

function getWorldBookCount(card: Record<string, unknown>): number {
  const data = card.data as Record<string, unknown> | undefined;
  if (!data) return 0;
  const book = data.character_book as Record<string, unknown> | undefined;
  const entries = book?.entries;
  if (Array.isArray(entries)) return entries.length;
  return 0;
}

function getGreetingCount(card: Record<string, unknown>): number {
  // 口径与后端 greeting_count() 一致：首句 + 备选问候
  const data = card.data as Record<string, unknown> | undefined;
  if (!data) return 0;
  const alternate = Array.isArray(data.alternate_greetings) ? data.alternate_greetings.length : 0;
  return (typeof data.first_mes === "string" && data.first_mes.trim() !== "" ? 1 : 0) + alternate;
}

function getExtensionKeys(card: Record<string, unknown>): string[] {
  const data = card.data as Record<string, unknown> | undefined;
  if (!data) return [];
  const extensions = data.extensions as Record<string, unknown> | undefined;
  if (!extensions || typeof extensions !== "object") return [];
  return Object.keys(extensions).filter((k) => extensions[k] !== undefined);
}

function getSpecVersion(card: Record<string, unknown>): string {
  const value = card.spec_version;
  return typeof value === "string" && value.trim() !== "" ? value : "未声明";
}

function safeFileName(name: string): string {
  // 移除文件系统不友好字符，保留中文、字母、数字、空格与下划线
  return name.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim() || "character";
}

function withExtension(name: string, ext: ExportFormat): string {
  const base = name.trim().replace(/\.(json|png)$/i, "") || "character";
  return `${base}.${ext}`;
}

export function CharacterExportFlow({
  cardId,
  cardName,
  backend,
  actions,
  onClose,
  onSuccess,
}: CharacterExportFlowProps) {
  const [phase, setPhase] = useState<ExportPhase>({ kind: "loadingCard" });
  const [exportFormat, setExportFormat] = useState<ExportFormat>("json");
  const [fileName, setFileName] = useState(`${safeFileName(cardName)}.json`);
  const [saveAvatar, setSaveAvatar] = useState(true);
  // StrictMode 开发模式会 mount→cleanup→再 mount：effect 体必须重新置 true，
  // 否则 cleanup 后 mountedRef 永久 false，异步阶段的 setPhase 全被守卫吞掉。
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleError = useCallback((error: unknown, title: string, guideAvatar = false) => {
    const err = error instanceof Error ? error : new Error(String(error));
    const code = (err as Error & { code?: string }).code;
    const message = code ? `${code}：${err.message}` : err.message;
    if (mountedRef.current) {
      setPhase({ kind: "error", title, message, guideAvatar });
    }
  }, []);

  const loadCard = useCallback(async () => {
    try {
      const result = await actions.cardGet(cardId);
      if (!mountedRef.current) return;
      if (result.read_only || String(cardId).startsWith("builtin:")) {
        setPhase({ kind: "readonly", message: "内置角色卡只读，导出前请先复制。" });
        return;
      }
      setFileName(withExtension(`${safeFileName(result.card.name as string || cardName)}`, "json"));
      setPhase({ kind: "confirm", card: result });
    } catch (error) {
      handleError(error, "加载角色卡失败");
    }
  }, [cardId, cardName, actions, handleError]);

  useEffect(() => {
    void loadCard();
  }, [loadCard]);

  const handleDuplicate = useCallback(async () => {
    try {
      await actions.duplicateCard(cardId);
      // 复制成功后关闭导出流程，让用户重新选择新副本导出
      onSuccess?.();
      onClose();
    } catch (error) {
      handleError(error, "复制失败");
    }
  }, [cardId, actions, onSuccess, onClose, handleError]);

  const switchFormat = useCallback((format: ExportFormat) => {
    setExportFormat(format);
    setFileName((prev) => withExtension(prev, format));
  }, []);

  const handleExport = useCallback(async () => {
    if (phase.kind !== "confirm") return;
    if (!backend) {
      handleError(new Error("当前环境未提供桌面后端，无法打开保存对话框。请在 Tauri 桌面端重试。"), "环境不可用");
      return;
    }
    const hasAvatar = phase.card.avatar !== null;
    if (exportFormat === "png") {
      let path: string | null;
      try {
        path = await backend.saveFile({
          title: "导出角色卡 PNG",
          defaultPath: fileName,
          filters: [PNG_FILTER],
        });
      } catch (error) {
        handleError(error, "打开保存对话框失败");
        return;
      }
      if (!path) return;
      setPhase({ kind: "exporting", path });
      try {
        const result = await actions.cardExportPng(cardId, path);
        if (mountedRef.current) {
          setPhase({ kind: "success", format: "png", png: result });
          onSuccess?.();
        }
      } catch (error) {
        // §1.3：无头像卡的 PNG 导出由后端真实拒绝（card_export_failed），
        // UI 不预判成败，只在真实失败后给出「先去设置头像」引导。
        const code = (error as Error & { code?: string }).code;
        handleError(error, "导出失败", code === CARD_EXPORT_FAILED && !hasAvatar);
      }
      return;
    }
    let path: string | null;
    try {
      path = await backend.saveFile({
        title: "导出角色卡",
        defaultPath: fileName,
        filters: [JSON_FILTER],
      });
    } catch (error) {
      handleError(error, "打开保存对话框失败");
      return;
    }
    if (!path) return;
    setPhase({ kind: "exporting", path });
    try {
      const result = await actions.cardExportJson(cardId, path, saveAvatar);
      if (mountedRef.current) {
        setPhase({ kind: "success", format: "json", json: result });
        onSuccess?.();
      }
    } catch (error) {
      handleError(error, "导出失败");
    }
  }, [phase, backend, exportFormat, fileName, cardId, saveAvatar, actions, onSuccess, handleError]);

  const handleRetry = useCallback(() => {
    void loadCard();
  }, [loadCard]);

  const renderLoading = () => (
    <div className="xfer-page">
      <div className="xfer-title-row">
        <h2 className="xfer-title">正在加载角色卡…</h2>
      </div>
      <div className="xfer-card xfer-card-subtle">
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span className="char-dot char-dot-progress" />
          <span className="xfer-muted">读取角色卡完整数据以确认导出内容</span>
        </div>
      </div>
    </div>
  );

  const renderReadonly = () => (
    <div className="xfer-page">
      <div className="xfer-card xfer-result">
        <div className="xfer-status-mark warn">
          <AlertTriangleIcon />
        </div>
        <h2 className="xfer-result-title">内置角色卡不可导出</h2>
        <pre className="xfer-error-block">{phase.kind === "readonly" ? phase.message : ""}</pre>
        <p className="xfer-muted">复制后将得到一张可编辑的自定义卡，随后可正常导出。</p>
        <div className="xfer-actions xfer-actions-center">
          <button type="button" className="xfer-btn xfer-btn-primary" onClick={() => void handleDuplicate()}>
            复制此卡
          </button>
          <button type="button" className="xfer-btn xfer-btn-ghost" onClick={onClose}>
            取消
          </button>
        </div>
      </div>
    </div>
  );

  const renderConfirm = () => {
    if (phase.kind !== "confirm") return null;
    const { card } = phase;
    const worldBookCount = getWorldBookCount(card.card);
    const greetingCount = getGreetingCount(card.card);
    const extensionKeys = getExtensionKeys(card.card);
    const hasAvatar = card.avatar !== null;
    const isPng = exportFormat === "png";

    return (
      <div className="xfer-page">
        <div className="xfer-title-row">
          <h2 className="xfer-title">导出角色</h2>
        </div>
        <div className="xfer-card">
          <div className="xfer-field">
            <label>导出格式</label>
            <div className="xfer-format-toggle" role="radiogroup" aria-label="导出格式">
              <label className={`xfer-format-option ${!isPng ? "active" : ""}`}>
                <input
                  type="radio"
                  name="export-format"
                  checked={!isPng}
                  onChange={() => switchFormat("json")}
                  aria-label="JSON 格式"
                />
                <FileJsonIcon />
                <span>JSON（v3 数据文件）</span>
              </label>
              <label className={`xfer-format-option ${isPng ? "active" : ""}`}>
                <input
                  type="radio"
                  name="export-format"
                  checked={isPng}
                  onChange={() => switchFormat("png")}
                  aria-label="PNG 格式"
                />
                <FileImageIcon />
                <span>PNG（头像内嵌单文件）</span>
              </label>
            </div>
          </div>
          <div className="xfer-field">
            <label htmlFor="export-filename">文件名</label>
            <input
              id="export-filename"
              className="xfer-input"
              type="text"
              value={fileName}
              onChange={(e) => setFileName(e.target.value)}
              aria-label="导出文件名"
            />
          </div>
          <div className="xfer-save-path">
            <FolderIcon />
            <span className="xfer-muted">保存位置</span>
            <span className="xfer-meta">
              点击「导出」后在系统对话框选择保存目录；文件名 {fileName}
            </span>
          </div>
        </div>
        {isPng && !hasAvatar && (
          <div className="xfer-warn-banner" role="alert">
            <AlertTriangleIcon />
            <span>
              PNG 导出需要卡内已设置头像；当前卡未设置头像，导出将被后端拒绝。请先设置头像，或改用 JSON 导出。
            </span>
          </div>
        )}
        <div className="xfer-card">
          <div className="xfer-checklist">
            <div className="xfer-check-row">
              {hasAvatar ? (
                <CheckIcon className="xfer-check-ok" />
              ) : (
                <AlertTriangleIcon className="xfer-check-warn" />
              )}
              <span className="xfer-check-name">头像</span>
              <span className="xfer-check-text">
                {isPng
                  ? hasAvatar
                    ? "已绑定头像，将内嵌为 PNG 图像块"
                    : "未设置头像，PNG 导出将被拒绝"
                  : hasAvatar
                    ? "已绑定头像"
                    : "无头像，JSON 中只保留引用"}
              </span>
            </div>
            <div className="xfer-check-row">
              <CheckIcon className="xfer-check-ok" />
              <span className="xfer-check-name">规格</span>
              <span className="xfer-check-text">Character Card v{getSpecVersion(card.card)}</span>
            </div>
            <div className="xfer-check-row">
              <CheckIcon className="xfer-check-ok" />
              <span className="xfer-check-name">问候</span>
              <span className="xfer-check-text">
                {greetingCount > 0 ? `${greetingCount} 条（含开场白与备选）` : "无问候文本"}
              </span>
            </div>
            <div className="xfer-check-row">
              <CheckIcon className="xfer-check-ok" />
              <span className="xfer-check-name">世界书</span>
              <span className="xfer-check-text">
                {worldBookCount > 0 ? `${worldBookCount} 条已包含` : "无世界书条目"}
              </span>
            </div>
            <div className="xfer-check-row">
              <CheckIcon className="xfer-check-ok" />
              <span className="xfer-check-name">扩展字段</span>
              <span className="xfer-check-text">
                {extensionKeys.length > 0
                  ? `${extensionKeys.join("、")} 等 ${extensionKeys.length} 项`
                  : "无扩展字段"}
              </span>
            </div>
          </div>
        </div>
        {!isPng && (
          <div className="xfer-card">
            <label className="xfer-checkbox-row">
              <input
                type="checkbox"
                checked={saveAvatar}
                onChange={(e) => setSaveAvatar(e.target.checked)}
                aria-label="同时保存头像文件"
              />
              <span>同时保存头像文件（导出 &lt;文件名&gt;.avatar.&lt;扩展名&gt;）</span>
            </label>
          </div>
        )}
        <div className="xfer-actions">
          <button type="button" className="xfer-btn xfer-btn-ghost" onClick={onClose}>
            取消
          </button>
          <button type="button" className="xfer-btn xfer-btn-primary" onClick={() => void handleExport()}>
            {isPng ? <FileImageIcon /> : <FileJsonIcon />}
            导出
          </button>
        </div>
      </div>
    );
  };

  const renderExporting = () => (
    <div className="xfer-page">
      <div className="xfer-title-row">
        <h2 className="xfer-title">正在导出…</h2>
      </div>
      <div className="xfer-card xfer-card-subtle">
        <div className="xfer-save-path">
          <FolderIcon />
          <span className="xfer-muted">保存位置</span>
          <span className="xfer-meta">{phase.kind === "exporting" ? phase.path : ""}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span className="char-dot char-dot-progress" />
          <span className="xfer-muted">写入期间请勿关闭窗口</span>
        </div>
      </div>
    </div>
  );

  const renderSuccess = () => {
    if (phase.kind !== "success") return null;
    const png = phase.png;
    return (
      <div className="xfer-page">
        <div className="xfer-card xfer-result">
          <div className="xfer-status-mark ok">
            <CheckIcon />
          </div>
          <h2 className="xfer-result-title">导出完成</h2>
          <span className="xfer-result-path">{phase.json?.path ?? png?.path ?? ""}</span>
          {phase.format === "json" && phase.json ? (
            <span className="xfer-muted">
              {phase.json.avatar_saved ? "头像文件已配套保存" : "未保存头像文件"}
            </span>
          ) : null}
          {phase.format === "png" && png ? (
            <>
              <span className="xfer-muted">头像已内嵌 PNG 图像块，单文件可直接导入 SillyTavern</span>
              <div className="xfer-result-facts">
                <div className="xfer-fact">
                  <span className="xfer-fact-label">名称</span>
                  <span className="xfer-fact-value">{png.name}</span>
                </div>
                <div className="xfer-fact">
                  <span className="xfer-fact-label">规格</span>
                  <span className="xfer-fact-value">Character Card v{png.spec_version}</span>
                </div>
                <div className="xfer-fact">
                  <span className="xfer-fact-label">备选问候</span>
                  <span className="xfer-fact-value">{png.greeting_count}</span>
                </div>
                <div className="xfer-fact">
                  <span className="xfer-fact-label">世界书条目</span>
                  <span className="xfer-fact-value">{png.world_book_entries}</span>
                </div>
                <div className="xfer-fact">
                  <span className="xfer-fact-label">扩展</span>
                  <span className="xfer-fact-value">
                    {png.extensions.length > 0 ? png.extensions.join("、") : "无"}
                  </span>
                </div>
              </div>
            </>
          ) : null}
          <div className="xfer-actions xfer-actions-center">
            <button type="button" className="xfer-btn xfer-btn-primary" onClick={onClose}>
              返回角色库
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderError = () => {
    if (phase.kind !== "error") return null;
    return (
      <div className="xfer-page">
        <div className="xfer-card xfer-result">
          <div className="xfer-status-mark danger">
            <AlertCircleIcon />
          </div>
          <h2 className="xfer-result-title">{phase.title}</h2>
          <pre className="xfer-error-block">{phase.message}</pre>
          {phase.guideAvatar && (
            <div className="xfer-guide-block" role="note">
              <AlertTriangleIcon />
              <div>
                <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>PNG 导出需要头像</div>
                <p className="xfer-muted">
                  请先在角色编辑页为该卡设置头像，完成后再回到这里导出 PNG；或改用 JSON 格式导出。
                </p>
              </div>
            </div>
          )}
          <p className="xfer-muted">目标文件未被创建，请检查路径与权限后重试。</p>
          <div className="xfer-actions xfer-actions-center">
            <button type="button" className="xfer-btn xfer-btn-secondary" onClick={handleRetry}>
              <RetryIcon />
              重试
            </button>
            <button type="button" className="xfer-btn xfer-btn-ghost" onClick={onClose}>
              取消
            </button>
          </div>
        </div>
      </div>
    );
  };

  switch (phase.kind) {
    case "loadingCard":
      return renderLoading();
    case "readonly":
      return renderReadonly();
    case "confirm":
      return renderConfirm();
    case "exporting":
      return renderExporting();
    case "success":
      return renderSuccess();
    case "error":
      return renderError();
  }
}
