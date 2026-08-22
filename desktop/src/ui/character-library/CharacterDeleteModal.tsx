import { useEffect } from "react";
import type { CharacterCardSummaryView } from "../../contracts/view-models";

interface CharacterDeleteModalProps {
  card: CharacterCardSummaryView | null;
  onConfirm: (cardId: string) => void;
  onClose: () => void;
}

export function CharacterDeleteModal({
  card,
  onConfirm,
  onClose,
}: CharacterDeleteModalProps) {
  useEffect(() => {
    if (!card) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [card, onClose]);

  if (!card) return null;

  return (
    <div
      className="char-modal-mask"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-modal-title"
      data-testid="delete-modal"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="char-modal-box">
        <h3 id="delete-modal-title" className="char-modal-title">
          删除「{card.name}」？
        </h3>
        <p className="char-modal-desc">
          角色的全部字段、世界书条目与头像将被移除，且无法恢复。已绑定的音色会一并解除绑定。
        </p>
        <div className="char-modal-actions">
          <button
            type="button"
            className="char-btn char-btn-secondary"
            onClick={onClose}
          >
            取消
          </button>
          <button
            type="button"
            className="char-btn char-btn-danger"
            onClick={() => {
              onConfirm(card.cardId);
              onClose();
            }}
          >
            确认删除
          </button>
        </div>
      </div>
    </div>
  );
}
