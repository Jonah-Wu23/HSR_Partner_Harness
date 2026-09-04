import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import { deriveCompatViewFromCard } from "../character-transfer/compatView";
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

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * 角色详情「兼容性」弹窗（V6 收尾）：随时回看导入后卡的兼容性视图。
 * 数据用 deriveCompatViewFromCard 从 card.get 返回的完整 v3 JSON 静态派生；
 * 派生边界如实标注——已应用/根级回退等导入时事实不在此还原，导入报告才是权威。
 * 加载失败如实呈现原始错误，不伪造报告。
 */
export function CharacterCompatModal({ cardId, cardName, actions, onClose }: CharacterCompatModalProps) {
  const [phase, setPhase] = useState<CompatPhase>({ kind: "loading" });
  const [report, setReport] = useState<ReturnType<typeof deriveCompatViewFromCard> | null>(null);
  // StrictMode 开发模式 mount→cleanup→再 mount：effect 体必须重新置 true，
  // 否则 cleanup 后 mountedRef 永久 false，异步 setPhase 全被守卫吞掉。
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
      if (!isPlainObject(result?.card)) {
        setPhase({
          kind: "error",
          message: "card.get 返回数据缺少完整卡 JSON（协议不一致），无法派生兼容性视图。",
        });
        return;
      }
      setReport(deriveCompatViewFromCard(result.card));
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
              以下按当前卡内容静态派生：存而不运行项与越界警告随时可回看；
              已应用、根级回退等导入时的事实以导入当时的报告为准，本视图不做还原。
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
