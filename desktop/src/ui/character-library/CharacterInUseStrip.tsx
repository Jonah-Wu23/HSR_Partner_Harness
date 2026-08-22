import type { CharacterCardSummaryView } from "../../contracts/view-models";
import { formatUpdatedAt } from "./types";

interface CharacterInUseStripProps {
  card: CharacterCardSummaryView;
  onEdit: (cardId: string) => void;
}

export function CharacterInUseStrip({ card, onEdit }: CharacterInUseStripProps) {
  const firstChar = card.name.trim().charAt(0) || "角";

  let voiceDotClass = "char-dot-muted";
  let voiceText = "音色未配置";
  if (card.voiceState === "voice_ready") {
    voiceDotClass = "char-dot-ok";
    voiceText = "音色已绑定";
  } else if (card.voiceState === "voice_creating") {
    voiceDotClass = "char-dot-progress";
    voiceText = "音色创建中";
  } else if (card.voiceState === "voice_failed") {
    voiceDotClass = "char-dot-danger";
    voiceText = "音色创建失败";
  }

  const updatedTimeText = formatUpdatedAt(card.updatedAt);

  return (
    <section className="char-in-use-strip" data-testid="in-use-strip">
      <div className={`char-avatar ${card.hasAvatar ? "avatar-geo" : ""}`}>
        {firstChar}
      </div>
      <div className="char-in-use-info">
        <div className="char-in-use-title-row">
          <span className="char-in-use-name">{card.name}</span>
          <span className="char-pill char-pill-accent">使用中</span>
          <span className="char-pill">
            <span className={`char-dot ${voiceDotClass}`} />
            {voiceText}
          </span>
        </div>
        <p className="char-in-use-sub">
          当前会话角色
          {updatedTimeText !== "—" ? ` · 最近编辑 ${updatedTimeText}` : ""}
        </p>
      </div>
      <button
        type="button"
        className="char-btn char-btn-ghost"
        onClick={() => onEdit(card.cardId)}
      >
        继续编辑
      </button>
    </section>
  );
}
