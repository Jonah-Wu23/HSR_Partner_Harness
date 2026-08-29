import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { CardGetResult, CardExportJsonResult } from "../../contracts/protocol";
import type { DesktopBackend } from "../../services/backend";
import {
  AlertCircleIcon,
  AlertTriangleIcon,
  CheckIcon,
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

type ExportPhase =
  | { kind: "loadingCard" }
  | { kind: "readonly"; message: string }
  | { kind: "confirm"; card: CardGetResult }
  | { kind: "exporting"; path: string }
  | { kind: "success"; result: CardExportJsonResult }
  | { kind: "error"; title: string; message: string };

const JSON_FILTER = { name: "Character Card JSON", extensions: ["json"] };

function getWorldBookCount(card: Record<string, unknown>): number {
  const data = card.data as Record<string, unknown> | undefined;
  if (!data) return 0;
  const book = data.character_book as Record<string, unknown> | undefined;
  const entries = book?.entries;
  if (Array.isArray(entries)) return entries.length;
  return 0;
}

function getExtensionKeys(card: Record<string, unknown>): string[] {
  const data = card.data as Record<string, unknown> | undefined;
  if (!data) return [];
  const extensions = data.extensions as Record<string, unknown> | undefined;
  if (!extensions || typeof extensions !== "object") return [];
  return Object.keys(extensions).filter((k) => extensions[k] !== undefined);
}

function safeFileName(name: string): string {
  // 移除文件系统不友好字符，保留中文、字母、数字、空格与下划线
  return name.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim() || "character";
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
  const [fileName, setFileName] = useState(`${safeFileName(cardName)}.json`);
  const [saveAvatar, setSaveAvatar] = useState(true);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleError = useCallback((error: unknown, title: string) => {
    const err = error instanceof Error ? error : new Error(String(error));
    const code = (err as Error & { code?: string }).code;
    const message = code ? `${code}：${err.message}` : err.message;
    if (mountedRef.current) {
      setPhase({ kind: "error", title, message });
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
      setFileName(`${safeFileName(result.card.name as string || cardName)}.json`);
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

  const handleExport = useCallback(async () => {
    if (!backend) {
      handleError(new Error("当前环境未提供桌面后端，无法打开保存对话框。请在 Tauri 桌面端重试。"), "环境不可用");
      return;
    }
    const path = await backend.saveFile({
      title: "导出角色卡",
      defaultPath: fileName,
      filters: [JSON_FILTER],
    });
    if (!path) return;
    setPhase({ kind: "exporting", path });
    try {
      const result = await actions.cardExportJson(cardId, path, saveAvatar);
      if (mountedRef.current) {
        setPhase({ kind: "success", result });
        onSuccess?.();
      }
    } catch (error) {
      handleError(error, "导出失败");
    }
  }, [backend, fileName, cardId, saveAvatar, actions, onSuccess, handleError]);

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
    const extensionKeys = getExtensionKeys(card.card);
    const hasAvatar = card.avatar !== null;

    return (
      <div className="xfer-page">
        <div className="xfer-title-row">
          <h2 className="xfer-title">导出角色</h2>
        </div>
        <div className="xfer-card">
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
        </div>
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
                {hasAvatar ? "已绑定头像" : "无头像，JSON 中只保留引用"}
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
        <div className="xfer-actions">
          <button type="button" className="xfer-btn xfer-btn-ghost" onClick={onClose}>
            取消
          </button>
          <button type="button" className="xfer-btn xfer-btn-primary" onClick={() => void handleExport()}>
            <FileJsonIcon />
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
    const { result } = phase;
    return (
      <div className="xfer-page">
        <div className="xfer-card xfer-result">
          <div className="xfer-status-mark ok">
            <CheckIcon />
          </div>
          <h2 className="xfer-result-title">导出完成</h2>
          <span className="xfer-result-path">{result.path}</span>
          <span className="xfer-muted">
            {result.avatar_saved ? "头像文件已配套保存" : "未保存头像文件"}
          </span>
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
