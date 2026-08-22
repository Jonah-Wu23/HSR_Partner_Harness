import { useEffect, useState } from "react";
import { CloseIcon } from "../../assets/icons/icons";
import type {
  AccountPageView,
  CharacterModelPageView,
  CodingAssistantPageView,
  TestResult,
  VoiceProvisionResult,
  VoicePageView,
  VoiceSpeakerStatus,
} from "./types";
import type { RemotePairingViewModel } from "../../contracts/view-models";
import { RemotePairingPanel } from "./remote/RemotePairingPanel";

export type SettingsPage = "account" | "coding" | "model" | "voice" | "remote";

interface SettingsCenterProps {
  open: boolean;
  page: SettingsPage;
  onPageChange: (page: SettingsPage) => void;
  onClose: () => void;
  account: AccountPageView;
  coding: CodingAssistantPageView;
  model: CharacterModelPageView;
  voice: VoicePageView;
  /** V0.3.3：远程设备页数据源与回调（remote.* 命令）。 */
  remote: RemotePairingViewModel;
  onIssuePairingCode: () => void;
  onListRemoteDevices: () => void;
  onRevokeRemoteDevice: (deviceName: string) => void;
  modelTest: TestResult;
  voicePreview: TestResult;
  onSaveProfile: (displayName: string) => void;
  onChangePassword: (oldPassword: string, newPassword: string) => void;
  onLogout: () => void;
  onCodexOAuthStart: () => void | Promise<void>;
  onCodexLogout: () => void;
  onCodexApiLogin: (apiKey: string) => void;
  onSaveModel: (config: CharacterModelPageView & { apiKey?: string }) => void | Promise<void>;
  onTestModel: () => void;
  /** 保存当前本地账号的语音配置与开关偏好。 */
  onSaveVoice: (config: {
    enabled: boolean;
    assistantVoiceEnabled: boolean;
    vadEnabled: boolean;
    baseUrl?: string;
    /** 只接受当前输入框的新 Key；已保存 Key 不会从 view 回传。 */
    apiKey?: string;
  }) => void | Promise<void>;
  onPreviewVoice: (voiceId: string, voiceName: string) => void;
  /** 当前窗口的 voice.provision 调用；未接入时保留真实错误，不伪造成功。 */
  onProvisionVoices?: (
    speakerIds: string[],
    replaceExisting?: boolean,
  ) => void | Promise<VoiceProvisionResult>;
}

const NAV: Array<{ id: SettingsPage; label: string }> = [
  { id: "account", label: "账号" },
  { id: "coding", label: "编程助手" },
  { id: "model", label: "角色对话模型" },
  { id: "voice", label: "语音" },
  { id: "remote", label: "远程设备" },
];

interface TestResultNoteProps {
  result: TestResult;
  okClass: string;
  testingLabel: string;
}

function TestResultNote({ result, okClass, testingLabel }: TestResultNoteProps) {
  if (result.state === "idle") return null;
  let className = "settings-hint";
  if (result.state === "ok") className = okClass;
  if (result.state === "failed") className = "field-error";
  return (
    <p className={className} role="status">
      {result.state === "testing" ? testingLabel : result.text}
    </p>
  );
}

const FIXED_ASR_MODEL = "qwen-audio-3.0-asr-flash-streaming";
const FIXED_TTS_MODEL = "qwen-audio-3.0-tts-flash";

// V0.3.4：助手侧说话方一律不出现在声音复刻中（fourth_mirror 是
// march7_fourth_mirror 配对的助手侧，服务端已冻结拒绝助手 TTS）。
const VOICE_SPEAKER_DEFINITIONS: Array<
  Pick<VoiceSpeakerStatus, "speakerId" | "name" | "method">
> = [
  { speakerId: "phainon", name: "白厄", method: "clone" },
  { speakerId: "firefly", name: "流萤", method: "clone" },
  { speakerId: "march7", name: "三月七", method: "clone" },
];

function normalizeSpeakerState(
  state: string | undefined,
): VoiceSpeakerStatus["state"] {
  if (state === "creating" || state === "completed" || state === "failed") return state;
  return "not_generated";
}

function speakerStateLabel(state: VoiceSpeakerStatus["state"]): string {
  if (state === "creating") return "创建中";
  if (state === "completed") return "已绑定";
  if (state === "failed") return "失败";
  return "未配置";
}

