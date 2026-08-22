export interface CharacterFormData {
  name: string;
  description: string;
  tags: string[];
  personality: string;
  scenario: string;
  first_mes: string;
  mes_example: string;
}

export type SaveStatus = "idle" | "unsaved" | "saving" | "saved" | "error";

export type CreateMode = "quick" | "advanced";

export const EMPTY_FORM_DATA: CharacterFormData = {
  name: "",
  description: "",
  tags: [],
  personality: "",
  scenario: "",
  first_mes: "",
  mes_example: "",
};

export const MAX_PERSONA_FIELD_LENGTH = 2000;

export function extractFormData(card: Record<string, unknown> | null): CharacterFormData {
  if (!card) {
    return { ...EMPTY_FORM_DATA };
  }
  const data = (card.data as Record<string, unknown>) ?? card;
  const rawTags = Array.isArray(data.tags) ? data.tags : [];
  const tags = rawTags.filter((t): t is string => typeof t === "string");

  return {
    name: typeof data.name === "string" ? data.name : "",
    description: typeof data.description === "string" ? data.description : "",
    tags,
    personality: typeof data.personality === "string" ? data.personality : "",
    scenario: typeof data.scenario === "string" ? data.scenario : "",
    first_mes: typeof data.first_mes === "string" ? data.first_mes : "",
    mes_example: typeof data.mes_example === "string" ? data.mes_example : "",
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
      system_prompt: "",
      post_history_instructions: "",
      creator: "",
      character_version: "1",
      alternate_greetings: [],
      extensions: {},
      ...existingData,
      name: formData.name.trim(),
      description: formData.description.trim(),
      tags: formData.tags,
      personality: formData.personality,
      scenario: formData.scenario,
      first_mes: formData.first_mes,
      mes_example: formData.mes_example,
    },
  };
}
