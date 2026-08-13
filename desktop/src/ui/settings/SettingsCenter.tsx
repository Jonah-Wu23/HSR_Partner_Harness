import { useEffect, useState } from "react";
import sponsorQr from "../../assets/sponsor/qrcode.png";
import { CloseIcon, HeartIcon } from "../../assets/icons/icons";
import type {
  AccountPageView,
  CharacterModelPageView,
  CodingAssistantPageView,
  TestResult,
  VoicePageView,
} from "./types";

export type SettingsPage = "account" | "coding" | "model" | "voice";

interface SettingsCenterProps {
  open: boolean;
  page: SettingsPage;
  onPageChange: (page: SettingsPage) => void;
  onClose: () => void;
  account: AccountPageView;
  coding: CodingAssistantPageView;
  model: CharacterModelPageView;
  voice: VoicePageView;
  modelTest: TestResult;
  voicePreview: TestResult;
  onSaveProfile: (displayName: string) => void;
  onChangePassword: (oldPassword: string, newPassword: string) => void;
  onLogout: () => void;
  onSelectEngine: (engine: "codex" | "deepseek") => void;
  onCodexOAuthStart: () => void;
  onCodexLogout: () => void;
  onCodexApiLogin: (apiKey: string) => void;
  onSaveModel: (config: CharacterModelPageView & { apiKey?: string }) => void;
  onTestModel: () => void;
  /** 语音页只有两个开关可改（总开关 / VAD），改动即保存，无独立保存按钮。 */
  onSaveVoice: (config: { enabled: boolean; vadEnabled: boolean }) => void;
  onPreviewVoice: (voiceId: string, voiceName: string) => void;
}