function speakerMethodLabel(method: VoiceSpeakerStatus["method"]): string {
  return method === "design" ? "声音设计" : "声音复刻";
}

function endpointsForBaseUrl(baseUrl: string): {
  customization: string;
  ws: string;
} {
  try {
    const parsed = new URL(baseUrl.trim());
    const base = `${parsed.protocol}//${parsed.host}`;
    const wsProtocol = parsed.protocol === "http:" ? "ws:" : "wss:";
    return {
      customization: `${base}/api/v1/services/audio/tts/customization`,
      ws: `${wsProtocol}//${parsed.host}/api-ws/v1/inference`,
    };
  } catch {
    return { customization: "", ws: "" };
  }
}

function vadStatusLabel(status: VoicePageView["vadStatus"]): string {
  if (status === "ready") return "就绪";
  if (status === "running") return "运行中";
  return "不可用";
}

/**
 * 设置中心：模态全屏遮罩，左栏目导航 + 右内容卡，Esc 关闭。
 * 技术参数统一收进每页底部「高级设置」折叠区；危险操作二次确认。
 */
export function SettingsCenter(props: SettingsCenterProps) {
  const { open, onClose } = props;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const Page = PAGES[props.page];

  return (
    <div className="settings-backdrop" onClick={onClose}>
      <div
        className="settings-panel"
        role="dialog"
        aria-label="设置"
        onClick={(event) => event.stopPropagation()}
      >
        <nav className="settings-nav" aria-label="设置栏目">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`settings-nav-item${props.page === item.id ? " is-current" : ""}`}
              onClick={() => props.onPageChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          <header className="settings-content-head">
            <h2>{NAV.find((item) => item.id === props.page)?.label}</h2>
            <button type="button" className="icon-btn" aria-label="关闭设置" onClick={onClose}>
              <CloseIcon />
            </button>
          </header>

          <Page {...props} />
        </div>
      </div>
    </div>
  );
}

function AccountPage(props: SettingsCenterProps) {
  const [name, setName] = useState(props.account.displayName);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirming, setConfirming] = useState(false);

  return (
    <section className="settings-page">
      <label className="field">
        <span className="field-label">显示名称</span>
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <div className="settings-row">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={!name.trim() || name === props.account.displayName}
          onClick={() => props.onSaveProfile(name.trim())}
        >
          保存资料
        </button>
      </div>

      <h3 className="settings-subhead">修改密码</h3>
      <label className="field">
        <span className="field-label">当前密码</span>
        <input type="password" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">新密码（至少 6 位）</span>
        <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
      </label>
      <div className="settings-row">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={!oldPassword || newPassword.length < 6}
          onClick={() => props.onChangePassword(oldPassword, newPassword)}
        >
          修改密码
        </button>
      </div>

      <h3 className="settings-subhead">会话</h3>
      {confirming ? (
        <div className="settings-confirm" role="alert">
          退出登录后需要重新输入密码。确定退出？
          <span className="settings-confirm-actions">
            <button type="button" className="btn btn-danger-outline" onClick={props.onLogout}>
              确定退出
            </button>
            <button type="button" className="btn btn-outline" onClick={() => setConfirming(false)}>
              再想想
            </button>
          </span>
        </div>
      ) : (
        <button type="button" className="btn btn-outline" onClick={() => setConfirming(true)}>
          退出登录
        </button>
      )}
    </section>
  );
}

