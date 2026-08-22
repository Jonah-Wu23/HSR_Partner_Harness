/** V0.3.3 角色卡与远程配对样例数据（契约形状见 contracts/protocol.ts，
    与 Sidecar card.* / remote.* 命令的真实返回一致）。
    仅供 mock 后端与组件测试使用；生产页面默认接真实 action，
    样例数据不得出现在生产渲染路径。 */
import type { CardSummaryPayload, RemoteDevice } from "../contracts/protocol";

/** 内置角色只读摘要（对应 sidecar _builtin_card_summaries：pair 目录角色）。 */
export const MOCK_BUILTIN_CARDS: CardSummaryPayload[] = [
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

/** 用户卡样例：草稿 / 已保存（音色已绑定+使用中）/ 导入失败 / 已导入（已归档）。 */
export const MOCK_USER_CARDS: CardSummaryPayload[] = [
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
    source: "imported_json",
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
    source: "imported_png",
    updated_at: "2026-08-16T12:00:00+00:00",
    has_avatar: true,
    voice_state: "voice_failed",
    active: false,
    read_only: false,
  },
];

/** 归档集合：card.list(include_archived=false) 会排除这些 id。 */
export const MOCK_ARCHIVED_CARD_IDS: readonly string[] = ["card-imported-004"];

export const MOCK_REMOTE_DEVICES: RemoteDevice[] = [
  {
    device_name: "小米 14",
    issued_at: "2026-08-19T09:00:00+00:00",
    last_used_at: "2026-08-19T12:30:00+00:00",
    revoked: false,
  },
];

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
