import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { CardImportPreviewPayload, CardImportJsonResult, CompatReportPayload } from "../../contracts/protocol";
import type { DesktopBackend } from "../../services/backend";
import {
  AlertCircleIcon,
  AlertTriangleIcon,
  CheckIcon,
  FileJsonIcon,
  RetryIcon,
  UploadIcon,
} from "./CharacterTransferIcons";

import "./character-transfer.css";

interface CharacterImportFlowProps {
  backend?: DesktopBackend;
  actions: HarnessActions;
  onClose: () => void;
  onSuccess?: () => void;
}

type ImportPhase =
  | { kind: "idle" }
  | { kind: "peeking"; path: string }
  | { kind: "preview"; path: string; preview: CardImportPreviewPayload }
  | { kind: "importing"; path: string; asDuplicate: boolean }
  | { kind: "success"; result: CardImportJsonResult }
  | { kind: "error"; path: string | null; title: string; message: string };

const JSON_FILTER = { name: "Character Card JSON", extensions: ["json"] };

function reportSummary(report: CompatReportPayload): string {
  const parts: string[] = [];
  if (report.applied.length) parts.push(`已应用 ${report.applied.length} 项`);
  if (report.preserved.length) parts.push(`已保留 ${report.preserved.length} 项`);
  if (report.not_executed.length) parts.push(`未执行 ${report.not_executed.length} 项`);
  if (report.warnings.length) parts.push(`警告 ${report.warnings.length} 项`);
  if (report.errors.length) parts.push(`错误 ${report.errors.length} 项`);
  return parts.length ? parts.join(" · ") : "无兼容报告项";
}

function formatReportList(items: string[]): string {
  if (!items.length) return "";
  return items.slice(0, 8).join("\n") + (items.length > 8 ? `\n…等 ${items.length} 项` : "");
}