const NAV: Array<{ id: SettingsPage; label: string }> = [
  { id: "account", label: "账号" },
  { id: "coding", label: "编程助手" },
  { id: "model", label: "角色对话模型" },
  { id: "voice", label: "语音" },
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

interface VoicePreviewFieldProps {
  label: string;
  voiceId: string;
  voiceName: string;
  fallbackName: string;
  onPreview: () => void;
}

function VoicePreviewField({
  label,
  voiceId,
  voiceName,
  fallbackName,
  onPreview,
}: VoicePreviewFieldProps) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className="settings-voice-info">
        <span>
          <span className="settings-voice-info-name">{voiceName || fallbackName}</span>
          {voiceId ? <div className="settings-voice-info-id">{voiceId}</div> : null}
        </span>
        <button type="button" className="btn btn-outline" onClick={onPreview}>
          试听
        </button>
      </span>
    </div>
  );
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
        <span className="field-label">新密码（至少 4 位）</span>
        <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
      </label>
      <div className="settings-row">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={!oldPassword || newPassword.length < 4}
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
  const { codex } = props.coding;

  return (
    <section className="settings-page">
      <div className="segmented" role="radiogroup" aria-label="选择编程助手">
        <button
          type="button"
          role="radio"
          aria-checked={props.coding.engine === "codex"}
          className={`segmented-item${props.coding.engine === "codex" ? " is-selected" : ""}`}
          onClick={() => props.onSelectEngine("codex")}
        >
          使用 Codex
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={props.coding.engine === "deepseek"}
          className={`segmented-item${props.coding.engine === "deepseek" ? " is-selected" : ""}`}
          onClick={() => props.onSelectEngine("deepseek")}
        >
          使用 DeepSeek
        </button>
      </div>

      {props.coding.engine === "codex" ? (
        <div className={`settings-status-card settings-status-${codex.status}`}>
          {codex.status === "logged_in" ? (
            <>
              <p className="settings-status-ok">已登录 {codex.accountLabel ?? "Codex"}</p>
              <div className="settings-row">
                <button type="button" className="btn btn-outline" onClick={props.onCodexOAuthStart}>
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
                <button type="button" className="btn btn-primary" onClick={props.onCodexOAuthStart}>
                  通过浏览器登录
                </button>
              </div>
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
  const [form, setForm] = useState(props.model);
  const [apiKey, setApiKey] = useState("");
  const dirty =
    form.provider !== props.model.provider ||
    form.model !== props.model.model ||
    form.baseUrl !== props.model.baseUrl ||
    form.reasoningEffort !== props.model.reasoningEffort ||
    apiKey !== "";

  return (
    <section className="settings-page">
      <label className="field">
        <span className="field-label">服务商</span>
        <input value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value })} />
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
      <label className="field">
        <span className="field-label">推理等级</span>
        <select
          value={form.reasoningEffort}
          onChange={(event) => setForm({ ...form, reasoningEffort: event.target.value })}
        >
          <option value="low">低</option>
          <option value="medium">中</option>
          <option value="high">高</option>
        </select>
      </label>

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

      <div className="settings-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!dirty}
          onClick={() => {
            props.onSaveModel({ ...form, apiKey: apiKey || undefined });
            props.onTestModel();
          }}
        >
          保存并测试
        </button>
      </div>
    </section>
  );
}

function VoicePage(props: SettingsCenterProps) {
  const { voice } = props;
  return (
    <section className="settings-page">
      {/* 语音总开关：与赞助无关，跳过赞助可直接开启；关闭后输入区语音按钮整体隐藏 */}
      <label className="settings-switch">
        <input
          type="checkbox"
          checked={voice.enabled}
          onChange={(event) =>
            props.onSaveVoice({ enabled: event.target.checked, vadEnabled: voice.vadEnabled })
          }
        />
        语音功能
        <span className="field-note">关闭后输入区的语音按钮整体隐藏</span>
      </label>

      {/* 自愿赞助卡：语音服务由作者自费提供，二维码为微信收款码 */}
      <div className="settings-sponsor">
        <span className="settings-sponsor-head" aria-hidden="true">
          <HeartIcon />
        </span>
        <p className="settings-sponsor-title">喜欢这个语音功能的话，请给作者一点支持</p>
        <p className="settings-sponsor-copy">
          语音服务由作者自费提供，服务器与模型费用需要持续投入。一杯咖啡的赞助能让它继续运转。
        </p>
        <div className="settings-sponsor-qr">
          <img src={sponsorQr} alt="微信收款二维码" width={148} />
        </div>
        <span className="settings-sponsor-meta">微信支付 · 扫码打赏</span>
        <span className="settings-sponsor-payee">请认准收款人：天小可</span>
        <span className="settings-sponsor-amount">
          <strong>6元</strong>一杯咖啡的价格
        </span>
        <div className="settings-sponsor-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={voice.enabled}
            onClick={() => props.onSaveVoice({ enabled: true, vadEnabled: voice.vadEnabled })}
          >
            我已打赏，开启语音
          </button>
          <p className="settings-sponsor-note">
            无论是否打赏，都可以直接开启语音。打赏完全自愿，感谢每一份心意。
          </p>
        </div>
      </div>

      {voice.enabled ? (
        <>
          {/* 内置音色只读展示：音色由作者预先复刻/设计，随应用分发 */}
          <div className="settings-grid">
            <VoicePreviewField
              label="角色音色"
              voiceId={voice.characterVoiceId}
              voiceName={voice.characterVoiceName}
              fallbackName="白厄"
              onPreview={() =>
                props.onPreviewVoice(voice.characterVoiceId, voice.characterVoiceName)
              }
            />
            <VoicePreviewField
              label="助手音色"
              voiceId={voice.assistantVoiceId}
              voiceName={voice.assistantVoiceName}
              fallbackName="神秘的古代机械"
              onPreview={() =>
                props.onPreviewVoice(voice.assistantVoiceId, voice.assistantVoiceName)
              }
            />
          </div>

          <TestResultNote
            result={props.voicePreview}
            okClass="settings-hint"
            testingLabel="正在合成试听…"
          />

          <label className="settings-switch">
            <input
              type="checkbox"
              checked={voice.vadEnabled}
              onChange={(event) =>
                props.onSaveVoice({ enabled: voice.enabled, vadEnabled: event.target.checked })
              }
            />
            语音自动聆听（VAD）
            <span className={`voice-vad-pill voice-vad-${voice.vadStatus}`}>
              {vadStatusLabel(voice.vadStatus)}
            </span>
          </label>
        </>
      ) : null}
    </section>
  );
}

const PAGES = {
  account: AccountPage,
  coding: CodingAssistantPage,
  model: CharacterModelPage,
  voice: VoicePage,
};
