/* 界面可选的对话服务商，都是 OpenAI Chat Completions 兼容端点，用 Base URL 与 API Key
   配置，共同供角色对话与编程助手使用。已保存的服务商是否可用以 config.get 的
   dialogue.provider_supported 为准。 */

export type DialogueProviderId = "deepseek" | "openai_compatible";

export interface DialogueProviderOption {
  label: string;
  baseUrl: string;
  model: string;
}

/** 下拉顺序即产品顺序：DeepSeek 在前，通用 OpenAI 兼容端点在后。 */
export const DIALOGUE_PROVIDER_IDS: DialogueProviderId[] = ["deepseek", "openai_compatible"];

export const DIALOGUE_PROVIDERS: Record<DialogueProviderId, DialogueProviderOption> = {
  deepseek: { label: "DeepSeek", baseUrl: "https://api.deepseek.com", model: "deepseek-v4-flash" },
  openai_compatible: {
    label: "OpenAI 兼容 API",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-5.6-sol",
  },
};

/** 该值是否属于界面可选的服务商。账号可能保存着已不支持的服务商，此时下拉里没有对应选项，
    界面不改写用户配置。 */
export function isSupportedDialogueProvider(value: string): value is DialogueProviderId {
  return DIALOGUE_PROVIDER_IDS.some((id) => id === value);
}