function CodingAssistantPage(props: SettingsCenterProps) {
  const [apiKey, setApiKey] = useState("");
  const [oauthError, setOauthError] = useState<string | null>(null);
  const { codex } = props.coding;

  const startOAuth = async () => {
    setOauthError(null);
    try {
      await props.onCodexOAuthStart();
    } catch (error) {
      setOauthError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <section className="settings-page">
      <p className="settings-hint">
        供应商在「角色对话模型」页统一选择，角色和助手始终使用同一家：OpenAI OAuth/API 使用 GPT，DeepSeek 使用 DeepSeek。
      </p>

      {props.coding.engine === "codex" ? (
        <div className={`settings-status-card settings-status-${codex.status}`}>
          {codex.status === "logged_in" ? (
            <>
              <p className="settings-status-ok">已登录 {codex.accountLabel ?? "Codex"}</p>
              <div className="settings-row">
                <button type="button" className="btn btn-outline" onClick={() => void startOAuth()}>
                  重新授权
                </button>
                <button type="button" className="btn btn-danger-outline" onClick={props.onCodexLogout}>
                  退出登录
                </button>
              </div>
            </>
          ) : codex.status === "waiting" ? (
            <p role="status">等待浏览器授权… 请在打开的浏览器页面完成登录。</p>
          ) : (
            <>
              {codex.status === "expired" ? (
                <p className="field-error" role="alert">登录已过期，请重新授权。</p>
              ) : null}
              <div className="settings-row">
                <button type="button" className="btn btn-primary" onClick={() => void startOAuth()}>
                  通过浏览器登录
                </button>
              </div>
              {oauthError ? <p className="field-error" role="alert">{oauthError}</p> : null}
              <h3 className="settings-subhead">或使用 API Key</h3>
              <label className="field">
                <span className="field-label">OpenAI API Key</span>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                />
              </label>
              <div className="settings-row">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={!apiKey}
                  onClick={() => props.onCodexApiLogin(apiKey)}
                >
                  保存并验证
                </button>
              </div>
            </>
          )}
        </div>
      ) : (
        <p className="settings-hint">
          DeepSeek 编程助手复用「角色对话模型」页的服务商与 Key，保存后下一个任务生效。
        </p>
      )}
    </section>
  );
}

function CharacterModelPage(props: SettingsCenterProps) {
  const normalizeProvider = (value: string) => {
    const normalized = value.trim().toLowerCase().replaceAll("_", " ");
    if (normalized.includes("deepseek")) return "deepseek";
    if (normalized.includes("oauth")) return "openai_oauth";
    return "openai_compatible";
  };
  const defaultsForProvider = (provider: string) =>
    provider === "deepseek"
      ? { baseUrl: "https://api.deepseek.com", model: "deepseek-v4-flash" }
      : { baseUrl: "https://api.openai.com/v1", model: "gpt-5.6-sol" };
  const [form, setForm] = useState({
    ...props.model,
    provider: normalizeProvider(props.model.provider),
  });
  const initialProvider = normalizeProvider(props.model.provider);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const dirty =
    form.provider !== initialProvider ||
    form.model !== props.model.model ||
    form.baseUrl !== props.model.baseUrl ||
    form.reasoningEffort !== props.model.reasoningEffort ||
    apiKey !== "";

  return (
    <section className="settings-page">
      <label className="field">
        <span className="field-label">服务商</span>
        <select
          value={form.provider}
          onChange={(event) => {
            const provider = event.target.value;
            setForm({ ...form, provider, ...defaultsForProvider(provider) });
          }}
        >
          <option value="deepseek">DeepSeek</option>
          <option value="openai_compatible">OpenAI API</option>
          <option value="openai_oauth">OpenAI OAuth</option>
        </select>
      </label>
      <label className="field">
        <span className="field-label">模型</span>
        <input value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} />
      </label>
      <label className="field">
        <span className="field-label">
          API Key{props.model.apiKeyMasked ? <span className="field-note">当前已保存 {props.model.apiKeyMasked}</span> : null}
        </span>
        <input
          type="password"
          value={apiKey}
          placeholder="留空表示不修改"
          onChange={(event) => setApiKey(event.target.value)}
        />
      </label>
      {form.provider === "deepseek" ? (
        <label className="field">
          <span className="field-label">推理等级</span>
          <select
            value={form.reasoningEffort}
            onChange={(event) => setForm({ ...form, reasoningEffort: event.target.value })}
          >
            <option value="auto">自动</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="max">最高</option>
          </select>
        </label>
      ) : (
        <p className="settings-hint">当前服务不支持自定义推理等级，由服务端默认决定。</p>
      )}

      <details className="settings-advanced">
        <summary>高级设置</summary>
        <label className="field">
          <span className="field-label">
            接口地址<span className="field-note">就是 API Base URL，一般不用改</span>
          </span>
          <input value={form.baseUrl} onChange={(event) => setForm({ ...form, baseUrl: event.target.value })} />
        </label>
      </details>

      <TestResultNote result={props.modelTest} okClass="field-ok" testingLabel="正在测试连接…" />
      {saveError ? <p className="field-error" role="alert">{saveError}</p> : null}

      <div className="settings-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!dirty || saving}
          onClick={() => {
            setSaving(true);
            setSaveError(null);
            void Promise.resolve(props.onSaveModel({ ...form, apiKey: apiKey || undefined }))
              .then(() => {
                // OAuth 的保存动作会直接启动浏览器登录；此时不能立刻拿
                // 尚未登录的 OAuth 状态去做连接测试并显示失败。
                if (form.provider !== "openai_oauth") props.onTestModel();
              })
              .catch((error: unknown) => {
                setSaveError(error instanceof Error ? error.message : String(error));
              })
              .finally(() => setSaving(false));
          }}
        >
          {saving ? "正在保存…" : "保存并测试"}
        </button>
      </div>
    </section>
  );
}

