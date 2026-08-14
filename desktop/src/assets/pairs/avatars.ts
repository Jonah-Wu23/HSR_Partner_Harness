import phainonCharacter from "./phainon_ancient_machine/character.png";
import phainonAssistant from "./phainon_ancient_machine/assistant.png";
import fireflyCharacter from "./firefly_sam/character.png";
import fireflyAssistant from "./firefly_sam/assistant.png";
import march7Character from "./march7_fourth_mirror/character.png";
import march7Assistant from "./march7_fourth_mirror/assistant.png";

export interface PairAvatars {
  character: string;
  assistant: string;
}

export const PAIR_AVATARS: Record<string, PairAvatars> = {
  phainon_ancient_machine: {
    character: phainonCharacter,
    assistant: phainonAssistant,
  },
  firefly_sam: {
    character: fireflyCharacter,
    assistant: fireflyAssistant,
  },
  march7_fourth_mirror: {
    character: march7Character,
    assistant: march7Assistant,
  },
};

export function getPairAvatars(pairId: string): PairAvatars | null {
  return PAIR_AVATARS[pairId] ?? null;
}
