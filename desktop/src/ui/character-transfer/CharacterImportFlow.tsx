import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { CardImportPreviewPayload, CardImportJsonResult } from "../../contracts/protocol";
import type { DesktopBackend } from "../../services/backend";
import { CompatReportView } from "./CompatReportView";
import {
  AlertCircleIcon,
  CheckIcon,
  FileImageIcon,
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

type ImportFormat = "json" | "png";

type ImportPhase =
  | { kind: "idle" }
  | { kind: "peeking"; path: string }
  | { kind: "preview"; path: string; preview: CardImportPreviewPayload; format: ImportFormat }
  | { kind: "importing"; path: string; asDuplicate: boolean; format: ImportFormat }
  | { kind: "success"; result: CardImportJsonResult }
  | { kind: "error"; path: string | null; title: string; message: string };

const CARD_FILE_FILTERS = [
  { name: "角色卡（JSON / PNG）", extensions: ["json", "png"] },
  { name: "Character Card JSON", extensions: ["json"] },
  { name: "PNG Character Card", extensions: ["png"] },
];

function reportSummary(report: CardImportPreviewPayload["report"]): string {
  const parts: string[] = [];
  if (report.applied.length) parts.push(`已应用 ${report.applied.length} 项`);
  if (report.preserved.length) parts.push(`已保留 ${report.preserved.length} 项`);
  if (report.not_executed.length) parts.push(`未执行 ${report.not_executed.length} 项`);
  if (report.normalized_from_root.length) parts.push(`根级回退 ${report.normalized_from_root.length} 项`);
  if (report.warnings.length) parts.push(`警告 ${report.warnings.length} 项`);
  if (report.errors.length) parts.push(`错误 ${report.errors.length} 项`);
  return parts.length ? parts.join(" · ") : "无兼容报告项";
}

/** 解析拖放事件携带的路径：一次只接受一个角色卡文件。 */
export function resolveDroppedCardPath(
  paths: readonly string[],
): { ok: true; path: string } | { ok: false; reason: string } {
  if (paths.length === 0) {
    return { ok: false, reason: "拖放事件未携带文件路径。" };
  }
  if (paths.length > 1) {
    return {
      ok: false,
      reason: `一次只能导入一个角色卡文件，本次拖放了 ${paths.length} 个文件。`,
    };
  }
  return { ok: true, path: paths[0] };
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** §1.1：新后端 JSON/PNG 两分支恒返回 format；缺省 json 是协议推导
    （支持 peek_import 但不回 format 的旧后端只能解析 JSON，PNG 会在 peek 报错）。 */
function resolveFormat(preview: CardImportPreviewPayload): ImportFormat {
  return preview.format ?? "json";
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
  // StrictMode 开发模式会 mount→cleanup→再 mount：effect 体必须重新置 true，
  // 否则 cleanup 后 mountedRef 永久 false，异步阶段的 setPhase 全被守卫吞掉。
  const mountedRef = useRef(true);
  const phaseRef = useRef(phase);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  const handleError = useCallback((error: unknown, path: string | null, title: string) => {
    const err = error instanceof Error ? error : new Error(String(error));
    const code = (err as Error & { code?: string }).code;
    const message = code ? `${code}：${err.message}` : err.message;
    if (mountedRef.current) {
      setPhase({ kind: "error", path, title, message });
    }
  }, []);

  const startPeek = useCallback(
    async (path: string) => {
      setAsDuplicate(false);
      setPhase({ kind: "peeking", path });
      try {
        const result = await actions.cardPeekImport(path);
        if (mountedRef.current) {
          setPhase({
            kind: "preview",
            path,
            preview: result.preview,
            format: resolveFormat(result.preview),
          });
        }
      } catch (error) {
        handleError(error, path, "解析失败");
      }
    },
    [actions, handleError],
  );

  const handlePickFile = useCallback(async () => {
    if (!backend) {
      handleError(
        new Error("当前环境未提供桌面后端，无法打开文件对话框。请在 Tauri 桌面端重试。"),
        null,
        "环境不可用",
      );
      return;
    }
    let path: string | null;
    try {
      path = await backend.pickFile({ title: "选择角色卡文件", filters: CARD_FILE_FILTERS });
    } catch (error) {
      handleError(error, null, "打开文件对话框失败");
      return;
    }
    if (!path) return;
    void startPeek(path);
  }, [backend, startPeek, handleError]);

  const handleImport = useCallback(async () => {
    if (phase.kind !== "preview") return;
    const { path, format } = phase;
    setPhase({ kind: "importing", path, asDuplicate, format });
    try {
      // 导入分派跟随 peek 的 format（后端按文件签名分派，不信任扩展名）
      const result =
        format === "png"
          ? await actions.cardImportPng(path, asDuplicate)
          : await actions.cardImportJson(path, asDuplicate);
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
    void startPeek(path);
  }, [phase, startPeek]);

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
      // 浏览器 File 对象没有绝对路径，契约只接收 path；Tauri 桌面端拖拽
      // 走下方 onDragDropEvent 订阅（携带绝对路径），这里只兜浏览器开发模式。
      if (e.dataTransfer.files.length > 0) {
        handleError(
          new Error("浏览器环境无法从拖放文件获取绝对路径，请使用「选择文件」按钮；桌面端可直接拖入文件。"),
          null,
          "不支持此操作",
        );
      }
    },
    [handleError],
  );

  // Tauri 拖拽事件（dragDropEnabled 默认开启，DOM drop 不携带路径）：
  // enter/over 点亮拖放区，drop 取绝对路径进入解析；导入进行中忽略新拖放。
  useEffect(() => {
    if (!isTauriRuntime()) return;
    let cancelled = false;
    let unlisten: (() => void) | null = null;
    void import("@tauri-apps/api/webview")
      .then(({ getCurrentWebview }) =>
        getCurrentWebview().onDragDropEvent((event) => {
          const payload = event.payload;
          if (payload.type === "enter" || payload.type === "over") {
            setDragOver(true);
            return;
          }
          setDragOver(false);
          if (payload.type !== "drop") return;
          if (!mountedRef.current) return;
          if (phaseRef.current.kind === "importing") return;
          const resolved = resolveDroppedCardPath(payload.paths);
          if (!resolved.ok) {
            handleError(new Error(resolved.reason), null, "不支持此操作");
            return;
          }
          void startPeek(resolved.path);
        }),
      )
      .then((fn) => {
        if (cancelled) {
          fn?.();
          return;
        }
        unlisten = fn ?? null;
      })
      .catch((error) => {
        // 订阅失败如实记录：拖放不可用不阻断「选择文件」路径，也不伪造成功
        console.error("拖拽事件订阅失败：", error);
      });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [startPeek, handleError]);

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
          <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>
            将角色卡 JSON / PNG 拖到这里
          </div>
          <p className="xfer-muted">
            支持 Character Card v2 / v3 JSON 与 v3 PNG（单文件、头像内嵌），解析在本地完成。
          </p>
          <p className="xfer-muted" style={{ fontSize: "12px" }}>
            浏览器开发模式请使用下方按钮；桌面端可直接拖入文件。
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
    const { preview, path, format } = phase;
    const isPng = format === "png";
    return (
      <div className="xfer-page">
        <div className="xfer-title-row">
          <h2 className="xfer-title">导入预览</h2>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <span className="xfer-pill char-pill char-pill-accent">{isPng ? "PNG 卡" : "JSON 卡"}</span>
            <span className="xfer-pill char-pill char-pill-accent">{preview.spec_version}</span>
          </div>
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
                {isPng && (
                  <div className="xfer-stat">
                    <span className="xfer-stat-value">
                      {preview.avatar_width != null && preview.avatar_height != null
                        ? `${preview.avatar_width} × ${preview.avatar_height}`
                        : "未能解析"}
                    </span>
                    <span className="xfer-stat-label">头像尺寸（像素）</span>
                  </div>
                )}
              </div>
              {isPng && (
                <div className="xfer-note-row">
                  <FileImageIcon />
                  <span className="xfer-muted">
                    PNG 字节即头像：导入时该文件的图像字节将直接存为此卡头像，无需另配头像文件。
                  </span>
                </div>
              )}
            </div>
            <CompatReportView report={preview.report} title="兼容报告" />
          </div>
          <div className="xfer-muted" style={{ fontSize: "12px" }}>
            摘要：{reportSummary(preview.report)}
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
            {phase.kind === "importing" ? `正在写入${phase.asDuplicate ? "副本" : ""}角色…` : ""}
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