function VoicePage(props: SettingsCenterProps) {
  const { voice } = props;

  const [baseUrl, setBaseUrl] = useState(voice.baseUrl ?? "");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [provisionError, setProvisionError] = useState<string | null>(null);
  const [provisioningIds, setProvisioningIds] = useState<string[]>([]);
  const [localSpeakers, setLocalSpeakers] = useState<
    Record<string, Partial<VoiceSpeakerStatus>>
  >({});

  useEffect(() => {
    setBaseUrl(voice.baseUrl ?? "");
    setApiKey("");
    setSaveError(null);
    setSaveNotice(null);
  }, [voice.baseUrl, voice.apiKeyMasked]);

  const draftEndpoints = endpointsForBaseUrl(baseUrl);
  const customizationEndpoint = draftEndpoints.customization || voice.customizationEndpoint || "";
  const wsUrl = draftEndpoints.ws || voice.wsUrl || "";
  const hasSavedKey = Boolean(voice.apiKeyMasked);
  const hasConfig = Boolean(baseUrl.trim()) && Boolean(apiKey.trim() || hasSavedKey);
  const asrAvailable = voice.asrAvailable ?? hasConfig;

  const serverSpeakers = new Map(
    (voice.speakers ?? []).map((speaker) => [speaker.speakerId, speaker]),
  );
  const speakers = VOICE_SPEAKER_DEFINITIONS.map((definition) => {
    const serverSpeaker = serverSpeakers.get(definition.speakerId);
    const localSpeaker = localSpeakers[definition.speakerId];
    return {
      ...definition,
      ...localSpeaker,
      ...serverSpeaker,
      voiceId: serverSpeaker?.voiceId ?? localSpeaker?.voiceId,
      error: serverSpeaker?.error ?? localSpeaker?.error ?? null,
      state: normalizeSpeakerState(serverSpeaker?.state ?? localSpeaker?.state),
    };
  });

  const failedSpeakerIds = speakers
    .filter((speaker) => speaker.state === "failed")
    .map((speaker) => speaker.speakerId);
  const provisionTargetIds = (
    failedSpeakerIds.length > 0
      ? failedSpeakerIds
      : speakers
          .filter((speaker) => speaker.state === "not_generated")
          .map((speaker) => speaker.speakerId)
  ).filter((speakerId) => !provisioningIds.includes(speakerId));
  const completedCount = speakers.filter((speaker) => speaker.state === "completed").length;
  const provisioning = provisioningIds.length > 0;

  const savePreferences = async (config: {
    enabled?: boolean;
    assistantVoiceEnabled?: boolean;
    vadEnabled?: boolean;
  }) => {
    setSaveError(null);
    try {
      await props.onSaveVoice({
        enabled: config.enabled ?? voice.enabled,
        assistantVoiceEnabled: config.assistantVoiceEnabled ?? voice.assistantVoiceEnabled,
        vadEnabled: config.vadEnabled ?? voice.vadEnabled,
        baseUrl: baseUrl.trim() || undefined,
      });
    } catch (error: unknown) {
      setSaveError(error instanceof Error ? error.message : String(error));
    }
  };

  const saveVoiceAccount = async () => {
    const nextBaseUrl = baseUrl.trim();
    const nextApiKey = apiKey.trim();
    if (!nextBaseUrl || (!nextApiKey && !hasSavedKey)) {
      setSaveError("请填写 DashScope API Key 和服务地址后再保存。");
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveNotice(null);
    try {
      await props.onSaveVoice({
        enabled: voice.enabled,
        assistantVoiceEnabled: voice.assistantVoiceEnabled,
        vadEnabled: voice.vadEnabled,
        baseUrl: nextBaseUrl,
        ...(nextApiKey ? { apiKey: nextApiKey } : {}),
      });
      setApiKey("");
      setSaveNotice("语音配置已提交保存；Key 仅保存在当前本地账号。");
    } catch (error: unknown) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const provisionVoices = async (speakerIds: string[], replaceExisting = false) => {
    setProvisionError(null);
    if (!props.onProvisionVoices) {
      setProvisionError("当前窗口尚未接入 voice.provision 调用，未伪造生成结果。");
      return;
    }
    setProvisioningIds((current) => [...new Set([...current, ...speakerIds])]);
    setLocalSpeakers((current) => {
      const next = { ...current };
      speakerIds.forEach((speakerId) => {
        next[speakerId] = { ...next[speakerId], state: "creating", error: null };
      });
      return next;
    });
    try {
      const result = await props.onProvisionVoices(speakerIds, replaceExisting);
      if (result?.results) {
        setLocalSpeakers((current) => {
          const next = { ...current };
          result.results?.forEach((item) => {
            const previous = next[item.speaker_id] ?? {};
            next[item.speaker_id] = {
              ...previous,
              state: normalizeSpeakerState(item.state),
              ...(item.voice_id ? { voiceId: item.voice_id } : {}),
              error: item.error ?? null,
            };
          });
          return next;
        });
      }
    } catch (error: unknown) {
      setProvisionError(error instanceof Error ? error.message : String(error));
    } finally {
      setProvisioningIds((current) => current.filter((id) => !speakerIds.includes(id)));
    }
  };

  return (
    <section className="settings-page">
      <p className="settings-hint">
        语音直接使用你自己的 DashScope 账号。Key 只写入当前本地账号的密钥引用，不会显示明文；保存配置不会自动创建音色。
      </p>

      <h3 className="settings-subhead">DashScope 账号配置</h3>
      <label className="field">
        <span className="field-label">
          API Key
          <span className="field-note">
            {voice.credentialSource === "account" && voice.apiKeyMasked
              ? `当前账号已保存 ${voice.apiKeyMasked}`
              : voice.credentialSource === "development_env"
                ? "开发环境 .env Key 可用，尚未保存到当前账号"
                : "当前账号尚未保存"}
          </span>
        </span>
        <input
          type="password"
          value={apiKey}
          autoComplete="new-password"
          placeholder={voice.apiKeyMasked ? `留空保留当前 ${voice.apiKeyMasked}` : "填写自己的 DashScope API Key"}
          onChange={(event) => setApiKey(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field-label">
          服务地址
          <span className="field-note">北京 Key 配北京地址，新加坡 Key 配新加坡地址</span>
        </span>
        <input
          value={baseUrl}
          placeholder="https://dashscope.aliyuncs.com/api/v1"
          onChange={(event) => setBaseUrl(event.target.value)}
        />
      </label>

      <div className="settings-endpoint-card">
        <div>
          <span className="field-label">音色创建接口</span>
          <code>{customizationEndpoint || "填写有效服务地址后显示"}</code>
        </div>
        <div>
          <span className="field-label">ASR WebSocket 接口</span>
          <code>{wsUrl || "填写有效服务地址后显示"}</code>
        </div>
      </div>

      <div className="settings-fixed-models" aria-label="固定语音模型">
        <div>
          <span className="field-label">ASR 模型</span>
          <code>{FIXED_ASR_MODEL}</code>
        </div>
        <div>
          <span className="field-label">TTS 模型</span>
          <code>{FIXED_TTS_MODEL}</code>
        </div>
      </div>

      {saveError ? <p className="field-error" role="alert">{saveError}</p> : null}
      {saveNotice ? <p className="field-ok" role="status">{saveNotice}</p> : null}
      <div className="settings-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={saving || !baseUrl.trim() || (!apiKey.trim() && !hasSavedKey)}
          onClick={() => void saveVoiceAccount()}
        >
          {saving ? "正在保存…" : "保存语音配置"}
        </button>
      </div>

      <h3 className="settings-subhead">专属音色</h3>
      <p className="settings-hint">
        当前账号将依次提交 {VOICE_SPEAKER_DEFINITIONS.length} 次声音复刻。生成请求使用当前百炼账号的额度；是否计费以该账号页面和真实响应为准。助手侧说话方不支持语音，不在生成列表中。
      </p>
      {!hasConfig ? (
        <div className="settings-status-card" role="alert">
          <p className="field-error">
            语音服务账号未配置：尚未填写有效 DashScope API Key 与服务地址，无法生成音色。
          </p>
          <p className="settings-hint">请先在上方填写并保存 DashScope 账号配置。</p>
        </div>
      ) : null}
      <div className="settings-voice-progress" role="status" aria-live="polite">
        <span>进度：{completedCount}/{VOICE_SPEAKER_DEFINITIONS.length} 项已绑定</span>
        <span>{voice.voicesSource === "env_author" ? "开发机兼容音色" : "当前账号音色"}</span>
      </div>
      <div className="settings-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={provisioning || provisionTargetIds.length === 0 || !hasConfig}
          onClick={() => void provisionVoices(provisionTargetIds)}
        >
          {provisioning
            ? "正在生成…"
            : failedSpeakerIds.length > 0
              ? "重试失败项"
              : completedCount > 0
                ? "继续生成剩余音色"
                : `生成 ${VOICE_SPEAKER_DEFINITIONS.length} 个专属音色`}
        </button>
      </div>
      {provisionError ? <p className="field-error" role="alert">{provisionError}</p> : null}

      <div className="settings-voice-speakers">
        {speakers.map((speaker) => {
          const isBusy = provisioningIds.includes(speaker.speakerId);
          const canPreview = Boolean(speaker.voiceId);
          return (
            <article
              key={speaker.speakerId}
              className={`settings-voice-speaker settings-voice-state-${speaker.state}`}
            >
              <div className="settings-voice-speaker-head">
                <div>
                  <strong>{speaker.name}</strong>
                  <span className="settings-voice-method">{speakerMethodLabel(speaker.method)}</span>
                </div>
                <span className="settings-voice-state-label">
                  {isBusy ? "生成中" : speakerStateLabel(speaker.state)}
                </span>
              </div>
              {speaker.voiceId ? (
                <code className="settings-voice-id">{speaker.voiceId}</code>
              ) : (
                <span className="settings-voice-id settings-voice-unconfigured">
                  尚未生成音色 ID
                </span>
              )}
              {speaker.error ? <p className="field-error">{speaker.error}</p> : null}
              <div className="settings-voice-actions">
                {canPreview ? (
                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={() => props.onPreviewVoice(speaker.voiceId ?? "", speaker.name)}
                  >
                    试听
                  </button>
                ) : null}
                {speaker.state === "completed" ? (
                  <button
                    type="button"
                    className="btn btn-outline"
                    disabled={isBusy}
                    onClick={() => void provisionVoices([speaker.speakerId], true)}
                  >
                    重新生成
                  </button>
                ) : speaker.state === "failed" ? (
                  <button
                    type="button"
                    className="btn btn-outline"
                    disabled={isBusy}
                    onClick={() => void provisionVoices([speaker.speakerId])}
                  >
                    重试
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>

      <p className="settings-hint">为自定义角色上传参考音频并生成音色将于 V0.3.5 开放。</p>

      <label className="settings-switch">
        <input
          type="checkbox"
          checked={voice.enabled}
          disabled={!voice.enabled && !hasConfig}
          onChange={(event) => void savePreferences({ enabled: event.target.checked })}
        />
        语音功能
        <span className="field-note">
          {voice.credentialSource === "account"
            ? "当前账号 BYOK 已配置"
            : voice.credentialSource === "development_env"
              ? "开发环境 .env 凭据可用（未保存到账号）"
              : asrAvailable
                ? "ASR 已具备配置条件"
                : "保存 Key 和服务地址后可开启"}
        </span>
      </label>

      <label className="settings-switch">
        <input
          type="checkbox"
          checked={voice.vadEnabled}
          disabled={!voice.enabled || !hasConfig}
          onChange={(event) => void savePreferences({ vadEnabled: event.target.checked })}
        />
        语音自动聆听（VAD）
        <span className={`voice-vad-pill voice-vad-${voice.vadStatus}`}>
          {vadStatusLabel(voice.vadStatus)}
        </span>
      </label>

      <TestResultNote
        result={props.voicePreview}
        okClass="settings-hint"
        testingLabel="正在合成试听…"
      />
    </section>
  );
}

function RemotePage(props: SettingsCenterProps) {
  return (
    <RemotePairingPanel
      vm={props.remote}
      onIssuePairingCode={props.onIssuePairingCode}
      onListRemoteDevices={props.onListRemoteDevices}
      onRevokeRemoteDevice={props.onRevokeRemoteDevice}
    />
  );
}

const PAGES = {
  account: AccountPage,
  coding: CodingAssistantPage,
  model: CharacterModelPage,
  voice: VoicePage,
  remote: RemotePage,
};
