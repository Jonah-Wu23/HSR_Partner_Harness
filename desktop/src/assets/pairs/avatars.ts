import { useEffect, useState } from "react";

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

/**
 * 角色卡头像懒加载：按卡 id + 头像版本取一次数据地址，同一版本在内存缓存里只请求一次
 * （缓存由 actions.fetchCardAvatar 维护）。
 *
 * 卡没有头像或读取失败时返回 null，调用方沿用几何占位；失败原文由请求层提示。
 * cardId 为 null（内置搭档）时不发请求。
 */
export function useCardAvatar(
  fetchAvatar: (cardId: string, avatarVersion: string | null) => Promise<string | null>,
  cardId: string | null,
  avatarVersion: string | null,
): string | null {
  const [loaded, setLoaded] = useState<{ key: string; url: string | null } | null>(null);
  const key = cardId === null ? null : `${cardId}\u0000${avatarVersion ?? ""}`;
  useEffect(() => {
    if (key === null || cardId === null) return;
    let cancelled = false;
    fetchAvatar(cardId, avatarVersion)
      .then((url) => {
        if (!cancelled) setLoaded({ key, url });
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoaded({ key, url: null });
        console.warn("[card.avatar] 读取头像失败", error);
      });
    return () => {
      cancelled = true;
    };
  }, [key, cardId, avatarVersion, fetchAvatar]);
  return key !== null && loaded?.key === key ? loaded.url : null;
}
