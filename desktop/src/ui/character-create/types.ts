import type { CardAvatarPayload } from "../../contracts/protocol";

export interface CharacterFormData {
  name: string;
  description: string;
  tags: string[];
  personality: string;
  scenario: string;
  first_mes: string;
  mes_example: string;
  /** V0.3.5 高级字段：卡内系统提示。 */
  system_prompt: string;
  /** V0.3.5 高级字段：历史后指令。 */
  post_history_instructions: string;
  /** V0.3.5 高级字段：备选问候列表。 */
  alternate_greetings: string[];
  /** V0.3.5 高级字段：群组问候（单文本，标准字段）。 */
  group_only_greetings: string;
}

export type SaveStatus = "idle" | "unsaved" | "saving" | "saved" | "error";
export type PublishStatus = "idle" | "publishing" | "published" | "error";

export type CreateMode = "quick" | "advanced";

export const EMPTY_FORM_DATA: CharacterFormData = {
  name: "",
  description: "",
  tags: [],
  personality: "",
  scenario: "",
  first_mes: "",
  mes_example: "",
  system_prompt: "",
  post_history_instructions: "",
  alternate_greetings: [],
  group_only_greetings: "",
};

export const MAX_PERSONA_FIELD_LENGTH = 2000;
export const MAX_ADVANCED_TEXT_LENGTH = 8000;

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export function extractFormData(card: Record<string, unknown> | null): CharacterFormData {
  if (!card) {
    return { ...EMPTY_FORM_DATA };
  }
  const data = (card.data as Record<string, unknown>) ?? card;

  return {
    name: asString(data.name),
    description: asString(data.description),
    tags: asStringArray(data.tags),
    personality: asString(data.personality),
    scenario: asString(data.scenario),
    first_mes: asString(data.first_mes),
    mes_example: asString(data.mes_example),
    system_prompt: asString(data.system_prompt),
    post_history_instructions: asString(data.post_history_instructions),
    alternate_greetings: asStringArray(data.alternate_greetings),
    group_only_greetings: asString(
      Array.isArray(data.group_only_greetings) ? data.group_only_greetings.join("\n") : data.group_only_greetings,
    ),
  };
}

export function buildCardPayload(
  baseCard: Record<string, unknown> | null,
  formData: CharacterFormData,
): Record<string, unknown> {
  const existingData = (baseCard?.data as Record<string, unknown>) ?? {};
  return {
    spec: baseCard?.spec ?? "chara_card_v3",
    spec_version: baseCard?.spec_version ?? "3.0",
    ...baseCard,
    data: {
      creator_notes: "",
      creator: "",
      character_version: "1",
      extensions: {},
      ...existingData,
      name: formData.name.trim(),
      description: formData.description.trim(),
      tags: formData.tags,
      personality: formData.personality,
      scenario: formData.scenario,
      first_mes: formData.first_mes,
      mes_example: formData.mes_example,
      system_prompt: formData.system_prompt,
      post_history_instructions: formData.post_history_instructions,
      alternate_greetings: formData.alternate_greetings,
      group_only_greetings: formData.group_only_greetings
        ? formData.group_only_greetings.split("\n").map((line) => line.trim()).filter(Boolean)
        : [],
    },
  };
}

/** 将 card.get 返回的 avatar 载荷转成可展示的数据 URI。 */
export function avatarDataUri(avatar: CardAvatarPayload | null | undefined): string | null {
  if (!avatar?.data_base64 || !avatar.mime_type) return null;
  return `data:${avatar.mime_type};base64,${avatar.data_base64}`;
}

/** 判断角色卡是否已发布（saved / imported 视为可开始对话）。 */
export function isCardPublished(state: string | undefined): boolean {
  return state === "saved" || state === "imported";
}
