/** 角色卡与远程配对样例数据，形状与 Sidecar card.* / remote.* 命令的返回一致，
    供 mock 后端与组件测试使用。归档状态由 mock 后端的归档集合给出。 */
import type { CardSummaryPayload, RemoteDevice } from "../contracts/protocol";

export type MockCardSummary = Omit<CardSummaryPayload, "archived">;

/** 内置角色只读摘要（对应 sidecar _builtin_card_summaries：pair 目录角色）。 */
export const MOCK_BUILTIN_CARDS: MockCardSummary[] = [
  {
    card_id: "builtin:phainon",
    name: "白厄",
    state: "saved",
    source: "builtin",
    updated_at: "",
    has_avatar: false,
    voice_state: "voice_ready",
    active: false,
    read_only: true,
  },
  {
    card_id: "builtin:firefly",
    name: "流萤",
    state: "saved",
    source: "builtin",
    updated_at: "",
    has_avatar: false,
    voice_state: "voice_unconfigured",
    active: false,
    read_only: true,
  },
  {
    card_id: "builtin:march7",
    name: "三月七",
    state: "saved",
    source: "builtin",
    updated_at: "",
    has_avatar: false,
    voice_state: "voice_unconfigured",
    active: false,
    read_only: true,
  },
];

/** 用户卡样例：草稿、已保存（音色已绑定且使用中）、导入失败、已导入（已归档）。 */
export const MOCK_USER_CARDS: MockCardSummary[] = [
  {
    card_id: "card-draft-001",
    name: "新角色草稿",
    state: "draft",
    source: "user_created",
    updated_at: "2026-08-19T10:00:00+00:00",
    has_avatar: false,
    voice_state: "voice_unconfigured",
    active: false,
    read_only: false,
  },
  {
    card_id: "card-saved-002",
    name: "卡芙卡",
    state: "saved",
    source: "user_created",
    updated_at: "2026-08-18T21:40:00+00:00",
    has_avatar: true,
    voice_state: "voice_ready",
    active: true,
    read_only: false,
  },
  {
    card_id: "card-invalid-003",
    name: "（导入失败的角色卡）",
    state: "invalid",
    source: "tavern_import",
    updated_at: "2026-08-17T08:00:00+00:00",
    has_avatar: false,
    voice_state: "voice_unconfigured",
    active: false,
    read_only: false,
  },
  {
    card_id: "card-imported-004",
    name: "砂金",
    state: "imported",
    source: "tavern_import",
    updated_at: "2026-08-16T12:00:00+00:00",
    has_avatar: true,
    voice_state: "voice_failed",
    active: false,
    read_only: false,
  },
];

/** 初始归档集合：card.list(include_archived=false) 会排除这些 id。 */
export const MOCK_ARCHIVED_CARD_IDS: readonly string[] = ["card-imported-004"];

/** 到期时间取签发后 30 天与最近使用后 7 天中较早的一个。 */
export const MOCK_REMOTE_DEVICES: RemoteDevice[] = [
  {
    device_name: "小米 14",
    issued_at: "2026-08-19T09:00:00+00:00",
    last_used_at: "2026-08-19T12:30:00+00:00",
    expires_at: "2026-08-26T12:30:00+00:00",
    revoked: false,
  },
];

/** 内置角色的提示词路径（config/pairs 中各搭档的 character.prompt）。 */
const MOCK_BUILTIN_PROMPTS: Record<string, string> = {
  "builtin:phainon": "config/prompts/characters/phainon.md",
  "builtin:firefly": "config/prompts/characters/firefly.md",
  "builtin:march7": "config/prompts/characters/march7.md",
};

/** 内置角色的只读整卡（对应 Sidecar _builtin_card：由搭档目录生成，不入库）。 */
export function mockBuiltinCardPayload(cardId: string, name: string): Record<string, unknown> {
  const payload = mockCardPayload(name);
  return {
    ...payload,
    data: {
      ...(payload.data as Record<string, unknown>),
      creator: "HSR Partner Harness",
      tags: ["builtin"],
      creator_notes: `内置角色，提示词来源：${MOCK_BUILTIN_PROMPTS[cardId]}`,
    },
  };
}

/** card.get 返回的最小有效 v3 JSON（未知扩展原样保留在 data.extensions）。 */
export function mockCardPayload(name: string): Record<string, unknown> {
  return {
    spec: "chara_card_v3",
    spec_version: "3.0",
    data: {
      name,
      description: "",
      personality: "",
      scenario: "",
      first_mes: "",
      mes_example: "",
      creator_notes: "",
      system_prompt: "",
      post_history_instructions: "",
      tags: [],
      creator: "",
      character_version: "1",
      alternate_greetings: [],
      extensions: {},
    },
  };
}