export function CharacterImportFlow({
  backend,
  actions,
  onClose,
  onSuccess,
}: CharacterImportFlowProps) {
  const [phase, setPhase] = useState<ImportPhase>({ kind: "idle" });
  const [asDuplicate, setAsDuplicate] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleError = useCallback((error: unknown, path: string | null, title: string) => {
    const err = error instanceof Error ? error : new Error(String(error));
    const code = (err as Error & { code?: string }).code;
    const message = code ? `${code}：${err.message}` : err.message;
    if (mountedRef.current) {
      setPhase({ kind: "error", path, title, message });
    }
  }, []);

  const handlePickFile = useCallback(async () => {
    if (!backend) {
      handleError(
        new Error("当前环境未提供桌面后端，无法打开文件对话框。请在 Tauri 桌面端重试。"),
        null,
        "环境不可用",
      );
      return;
    }
    const path = await backend.pickFile({ title: "选择角色卡 JSON", filters: [JSON_FILTER] });
    if (!path) return;
    setAsDuplicate(false);
    setPhase({ kind: "peeking", path });
    try {
      const result = await actions.cardPeekImportJson(path);
      if (mountedRef.current) {
        setPhase({ kind: "preview", path, preview: result.preview });
      }
    } catch (error) {
      handleError(error, path, "解析失败");
    }
  }, [backend, actions, handleError]);

  const handleImport = useCallback(async () => {
    if (phase.kind !== "preview") return;
    const { path } = phase;
    setPhase({ kind: "importing", path, asDuplicate });
    try {
      const result = await actions.cardImportJson(path, asDuplicate);
      if (mountedRef.current) {
        setPhase({ kind: "success", result });
        onSuccess?.();
      }
    } catch (error) {
      handleError(error, path, "导入失败");
    }
  }, [phase, asDuplicate, actions, onSuccess, handleError]);

  const handleRetry = useCallback(() => {
    if (phase.kind !== "error") return;
    const { path } = phase;
    if (!path) {
      setPhase({ kind: "idle" });
      return;
    }
    setAsDuplicate(false);
    setPhase({ kind: "peeking", path });
    actions
      .cardPeekImportJson(path)
      .then((result) => {
        if (mountedRef.current) {
          setPhase({ kind: "preview", path, preview: result.preview });
        }
      })
      .catch((error) => handleError(error, path, "解析失败"));
  }, [phase, actions, handleError]);

  const handleContinue = useCallback(() => {
    setAsDuplicate(false);
    setPhase({ kind: "idle" });
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      // 浏览器 File 对象没有绝对路径，契约只接收 path；Tauri 拖拽事件未接入。
      // 这里不做实际导入，提示用户使用选择文件按钮。
      if (e.dataTransfer.files.length > 0) {
        handleError(
          new Error("浏览器环境无法从拖放文件获取绝对路径，请使用「选择文件」按钮。"),
          null,
          "不支持此操作",
        );
      }
    },
    [handleError],
  );

  const renderIdle = () => (
    <div className="xfer-page">
      <div className="xfer-title-row">
        <h2 className="xfer-title">导入角色</h2>
      </div>
      <div
        className={`xfer-dropzone ${dragOver ? "dragover" : ""}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        aria-label="选择角色卡文件"
        onClick={handlePickFile}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            void handlePickFile();
          }
        }}
      >
        <div className="xfer-dropzone-icon">
          <UploadIcon />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px", alignItems: "center" }}>
          <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>将角色卡 JSON 拖到这里</div>
          <p className="xfer-muted">支持 Character Card v2 / v3 JSON，解析在本地完成。</p>
          <p className="xfer-muted" style={{ fontSize: "12px" }}>
            浏览器开发模式请使用下方按钮；桌面端拖拽需 Tauri 运行时支持。
          </p>
        </div>
        <button type="button" className="xfer-btn xfer-btn-secondary" onClick={(e) => { e.stopPropagation(); void handlePickFile(); }}>
          <FileJsonIcon />
          选择文件
        </button>
      </div>
    </div>
  );

  const renderPeeking = () => (
    <div className="xfer-page">
      <div className="xfer-title-row">
        <h2 className="xfer-title">正在解析…</h2>
      </div>
      <div className="xfer-card xfer-card-subtle">
        <div className="xfer-muted">{phase.kind === "peeking" ? phase.path : ""}</div>
        <div style={{ display: "flex", alignItems: "flex-start", gap: "16px" }}>
          <div className="char-avatar avatar-lg xfer-skeleton" style={{ color: "transparent" }}>
            头
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "10px" }}>
            <div className="xfer-skeleton xfer-skeleton-line" style={{ width: "32%", height: "18px" }} />
            <div className="xfer-skeleton xfer-skeleton-line" style={{ width: "20%" }} />
            <div className="xfer-skeleton xfer-skeleton-line" style={{ width: "70%" }} />
            <div className="xfer-skeleton xfer-skeleton-line" style={{ width: "55%" }} />
          </div>
        </div>
      </div>
    </div>
  );

  const renderPreview = () => {
    if (phase.kind !== "preview") return null;
    const { preview, path } = phase;
    return (
      <div className="xfer-page">
        <div className="xfer-title-row">
          <h2 className="xfer-title">导入预览</h2>
          <span className="xfer-pill char-pill char-pill-accent">{preview.spec_version}</span>
        </div>
        <div className="xfer-card xfer-card-subtle">
          <div className="xfer-preview-grid">
            <div className="xfer-preview-main">
              <div style={{ display: "flex", alignItems: "flex-start", gap: "16px" }}>
                <div className={`char-avatar avatar-lg ${preview.avatar_available ? "avatar-geo" : ""}`}>
                  {preview.avatar_available ? "图" : preview.name.trim().charAt(0) || "角"}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <span style={{ fontSize: "20px", fontWeight: 600, color: "var(--text-primary)" }}>
                      {preview.name}
                    </span>
                    <span className="char-pill char-pill-accent">Character Card v{preview.spec_version}</span>
                  </div>
                  <span className="xfer-meta">{path}</span>
                </div>
              </div>
              <div className="xfer-preview-stats">
                <div className="xfer-stat">
                  <span className="xfer-stat-value">{preview.greeting_count}</span>
                  <span className="xfer-stat-label">备选问候</span>
                </div>
                <div className="xfer-stat">
                  <span className="xfer-stat-value">{preview.world_book_entries}</span>
                  <span className="xfer-stat-label">世界书条目</span>
                </div>
                <div className="xfer-stat">
                  <span className="xfer-stat-value">{preview.tags.length}</span>
                  <span className="xfer-stat-label">标签</span>
                </div>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <div className="xfer-field">
                <label>兼容报告摘要</label>
                <div className="xfer-muted" style={{ fontSize: "12px" }}>
                  {reportSummary(preview.report)}
                </div>
              </div>
              {preview.report.applied.length > 0 && (
                <div className="xfer-report-section">
                  <label className="xfer-muted">已应用</label>
                  <pre className="xfer-report-list">{formatReportList(preview.report.applied)}</pre>
                </div>
              )}
              {preview.report.preserved.length > 0 && (
                <div className="xfer-report-section">
                  <label className="xfer-muted">已保留</label>
                  <pre className="xfer-report-list">{formatReportList(preview.report.preserved)}</pre>
                </div>
              )}
              {preview.report.not_executed.length > 0 && (
                <div className="xfer-report-section">
                  <label className="xfer-muted">未执行（原样保留）</label>
                  <pre className="xfer-report-list">{formatReportList(preview.report.not_executed)}</pre>
                </div>
              )}
              {preview.report.warnings.length > 0 && (
                <div className="xfer-report-section">
                  <label className="xfer-muted" style={{ color: "var(--warning)" }}>
                    警告
                  </label>
                  <pre className="xfer-report-list">{formatReportList(preview.report.warnings)}</pre>
                </div>
              )}
              {preview.report.errors.length > 0 && (
                <div className="xfer-report-section">
                  <label className="xfer-muted" style={{ color: "var(--danger)" }}>
                    错误
                  </label>
                  <pre className="xfer-report-list">{formatReportList(preview.report.errors)}</pre>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="xfer-card">
          <label className="xfer-checkbox-row">
            <input
              type="checkbox"
              checked={asDuplicate}
              onChange={(e) => setAsDuplicate(e.target.checked)}
              aria-label="作为副本导入"
            />
            <span>作为副本导入（名称追加「（副本）」，不覆盖现有角色）</span>
          </label>
        </div>
        <div className="xfer-actions">
          <button type="button" className="xfer-btn xfer-btn-ghost" onClick={onClose}>
            取消
          </button>
          <button type="button" className="xfer-btn xfer-btn-primary" onClick={() => void handleImport()}>
            <CheckIcon />
            确认导入
          </button>
        </div>
      </div>
    );
  };

  const renderImporting = () => (
    <div className="xfer-page">
      <div className="xfer-title-row">
        <h2 className="xfer-title">正在导入…</h2>
      </div>
      <div className="xfer-card xfer-card-subtle">
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span className="char-dot char-dot-progress" />
          <span className="xfer-muted">
            {phase.kind === "importing" ? `正在写入 ${phase.asDuplicate ? "副本" : ""}角色…` : ""}
          </span>
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
          <h2 className="xfer-result-title">导入完成</h2>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            <span style={{ fontSize: "18px", fontWeight: 600, color: "var(--text-primary)" }}>
              {result.name}
            </span>
            <span className="char-pill char-pill-ok">{result.state}</span>
          </div>
          <span className="xfer-result-path">已写入角色库</span>
          <div className="xfer-actions xfer-actions-center">
            <button type="button" className="xfer-btn xfer-btn-primary" onClick={onClose}>
              返回角色库
            </button>
            <button type="button" className="xfer-btn xfer-btn-ghost" onClick={handleContinue}>
              继续导入
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
          <p className="xfer-muted">文件未被导入，角色库未发生任何改动；修复后可重试。</p>
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
    case "idle":
      return renderIdle();
    case "peeking":
      return renderPeeking();
    case "preview":
      return renderPreview();
    case "importing":
      return renderImporting();
    case "success":
      return renderSuccess();
    case "error":
      return renderError();
  }
}
