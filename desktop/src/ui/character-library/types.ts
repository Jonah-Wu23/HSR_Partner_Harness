import type { CharacterCardSummaryView } from "../../contracts/view-models";

export type SourceFilter =
  | "all"
  | "builtin"
  | "user_created"
  | "imported"
  | "draft"
  | "archived";

export type VoiceStateFilter =
  | "all"
  | "voice_ready"
  | "voice_unconfigured"
  | "voice_creating"
  | "voice_failed";

export interface CharacterFilterState {
  search: string;
  source: SourceFilter;
  voice: VoiceStateFilter;
}

export function filterCharacterCards(
  cards: CharacterCardSummaryView[],
  filters: CharacterFilterState,
): CharacterCardSummaryView[] {
  return cards.filter((card) => {
    // 归档过滤：除「已归档」筛选外，默认排除已归档卡片
    if (filters.source === "archived") {
      if (!card.archived) return false;
    } else {
      if (card.archived) return false;
    }

    // 来源筛选
    if (filters.source === "builtin" && card.source !== "builtin") {
      return false;
    }
    if (filters.source === "user_created" && card.source !== "user_created") {
      return false;
    }
    if (
      filters.source === "imported" &&
      card.source !== "imported_json" &&
      card.source !== "imported_png"
    ) {
      return false;
    }
    if (filters.source === "draft" && card.state !== "draft") {
      return false;
    }

    // 音色状态筛选
    if (filters.voice !== "all" && card.voiceState !== filters.voice) {
      return false;
    }

    // 关键字搜索
    if (filters.search.trim() !== "") {
      const keyword = filters.search.trim().toLowerCase();
      if (!card.name.toLowerCase().includes(keyword)) {
        return false;
      }
    }

    return true;
  });
}

export function formatUpdatedAt(dateStr: string): string {
  if (!dateStr || dateStr.trim() === "") return "—";
  try {
    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return dateStr;
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${month}-${day} ${hours}:${minutes}`;
  } catch {
    return dateStr;
  }
}
