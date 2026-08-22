import { useEffect } from "react";

interface CharacterNoticeModalProps {
  title: string;
  message: string;
  open: boolean;
  onClose: () => void;
}

export function CharacterNoticeModal({
  title,
  message,
  open,
  onClose,
}: CharacterNoticeModalProps) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="char-modal-mask"
      role="dialog"
      aria-modal="true"
      aria-labelledby="notice-modal-title"
      data-testid="notice-modal"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="char-modal-box">
        <h3 id="notice-modal-title" className="char-modal-title">
          {title}
        </h3>
        <p className="char-modal-desc">{message}</p>
        <div className="char-modal-actions">
          <button
            type="button"
            className="char-btn char-btn-primary"
            onClick={onClose}
          >
            知道了
          </button>
        </div>
      </div>
    </div>
  );
}
