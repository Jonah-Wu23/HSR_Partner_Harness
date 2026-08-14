import { useState } from "react";

import type { HarnessActions } from "../contracts/actions";
import type { AppShellViewModel } from "../contracts/view-models";
import { TopBar } from "./TopBar";
import { Navigation } from "./navigation/Navigation";
import { Workspace } from "./workspace/Workspace";
import { ApprovalBar } from "./approval/ApprovalBar";
import { Composer } from "./composer/Composer";
import { QueueStrip } from "./status/QueueStrip";
import { TechDetailsDrawer } from "./status/TechDetailsDrawer";
import { ToastStack } from "./status/ToastStack";
import { AccountGate } from "./gate/AccountGate";
import { Onboarding } from "./gate/Onboarding";
import { SettingsCenter, type SettingsPage } from "./settings/SettingsCenter";
import type { TestResult } from "./settings/types";
import type { ConnectionViewStatus } from "./status/types";

import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/app.css";
import "../styles/status.css";
import "../styles/settings.css";

interface AppShellProps {
  vm: AppShellViewModel;
  actions: HarnessActions;
}

function StatePage({ title, detail }: { title: string; detail?: string | null }) {
  return (
    <div className="app-state-page">
      <h1>{title}</h1>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}

/** 试连接/试听的三态推进：testing → 结果映射 → 失败兜底。 */
function runTest(
  setResult: (result: TestResult) => void,
  task: () => Promise<unknown>,
  toResult: (value: unknown) => TestResult,
): void {
  setResult({ state: "testing" });
  void task()
    .then((value) => setResult(toResult(value)))
    .catch((error: unknown) =>
      setResult({ state: "failed", text: error instanceof Error ? error.message : String(error) }),
    );
}

/** 把后端连接状态翻译成界面的三态药丸。 */
function toConnectionStatus(status: AppShellViewModel["status"]): ConnectionViewStatus {
  if (status === "ready") return "connected";
  if (status === "booting") return "connecting";
  return "disconnected";
}

/**
 * 视觉根组件：只消费 ViewModel 与 HarnessActions，不触碰 store / 协议。
 * 搭档色走 tokens.css 的双主题令牌（白厄色值有测试锁定）；
 * 不做 PairRecord.theme 内联注入——它会覆盖浅色主题的搭档色调整，
 * 多搭档配色接入时在令牌层统一扩展。
 *
 * 断线不再接管整屏：已有界面保持可用，状态由连接药丸与技术详情抽屉承接；
 * 只有启动期（尚无 navigation 数据）失败才整屏。
 */
export function AppShell({ vm, actions }: AppShellProps) {
  const activeConv = vm.navigation?.projects
    .flatMap((p) => p.conversations)
    .find((c) => c.conversation_id === vm.navigation?.currentConversationId);
  const activePair =
    vm.navigation?.pairs?.find((p) => p.pair_id === activeConv?.pair_id) ??
    vm.navigation?.currentPair ??
    null;
  const pair = activePair ?? vm.navigation?.currentPair ?? null;
  const [techDetailsOpen, setTechDetailsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsPage, setSettingsPage] = useState<SettingsPage>("account");
  // V0.2 M4：设置中心以 key 重挂载——每次打开拉取 config.get 后重新水合表单
  const [settingsRevision, setSettingsRevision] = useState(0);
  // V0.2 M4：QueueStrip「编辑」拉回输入区的草稿（nonce 驱动 Composer 写入）
  const [draftSeed, setDraftSeed] = useState<{ text: string; nonce: number } | null>(null);
  // 账号门就地错误（登录/注册失败不清表单）
  const [gateError, setGateError] = useState<string | null>(null);
  // 「保存并测试」/「试听」三态结果（组件只消费 props，初值 idle）
  const [modelTest, setModelTest] = useState<TestResult>({ state: "idle" });
  const [voicePreview, setVoicePreview] = useState<TestResult>({ state: "idle" });
  const connectionStatus = toConnectionStatus(vm.status);

  const openSettings = () => {
    setSettingsOpen(true);
    // V0.2 M4：打开时拉取 config.get；结果到达后重挂载表单水合最新配置
    void actions.getConfig().finally(() => setSettingsRevision((revision) => revision + 1));
  };

  // 登录/注册失败 → 就地显示错误（保持账号门表单不丢失输入）
  const runGateAction = async (task: () => Promise<unknown>) => {
    setGateError(null);
    try {
      await task();
    } catch (error) {
      setGateError(error instanceof Error ? error.message : String(error));
    }
  };

  let body: React.ReactNode;
  if (vm.status === "booting") {
    body = <StatePage title="初始化中…" detail="正在唤醒本地服务…" />;
  } else if (vm.status === "error" && !vm.navigation) {
    body = <StatePage title="启动失败" detail={vm.error ?? "未知错误"} />;
  } else if (vm.accountGate) {
    // V0.2 M4：默认账号（未设密码）→ 整屏账号门
    body = (
      <AccountGate
        accounts={vm.accountGate.accounts}
        error={gateError ?? vm.accountGate.error}
        busy={vm.accountGate.busy}
        onLogin={(accountId, password) => void runGateAction(() => actions.loginAccount(accountId, password))}
        onRegister={(displayName, password) => void runGateAction(() => actions.registerAccount(displayName, displayName, password))}
      />
    );
  } else if (vm.onboarding) {
    // V0.2 M4：非默认账号且引导未完成 → 整屏首次引导
    body = (
      <Onboarding
        characterName={pair?.character.name ?? "角色"}
        assistantName={pair?.assistant.name ?? "助手"}
        onCreateProject={async () => {
          await actions.createProject();
          return true;
        }}
        onSaveModelConfig={async ({ provider, apiKey, baseUrl, model }) => {
          if (provider === "OpenAI OAuth") {
            await actions.setConfig({
              engine: "codex",
              "dialogue.provider": "openai_oauth",
              "dialogue.base_url": "https://api.openai.com/v1",
              "dialogue.model": "gpt-5.6-sol",
            });
            await actions.codexOauthStart();
            return "已启动 OpenAI OAuth，请在浏览器完成登录后继续";
          }

          const isDeepSeek = provider === "DeepSeek";
          const updates: Record<string, string> = isDeepSeek
            ? {
                engine: "deepseek",
                "dialogue.provider": "deepseek",
                "dialogue.base_url": "https://api.deepseek.com",
                "dialogue.model": "deepseek-v4-flash",
                "dialogue.api_key": apiKey,
              }
            : {
                engine: "codex",
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": baseUrl?.trim() || "https://api.openai.com/v1",
                "dialogue.model": model?.trim() || "gpt-5.6-sol",
                "dialogue.api_key": apiKey,
              };
          await actions.setConfig(updates);
          if (!isDeepSeek) await actions.codexApiLogin(apiKey);
          return actions.testConnection();
        }}
        onFinish={() => void actions.completeOnboarding()}
      />
    );
  } else if (!vm.navigation) {
    body = <StatePage title="暂无打开的项目" detail="等待项目数据" />;
  } else {
    const workspace = vm.workspace;
    body = (
      <>
        <TopBar
          mode={workspace?.mode ?? "chat"}
          pair={pair}
          assistantBusy={workspace?.assistant.busy ?? false}
          connectionStatus={connectionStatus}
          onOpenTechDetails={() => setTechDetailsOpen(true)}
          onOpenSettings={openSettings}
          actions={actions}
        />
        <div className="app-body">
          <Navigation navigation={vm.navigation} theme={vm.theme} actions={actions} />
          <main className="workspace">
            {vm.status === "disconnected" || vm.status === "error" ? (
              <div className="connection-banner" role="alert">
                与本地服务失去连接，正在重试。已加载的对话不受影响，发送的消息会在恢复后处理。
                <button type="button" onClick={() => setTechDetailsOpen(true)}>
                  查看技术详情
                </button>
              </div>
            ) : null}
            {workspace ? (
              <Workspace
                workspace={workspace}
                pair={pair ?? vm.navigation.currentPair}
                onQuickTask={(text) => void actions.submitMessage(text, "assistant")}
                onCloseWorkbench={() => actions.switchMode("chat")}
                onCancelDelegation={() => void actions.cancelTask()}
              />
            ) : (
              <div className="workspace-split">
                <div className="app-state-page">
                  <h1>没有打开的聊天</h1>
                  <p>在左侧新建或选择一个聊天开始</p>
                </div>
              </div>
            )}
            <ApprovalBar approval={vm.approval} actions={actions} />
            {/* V0.2 M4：排队条——忙碌时发送的消息在此可见可操作（空队列不渲染） */}
            <QueueStrip
              items={vm.queueItems}
              names={{
                character: pair?.character.name ?? "角色",
                assistant: pair?.assistant.name ?? "助手",
              }}
              onEdit={async (queueItemId) => {
                const text = await actions.editQueueFromStrip(queueItemId);
                if (text) setDraftSeed({ text, nonce: Date.now() });
              }}
              onWithdraw={(queueItemId) => void actions.withdrawQueueItem(queueItemId)}
              onPrioritize={(queueItemId) => void actions.prioritizeQueueItem(queueItemId)}
            />
            <Composer
              composer={vm.composer}
              voice={vm.voice}
              mode={workspace?.mode ?? "chat"}
              actions={actions}
              voiceMiniPlayer={vm.voiceMiniPlayer}
              draftSeed={draftSeed}
            />
          </main>
        </div>
        <TechDetailsDrawer
          open={techDetailsOpen}
          status={connectionStatus}
          details={{ lastError: vm.error }}
          onClose={() => setTechDetailsOpen(false)}
          onReconnect={() => void actions.reconnect()}
        />
      </>
    );
  }

  return (
    <div className="app-shell" data-theme={vm.theme} data-pair={vm.currentPairId} data-testid="app-shell">
      {body}
      {/* V0.2 M4：Toast 队列（右上角）；空队列不渲染 */}
      <ToastStack
        toasts={vm.toasts}
        onDismiss={(id) => actions.dismissToast(id)}
        onOpenDetails={() => setTechDetailsOpen(true)}
      />
      {/* V0.2 M4：设置中心（打开时拉取 config.get；key 保证每次打开表单水合） */}
      <SettingsCenter
        key={settingsRevision}
        open={settingsOpen}
        page={settingsPage}
        onPageChange={setSettingsPage}
        onClose={() => setSettingsOpen(false)}
        account={vm.settings.account}
        coding={vm.settings.coding}
        model={vm.settings.model}
        voice={vm.settings.voice}
        modelTest={modelTest}
        voicePreview={voicePreview}
        onSaveProfile={(displayName) => void actions.updateAccountProfile(displayName)}
        onChangePassword={(oldPassword, newPassword) =>
          void actions.changePassword(oldPassword, newPassword)
        }
        onLogout={() => void actions.logoutAccount()}
        onCodexOAuthStart={() => actions.codexOauthStart()}
        onCodexLogout={() => void actions.codexLogout()}
        onCodexApiLogin={(apiKey) => void actions.codexApiLogin(apiKey)}
        onSaveModel={async (config) => {
          const updates: Record<string, string> = {
            "dialogue.provider": config.provider,
            "dialogue.base_url": config.baseUrl,
            "dialogue.model": config.model,
          };
          if (config.apiKey) updates["dialogue.api_key"] = config.apiKey;
          await actions.setConfig(updates);
          if (config.provider === "openai_oauth") await actions.codexOauthStart();
        }}
        onTestModel={() =>
          runTest(setModelTest, () => actions.testConnection(), (value) => {
            const text = String(value ?? "");
            return { state: text.startsWith("连接正常") ? "ok" : "failed", text };
          })
        }
        onSaveVoice={(config) => {
          // 语音页只有开关类偏好可存；API Key/模型/音色由应用内置
          void actions.setConfig({
            "voice.enabled": String(config.enabled),
            "assistant_voice_enabled": String(config.assistantVoiceEnabled),
            "vad_enabled": String(config.vadEnabled),
          });
          // VAD 开关立即作用于运行时；语音关闭时停止聆听
          void actions.setVadEnabled(config.enabled ? config.vadEnabled : false);
        }}
        onPreviewVoice={(voiceId, voiceName) =>
          // V0.2 M4：试听入队即返回成功（合成结果由 voice 状态机接管）
          runTest(
            setVoicePreview,
            () => actions.voicePreview(`你好，我是${voiceName || "角色"}。这是语音试听。`, voiceId),
            () => ({ state: "ok", text: "已加入播放队列" }),
          )
        }
      />
    </div>
  );
}
