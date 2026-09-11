/* B-03 产品决策：只支持 OpenAI Chat Completions 兼容端点，Codex 与不可用的
   OpenAI OAuth 入口一并移除。界面可选的对话服务商只有这里列出的两个，都用
   Base URL + API Key 配置，共同供角色对话与编程助手使用。某个已保存的服务商
   是否仍然可用，以后端 config.get 的 dialogue.provider_supported 为准。 */

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

/** 该值是否属于界面可选的服务商（即产品支持的两个）。历史账号可能保存着
    已被移除的服务商，此时下拉里没有对应选项，界面不静默改写用户配置。 */
export function isSupportedDialogueProvider(value: string): value is DialogueProviderId {
  return DIALOGUE_PROVIDER_IDS.some((id) => id === value);
}

/** 把 config.get 的 dialogue.provider 收敛为界面选项 id。识别不了的值原样返回，
    由调用方按「不在选项内」呈现——不做语义猜测，也不替用户改配置；是否可用
    由后端 dialogue.provider_supported 判定。 */
export function normalizeDialogueProvider(value: string): string {
  const normalized = value.trim().toLowerCase().replaceAll("_", " ");
  if (normalized.includes("deepseek")) return "deepseek";
  if (normalized.includes("oauth")) return "openai_oauth";
  return "openai_compatible";
}
