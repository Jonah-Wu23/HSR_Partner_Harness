import { useEffect, useState } from "react";
import { CloseIcon } from "../../assets/icons/icons";
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
  onSaveVoice: (config: VoicePageView & { apiKey?: string }) => void;
  onPreviewVoice: (voiceId: string) => void;
}

const NAV: Array<{ id: SettingsPage; label: string }> = [
  { id: "account", label: "账号" },
  { id: "coding", label: "编程助手" },
  { id: "model", label: "角色对话模型" },
  { id: "voice", label: "语音" },
];

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

          {props.page === "account" ? <AccountPage {...props} /> : null}
          {props.page === "coding" ? <CodingAssistantPage {...props} /> : null}
          {props.page === "model" ? <CharacterModelPage {...props} /> : null}
          {props.page === "voice" ? <VoicePage {...props} /> : null}
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

      {props.modelTest.state !== "idle" ? (
        <p
          className={props.modelTest.state === "ok" ? "field-ok" : props.modelTest.state === "failed" ? "field-error" : "settings-hint"}
          role="status"
        >
          {props.modelTest.state === "testing" ? "正在测试连接…" : props.modelTest.text}
        </p>
      ) : null}

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
  const [form, setForm] = useState(props.voice);
  const [apiKey, setApiKey] = useState("");

  return (
    <section className="settings-page">
      <label className="settings-switch">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
        />
        语音功能
        <span className="field-note">关闭后输入区的语音按钮整体隐藏</span>
      </label>

      {form.enabled ? (
        <>
          <label className="field">
            <span className="field-label">
              API Key{props.voice.apiKeyMasked ? <span className="field-note">当前已保存 {props.voice.apiKeyMasked}</span> : null}
            </span>
            <input
              type="password"
              value={apiKey}
              placeholder="留空表示不修改"
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>
          <div className="settings-grid">
            <label className="field">
              <span className="field-label">ASR 模型</span>
              <input value={form.asrModel} onChange={(event) => setForm({ ...form, asrModel: event.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">TTS 模型</span>
              <input value={form.ttsModel} onChange={(event) => setForm({ ...form, ttsModel: event.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">角色音色</span>
              <span className="settings-voice-row">
                <input value={form.characterVoice} onChange={(event) => setForm({ ...form, characterVoice: event.target.value })} />
                <button type="button" className="btn btn-outline" onClick={() => props.onPreviewVoice(form.characterVoice)}>
                  试听
                </button>
              </span>
            </label>
            <label className="field">
              <span className="field-label">助手音色</span>
              <span className="settings-voice-row">
                <input value={form.assistantVoice} onChange={(event) => setForm({ ...form, assistantVoice: event.target.value })} />
                <button type="button" className="btn btn-outline" onClick={() => props.onPreviewVoice(form.assistantVoice)}>
                  试听
                </button>
              </span>
            </label>
          </div>

          {props.voicePreview.state !== "idle" ? (
            <p
              className={props.voicePreview.state === "failed" ? "field-error" : "settings-hint"}
              role="status"
            >
              {props.voicePreview.state === "testing" ? "正在合成试听…" : props.voicePreview.text}
            </p>
          ) : null}

          <label className="settings-switch">
            <input
              type="checkbox"
              checked={form.vadEnabled}
              onChange={(event) => setForm({ ...form, vadEnabled: event.target.checked })}
            />
            语音自动聆听（VAD）
            <span className={`voice-vad-pill voice-vad-${form.vadStatus}`}>
              {form.vadStatus === "ready" ? "就绪" : form.vadStatus === "running" ? "运行中" : "不可用"}
            </span>
          </label>

          <details className="settings-advanced">
            <summary>高级设置</summary>
            <label className="field">
              <span className="field-label">
                服务地址<span className="field-note">DashScope Base URL，一般不用改</span>
              </span>
              <input value={form.baseUrl} onChange={(event) => setForm({ ...form, baseUrl: event.target.value })} />
            </label>
          </details>
        </>
      ) : null}

      <div className="settings-row">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => props.onSaveVoice({ ...form, apiKey: apiKey || undefined })}
        >
          保存
        </button>
      </div>
    </section>
  );
}
