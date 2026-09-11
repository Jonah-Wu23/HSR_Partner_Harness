import { useEffect, useRef, useState } from "react";
import {
  DIALOGUE_PROVIDERS,
  DIALOGUE_PROVIDER_IDS,
  type DialogueProviderId,
} from "../settings/dialogueProviders";

interface OnboardingProps {
  /** 选文件夹并创建第一个项目；返回 false 表示用户取消。 */
  onCreateProject: () => Promise<boolean>;
  /** 保存角色模型配置并测试连接；返回人话结果。 */
  onSaveModelConfig: (config: {
    provider: DialogueProviderId;
    apiKey: string;
    baseUrl?: string;
    model?: string;
  }) => Promise<string>;
  onFinish: () => void;
}

/** 首次引导三步：建项目 → 配模型 → 完成。任何一步可跳过。 */
export function Onboarding({ onCreateProject, onSaveModelConfig, onFinish }: OnboardingProps) {
  const [step, setStep] = useState(0);
  const [projectDone, setProjectDone] = useState(false);
  const [provider, setProvider] = useState<DialogueProviderId>(DIALOGUE_PROVIDER_IDS[0]);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(DIALOGUE_PROVIDERS.openai_compatible.baseUrl);
  const [model, setModel] = useState(DIALOGUE_PROVIDERS.openai_compatible.model);
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

  const saveModelConfig = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await onSaveModelConfig({
        provider,
        apiKey,
        ...(provider === "openai_compatible"
          ? { baseUrl: baseUrl.trim(), model: model.trim() }
          : {}),
      });
      if (!mountedRef.current) return;
      setTestResult(result);
      if (result.startsWith("连接正常")) setStep(2);
    } catch (error) {
      if (!mountedRef.current) return;
      setTestResult(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setTesting(false);
    }
  };

  const needsEndpointFields = provider === "openai_compatible";
  const canSubmit =
    !testing &&
    Boolean(apiKey) &&
    (!needsEndpointFields || (Boolean(baseUrl.trim()) && Boolean(model.trim())));

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
            <select
              value={provider}
              onChange={(event) => setProvider(event.target.value as DialogueProviderId)}
            >
              {DIALOGUE_PROVIDER_IDS.map((id) => (
                <option key={id} value={id}>
                  {DIALOGUE_PROVIDERS[id].label}
                </option>
              ))}
            </select>
          </label>
          {needsEndpointFields ? (
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
          <label className="field">
            <span className="field-label">API Key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>
          {testResult ? (
            <p
              className={testResult.startsWith("连接正常") ? "field-ok" : "field-error"}
              role="status"
            >
              {testResult}
            </p>
          ) : null}
          <div className="onboarding-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canSubmit}
              onClick={() => void saveModelConfig()}
            >
              {testing ? "正在连接…" : "保存并测试"}
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
