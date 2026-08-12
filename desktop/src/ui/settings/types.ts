/* 设置中心四页的视图类型。对应协议 config.get / config.set、
   codex.oauth_*、voice.preview、account.update_profile，由 presenters 映射。 */

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

export interface VoicePageView {
  /** 语音功能总开关（与赞助无关，不赞助也可开启）。 */
  enabled: boolean;
  /** 内置角色/助手音色展示（试听按钮回传 voice_id）。 */
  characterVoiceId: string;
  characterVoiceName: string;
  assistantVoiceId: string;
  assistantVoiceName: string;
  vadEnabled: boolean;
  vadStatus: "ready" | "running" | "unavailable";
}

/** 「保存并测试」/「试听」的三态结果。 */
export interface TestResult {
  state: "idle" | "testing" | "ok" | "failed";
  /** 人话结果，例如「连接正常（延迟 218 ms）」或「Key 无效，请检查后重试」。 */
  text?: string;
}
