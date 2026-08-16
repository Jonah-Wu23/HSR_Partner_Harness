import { useEffect, useRef, useState } from "react";
import type { CodexOAuthStatus } from "../../contracts/actions";

interface OnboardingProps {
  /** 选文件夹并创建第一个项目；返回 false 表示用户取消。 */
  onCreateProject: () => Promise<boolean>;
  /** 保存角色模型配置并测试连接；返回人话结果。 */
  onSaveModelConfig: (config: {
    provider: string;
    apiKey: string;
    baseUrl?: string;
    model?: string;
  }) => Promise<string>;
  /** OAuth 启动后轮询登录状态；仅确认 logged_in 才允许进入下一步。 */
  onCheckOAuthStatus?: () => Promise<CodexOAuthStatus>;
  onFinish: () => void;
}

const PROVIDERS = ["DeepSeek", "OpenAI 兼容 API（包括 OpenAI API）", "OpenAI OAuth"];
const OPENAI_BASE_URL = "https://api.openai.com/v1";
const OPENAI_MODEL = "gpt-5.6-sol";
const OAUTH_POLL_INTERVAL_MS = 1500;

/** 首次引导三步：建项目 → 配模型 → 完成。任何一步可跳过。 */
export function Onboarding({
  onCreateProject,
  onSaveModelConfig,
  onCheckOAuthStatus,
  onFinish,
}: OnboardingProps) {
  const [step, setStep] = useState(0);
  const [projectDone, setProjectDone] = useState(false);
  const [provider, setProvider] = useState(PROVIDERS[0]);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(OPENAI_BASE_URL);
  const [model, setModel] = useState(OPENAI_MODEL);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const createProject = async () => {
    setProjectError(null);
    setTesting(true);
    try {
      const created = await onCreateProject();
      if (!mountedRef.current) return;
      if (created) {
        setProjectDone(true);
        setStep(1);
      }
    } catch (error) {
      if (!mountedRef.current) return;
      setProjectError(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setTesting(false);
    }
  };

  const waitForOAuthLogin = async () => {
    if (!onCheckOAuthStatus) return false;
    // 轮询直到真实 logged_in；失败时抛错由外层展示并停留在当前步骤。
    // 不设超时：用户可能长时间停留在浏览器登录页，离开页面由 unmount 停止。
    while (mountedRef.current) {
      const status = await onCheckOAuthStatus();
      if (!mountedRef.current) return false;
      if (status.status === "logged_in") {
        setTestResult("OpenAI OAuth 登录成功");
        setStep(2);
        return true;
      }
      await new Promise((resolve) => setTimeout(resolve, OAUTH_POLL_INTERVAL_MS));
    }
    return false;
  };

  const saveModelConfig = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await onSaveModelConfig({
        provider,
        apiKey,
        ...(provider === "OpenAI 兼容 API（包括 OpenAI API）"
          ? { baseUrl: baseUrl.trim(), model: model.trim() }
          : {}),
      });
      if (!mountedRef.current) return;
      if (result.startsWith("连接正常")) {
        setTestResult(result);
        setStep(2);
        return;
      }
      if (result.startsWith("已启动 OpenAI OAuth")) {
        setTestResult(result);
        await waitForOAuthLogin();
        return;
      }
      setTestResult(result);
    } catch (error) {
      if (!mountedRef.current) return;
      setTestResult(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setTesting(false);
    }
  };

  return (
    <div className="onboarding">
      <ol className="onboarding-steps" aria-label="引导进度">
        {["创建第一个项目", "配置角色模型", "完成"].map((label, index) => (
          <li key={label} className={index === step ? "is-current" : index < step ? "is-done" : ""}>
            {label}
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <section className="onboarding-panel">
          <h2>创建第一个项目</h2>
          <p className="onboarding-hint">项目就是你想让助手帮忙干活的文件夹。</p>
          {projectError ? (
            <p className="field-error" role="alert">
              {projectError}
            </p>
          ) : null}
          <div className="onboarding-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={testing}
              onClick={() => void createProject()}
            >
              {projectDone ? "已创建，重新选择" : "选择文件夹"}
            </button>
            <button type="button" className="btn btn-outline" onClick={() => setStep(1)}>
              跳过
            </button>
          </div>
        </section>
      ) : null}

      {step === 1 ? (
        <section className="onboarding-panel">
          <h2>配置角色模型</h2>
          <p className="onboarding-hint">角色需要一个对话模型才能开口。之后可以在设置中心随时修改。</p>
          <label className="field">
            <span className="field-label">模型来源</span>
            <select value={provider} onChange={(event) => setProvider(event.target.value)}>
              {PROVIDERS.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          {provider === "OpenAI 兼容 API（包括 OpenAI API）" ? (
            <>
              <label className="field">
                <span className="field-label">Base URL</span>
                <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
              </label>
              <label className="field">
                <span className="field-label">模型</span>
                <input value={model} onChange={(event) => setModel(event.target.value)} />
              </label>
            </>
          ) : null}
          {provider === "OpenAI OAuth" ? (
            <p className="onboarding-hint">使用 OpenAI 账号登录，角色与助手共用 gpt-5.6-sol。</p>
          ) : (
            <label className="field">
              <span className="field-label">API Key</span>
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </label>
          )}
          {testResult ? (
            <p
              className={
                testResult.startsWith("连接正常") || testResult.startsWith("已启动")
                  ? "field-ok"
                  : "field-error"
              }
              role="status"
            >
              {testResult}
            </p>
          ) : null}
          <div className="onboarding-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={
                testing ||
                (provider !== "OpenAI OAuth" &&
                  (!apiKey ||
                    (provider === "OpenAI 兼容 API（包括 OpenAI API）" &&
                      (!baseUrl.trim() || !model.trim()))))
              }
              onClick={() => void saveModelConfig()}
            >
              {testing
                ? provider === "OpenAI OAuth"
                  ? "正在等待登录…"
                  : "正在连接…"
                : provider === "OpenAI OAuth"
                  ? "启动并继续"
                  : "保存并测试"}
            </button>
            <button
              type="button"
              className="btn btn-outline"
              disabled={testing}
              onClick={() => setStep(2)}
            >
              跳过，之后再说
            </button>
          </div>
        </section>
      ) : null}

      {step === 2 ? (
        <section className="onboarding-panel">
          <h2>都准备好了</h2>
          <p className="onboarding-hint">
            角色随时陪你聊天；切到协作模式，助手就能读写你的项目。
          </p>
          <div className="onboarding-actions">
            <button type="button" className="btn btn-primary" onClick={onFinish}>
              开始使用
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
