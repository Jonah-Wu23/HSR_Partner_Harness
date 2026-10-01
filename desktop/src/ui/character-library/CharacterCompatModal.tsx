import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { CompatReportPayload } from "../../contracts/protocol";
import { CompatReportView } from "../character-transfer/CompatReportView";
import { CloseIcon, CompatCheckIcon, RefreshIcon } from "./CharacterIcons";

interface CharacterCompatModalProps {
  cardId: string;
  cardName: string;
  actions: HarnessActions;
  onClose: () => void;
}

type CompatPhase =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready" };

/**
 * 角色详情「兼容性」弹窗：随时回看已入库卡的兼容报告。
 * 报告来自 card.get 的 compat_report，由后端对存储的卡跑导入时同一套静态扫描得到；
 * 加载失败显示原始错误。
 */
export function CharacterCompatModal({ cardId, cardName, actions, onClose }: CharacterCompatModalProps) {
  const [phase, setPhase] = useState<CompatPhase>({ kind: "loading" });
  const [report, setReport] = useState<CompatReportPayload | null>(null);
  // StrictMode 开发模式会 mount、cleanup 再 mount，effect 体里重新置 true。
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const load = useCallback(async () => {
    setPhase({ kind: "loading" });
    setReport(null);
    try {
      const result = await actions.cardGet(cardId);
      if (!mountedRef.current) return;
      setReport(result.compat_report);
      setPhase({ kind: "ready" });
    } catch (error) {
      if (!mountedRef.current) return;
      const err = error instanceof Error ? error : new Error(String(error));
      const code = (err as Error & { code?: string }).code;
      setPhase({ kind: "error", message: code ? `${code}：${err.message}` : err.message });
    }
  }, [actions, cardId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div
      className="char-modal-mask"
      role="dialog"
      aria-modal="true"
      aria-labelledby="compat-modal-title"
      data-testid="compat-modal"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="char-modal-box char-compat-modal-box">
        <div className="char-compat-modal-head">
          <h3 id="compat-modal-title" className="char-modal-title">
            <CompatCheckIcon />
            兼容性 · {cardName}
          </h3>
          <button
            type="button"
            className="char-icon-btn"
            aria-label="关闭兼容性视图"
            data-testid="compat-modal-close"
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>

        {phase.kind === "loading" ? (
          <p className="char-modal-desc" role="status" data-testid="compat-modal-loading">
            正在读取角色卡数据…
          </p>
        ) : null}

        {phase.kind === "error" ? (
          <div data-testid="compat-modal-error">
            <div className="char-error-banner" role="alert">
              <div className="char-error-text">
                <span>兼容性视图加载失败：{phase.message}</span>
              </div>
            </div>
            <div className="char-modal-actions">
              <button
                type="button"
                className="char-btn char-btn-secondary"
                data-testid="compat-modal-retry"
                onClick={() => void load()}
              >
                <RefreshIcon />
                <span>重试</span>
              </button>
              <button type="button" className="char-btn char-btn-ghost" onClick={onClose}>
                关闭
              </button>
            </div>
          </div>
        ) : null}

        {phase.kind === "ready" && report ? (
          <>
            <p className="char-modal-desc char-compat-modal-note">
              以下按当前保存的卡内容重新扫描得到。
            </p>
            <div className="char-compat-modal-body" data-testid="compat-modal-report">
              <CompatReportView report={report} compact />
            </div>
            <div className="char-modal-actions">
              <button type="button" className="char-btn char-btn-primary" onClick={onClose}>
                知道了
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
