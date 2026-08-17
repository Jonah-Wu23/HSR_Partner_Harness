/* 设置中心四页的视图类型。对应协议 config.get / config.set、
   codex.oauth_*、voice.preview、voice.provision、account.update_profile，
   由 presenters 映射。 */

export interface AccountPageView {
  displayName: string;
  avatarUrl?: string | null;
}

export interface CodingAssistantPageView {
  /** 当前编程助手选择。 */
  engine: "codex" | "deepseek";
  codex: {
    status: "logged_out" | "waiting" | "logged_in" | "expired";
    accountLabel?: string | null;
  };
}

export interface CharacterModelPageView {
  provider: string;
  model: string;
  baseUrl: string;
  /** 已保存的 Key 只回显掩码，不回传明文。 */
  apiKeyMasked: string;
  reasoningEffort: string;
}

/** V0.3.2 M6：6 个说话方的专属音色生成状态。 */
export interface VoiceSpeakerStatus {
  speakerId: string;
  name: string;
  method: "clone" | "design";
  state: "not_generated" | "creating" | "completed" | "failed";
  voiceId?: string;
  error?: string | null;
}

export interface VoiceProvisionResult {
  status?: "completed" | "partial_failed" | string;
  completed?: number;
  total?: number;
  results?: Array<{
    speaker_id: string;
    state: "pending" | "creating" | "completed" | "failed" | string;
    voice_id?: string | null;
    error?: string | null;
  }>;
}

export interface VoicePageView {
  /** 语音功能总开关（账号配置 voice.enabled）。 */
  enabled: boolean;
  /** 古代机械（助手）自动朗读开关，默认关闭。 */
  assistantVoiceEnabled: boolean;
  vadEnabled: boolean;
  vadStatus: "ready" | "running" | "unavailable";

  /* —— DashScope 账号配置（BYOK）—— */
  /** 已保存的服务地址（HTTP API 基址，含 /api/v1）。 */
  baseUrl?: string;
  /** 已保存的 Key 只回显掩码，不回传明文。 */
  apiKeyMasked?: string;
  /** 由服务地址推导的 ASR WebSocket 地址（保存前核对）。 */
  wsUrl?: string;
  /** 由服务地址推导的音色创建 endpoint（保存前核对）。 */
  customizationEndpoint?: string;
  /** 只读固定模型（产品常量，无编辑入口）。 */
  asrModel?: string;
  ttsModel?: string;
  /** Key + 服务地址有效即可用 ASR（PTT/VAD），不依赖音色。 */
  asrAvailable?: boolean;
  /** 凭据来源：账号 BYOK、开发环境 .env，或尚未配置。 */
  credentialSource?: "account" | "development_env" | "not_configured";
  /** 音色来源：account=账号自建；env_author=开发机作者 Key；not_provisioned。 */
  voicesSource?: "account" | "env_author" | "not_provisioned";

  /* —— 专属音色生成 —— */
  speakers?: VoiceSpeakerStatus[];

  /* —— 当前搭档有效音色（试听按钮回传 voice_id；未生成为空）—— */
  characterVoiceId: string;
  characterVoiceName: string;
  assistantVoiceId: string;
  assistantVoiceName: string;
}

/** 「保存并测试」/「试听」的三态结果。 */
export interface TestResult {
  state: "idle" | "testing" | "ok" | "failed";
  /** 人话结果，例如「连接正常（延迟 218 ms）」或「Key 无效，请检查后重试」。 */
  text?: string;
}
