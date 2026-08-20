import type { SaveStatus } from "./types";

interface SaveStatusBadgeProps {
  status: SaveStatus;
  lastSavedTime: string | null;
  errorMessage: string | null;
}

export function SaveStatusBadge({ status, lastSavedTime, errorMessage }: SaveStatusBadgeProps) {
  if (status === "unsaved") {
    return (
      <span className="char-create-save-badge" data-testid="save-status-unsaved">
        <span className="char-create-dot warn" aria-hidden="true" />
        <span style={{ color: "var(--warning, #CA8A04)" }}>未保存更改</span>
      </span>
    );
  }

  if (status === "saving") {
    return (
      <span className="char-create-save-badge" data-testid="save-status-saving">
        <span className="char-create-dot pulse" aria-hidden="true" />
        <span style={{ color: "var(--gold, #B08D57)" }}>保存中…</span>
      </span>
    );
  }

  if (status === "saved" && lastSavedTime) {
    return (
      <span className="char-create-save-badge" data-testid="save-status-saved">
        <span className="char-create-dot ok" aria-hidden="true" />
        <span style={{ color: "var(--text-secondary, #9AA3B2)" }}>
          已保存 {lastSavedTime}
        </span>
      </span>
    );
  }

  if (status === "error") {
    return (
      <span className="char-create-save-badge" data-testid="save-status-error" title={errorMessage ?? undefined}>
        <span className="char-create-dot error" aria-hidden="true" />
        <span style={{ color: "var(--danger, #DC2626)" }}>保存失败</span>
      </span>
    );
  }

  return (
    <span className="char-create-save-badge" data-testid="save-status-idle">
      <span className="char-create-dot" style={{ background: "var(--text-muted, #6B7686)" }} aria-hidden="true" />
      <span style={{ color: "var(--text-muted, #6B7686)" }}>草稿就绪</span>
    </span>
  );
}
