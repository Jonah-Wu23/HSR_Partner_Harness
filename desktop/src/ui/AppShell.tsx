import { useCallback, useMemo, useState } from "react";

import type { HarnessActions } from "../contracts/actions";
import type { AppShellViewModel } from "../contracts/view-models";
import type { DesktopBackend } from "../services/backend";
import { selectConversationCharacterIdentity } from "../presenters/presenters";
import { useDesktopStore } from "../stores/desktopStore";
import { TopBar } from "./TopBar";
import { Navigation } from "./navigation/Navigation";
import { Workspace } from "./workspace/Workspace";
import { ChatTabs } from "./ChatTabs";
import { ApprovalBar } from "./approval/ApprovalBar";
import { Composer } from "./composer/Composer";
import { QueueStrip } from "./status/QueueStrip";
import { TechDetailsDrawer } from "./status/TechDetailsDrawer";
import { ToastStack } from "./status/ToastStack";
import { ContextStatusStripHost } from "./status/ContextStatusStripHost";
import { DiagnosticsDrawerHost } from "./diagnostics/DiagnosticsDrawerHost";
import { AccountGate } from "./gate/AccountGate";
import { Onboarding } from "./gate/Onboarding";
import { SettingsCenter, type SettingsPage } from "./settings/SettingsCenter";
import { DIALOGUE_PROVIDERS } from "./settings/dialogueProviders";
import { PowerPrompt } from "./power/PowerPrompt";
import { CharacterLibraryPage } from "./character-library/CharacterLibraryPage";
import { CharacterCreatePage } from "./character-create/CharacterCreatePage";
import type { TestResult } from "./settings/types";
import type { ConnectionViewStatus } from "./status/types";

import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/app.css";
import "../styles/status.css";
import "../styles/settings.css";
import "../styles/characters.css";

interface AppShellProps {
  vm: AppShellViewModel;
  actions: HarnessActions;
  /** 文件选择与保存对话框（pickFile/saveFile），供角色库导入导出、创作页头像、
      语音页参考音频使用。 */
  backend: DesktopBackend;
}

function StatePage({ title, detail }: { title: string; detail?: string | null }) {
  return (
    <div className="app-state-page">
      <h1>{title}</h1>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}

/** 试连接与试听的三态推进：先 testing，再映射结果；请求失败显示错误原文。 */
function runTest<T>(
  setResult: (result: TestResult) => void,
  task: () => Promise<T>,
  toResult: (value: T) => TestResult,
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
 * 视觉根组件：消费 ViewModel 与 HarnessActions。
 * 搭档色走 tokens.css 的双主题令牌（按 data-pair 切换），浅色主题的搭档色调整也在令牌层。
 *
 * 断线时已有界面保持可用，状态由连接药丸与技术详情抽屉显示；
 * 只有启动期（尚无 navigation 数据）失败才整屏显示错误。
 */
export function AppShell({ vm, actions, backend }: AppShellProps) {
  const navigation = vm.navigation;
  const pair = useMemo(() => {
    if (!navigation) return null;
    const activeConv = navigation.projects
      .flatMap((p) => p.conversations)
      .find((c) => c.conversation_id === navigation.currentConversationId);
    return navigation.pairs.find((p) => p.pair_id === activeConv?.pair_id) ?? navigation.currentPair;
  }, [navigation]);
  // 本窗口活动会话的角色展示身份：会话 character_identity 优先，旧会话回退内置搭档。
  // 顶栏、工作区标题、消息署名、委派来源、排队条与语音条共用这一解析。
  const activeCharacterName = useDesktopStore(
    (state) =>
      selectConversationCharacterIdentity(
        state,
        vm.workspace?.character.conversationId ?? null,
      )?.name ?? "",
  );
  const [techDetailsOpen, setTechDetailsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsPage, setSettingsPage] = useState<SettingsPage>("account");
  // 角色库「配置音色」直达语音页并预选该卡；null 表示无预选。
  const [voiceCardFocus, setVoiceCardFocus] = useState<string | null>(null);
  // 设置中心以 key 重挂载：每次打开拉取 config.get 后重新水合表单。
  const [settingsRevision, setSettingsRevision] = useState(0);
  // 队列条「编辑」拉回输入区的草稿，nonce 驱动 Composer 写入。
  const [draftSeed, setDraftSeed] = useState<{ text: string; nonce: number } | null>(null);
  // 账号门就地错误，登录或注册失败不清表单。
  const [gateError, setGateError] = useState<string | null>(null);
  // 默认账号（未设密码）登录成功后关掉账号门。账号门按「当前账号 username=default」判定，
  // 登录默认账号不改变账号身份，需要这个标记区分冷启动与已进入；退出登录时重置。
  const [gateEntered, setGateEntered] = useState(false);
  // 「保存并测试」与「试听」的三态结果。
  const [modelTest, setModelTest] = useState<TestResult>({ state: "idle" });
  const [voicePreview, setVoicePreview] = useState<TestResult>({ state: "idle" });
  const connectionStatus = toConnectionStatus(vm.status);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);

  // 传给 memo 区域的回调保持稳定引用，流式事件批次不会让这些区域重渲染。
  const openSettings = useCallback(() => {
    setSettingsOpen(true);
    // 每次打开设置都清掉上一轮的测试、试听结果与角色库直达的预选卡。
    setModelTest({ state: "idle" });
    setVoicePreview({ state: "idle" });
    setVoiceCardFocus(null);
    void actions.getConfig().finally(() => setSettingsRevision((revision) => revision + 1));
  }, [actions]);
  const openTechDetails = useCallback(() => setTechDetailsOpen(true), []);
  const openDiagnostics = useCallback(() => setDiagnosticsOpen(true), []);
  const closeDiagnostics = useCallback(() => setDiagnosticsOpen(false), []);
  const selectTab = useCallback(
    (conversationId: string) => void actions.openConversationTab(conversationId),
    [actions],
  );
  const closeTab = useCallback(
    (conversationId: string) => actions.closeConversationTab(conversationId),
    [actions],
  );
  const openTabWindow = useCallback(
    (conversationId: string) => void actions.openConversationWindow(conversationId),
    [actions],
  );
  const submitQuickTask = useCallback(
    (text: string) => void actions.submitMessage(text, "assistant"),
    [actions],
  );
  const closeWorkbench = useCallback(() => actions.switchMode("chat"), [actions]);
  const cancelDelegation = useCallback(() => void actions.cancelTask(), [actions]);
  const editQueueItem = useCallback(
    async (queueItemId: string) => {
      const text = await actions.editQueueFromStrip(queueItemId);
      if (text) setDraftSeed({ text, nonce: Date.now() });
    },
    [actions],
  );
  const withdrawQueueItem = useCallback(
    (queueItemId: string) => void actions.withdrawQueueItem(queueItemId),
    [actions],
  );
  const prioritizeQueueItem = useCallback(
    (queueItemId: string) => void actions.prioritizeQueueItem(queueItemId),
    [actions],
  );
  const dismissToast = useCallback((id: string) => actions.dismissToast(id), [actions]);
  const queueNames = useMemo(
    () => ({
      character: activeCharacterName || pair?.character.name || "角色",
      assistant: pair?.assistant.name ?? "助手",
    }),
    [activeCharacterName, pair],
  );

  // 从角色库或创作页直达语音页「角色音色」区并预选卡片。
  const openSettingsToVoiceCard = (cardId: string | null) => {
    // 先走普通打开流程（含清预选），再设置本次预选，顺序不可颠倒。
    openSettings();
    setVoiceCardFocus(cardId);
    setSettingsPage("voice");
  };

  // 登录或注册失败时就地显示错误，账号门表单保留输入。
  const runGateAction = async (task: () => Promise<unknown>) => {
    setGateError(null);
    try {
      await task();
      setGateEntered(true);
    } catch (error) {
      setGateError(error instanceof Error ? error.message : String(error));
    }
  };

  // 回到运行中的聊天：打开第一个有活动任务的聊天，再切回聊天视图。
  const handleReturnToRunningChat = () => {
    const running = navigation?.projects
      .flatMap((project) =>
        project.conversations.map((conversation) => ({ project, conversation })),
      )
      .find((item) => item.conversation.isRunning);
    if (running) {
      if (running.project.project_id !== navigation?.currentProjectId) {
        void actions.selectProject(running.project.project_id);
      }
      void actions.openConversationTab(running.conversation.conversation_id);
    }
    actions.openChat();
  };

  let body: React.ReactNode;
  if (vm.status === "booting") {
    body = <StatePage title="初始化中…" detail="正在唤醒本地服务…" />;
  } else if (vm.status === "error" && !vm.navigation) {
    body = <StatePage title="启动失败" detail={vm.error ?? "未知错误"} />;
  } else if (vm.accountGate && !gateEntered) {
    // 默认账号（未设密码）显示整屏账号门。
    body = (
      <AccountGate
        accounts={vm.accountGate.accounts}
        error={gateError ?? vm.accountGate.error}
        busy={vm.accountGate.busy}
        onLogin={(accountId, password) => void runGateAction(() => actions.loginAccount(accountId, password))}
        onRegister={(displayName, password) => void runGateAction(() => actions.registerAccount(displayName, displayName, password))}
        // 登录与注册表单互切时清掉上一轮错误。
        onClearError={() => setGateError(null)}
      />
    );
  } else if (vm.onboarding) {
    // 非默认账号且引导未完成时显示整屏首次引导。
    body = (
      <Onboarding
        onCreateProject={actions.createProject}
        // 只配置 Chat Completions 兼容端点；引擎由后端按 dialogue.provider 推导，
        // DeepSeek 不填地址与模型时用该服务商的默认值。
        onSaveModelConfig={async ({ provider, apiKey, baseUrl, model }) => {
          const defaults = DIALOGUE_PROVIDERS[provider];
          const updates: Record<string, string> = {
            "dialogue.provider": provider,
            "dialogue.base_url": baseUrl?.trim() || defaults.baseUrl,
            "dialogue.model": model?.trim() || defaults.model,
            "dialogue.api_key": apiKey,
          };
          await actions.setConfig(updates);
          return actions.testConnection();
        }}
        onFinish={() => actions.completeOnboarding()}
      />
    );
  } else if (!navigation) {
    body = <StatePage title="暂无打开的项目" detail="等待项目数据" />;
  } else {
    const workspace = vm.workspace;
    const totalRunningTasks = navigation.projects.reduce(
      (sum, project) => sum + project.activeTaskCount,
      0,
    );

    body = (
      <>
        <TopBar
          mode={workspace?.mode ?? "chat"}
          pair={pair}
          assistantBusy={workspace?.assistant.busy ?? false}
          connectionStatus={connectionStatus}
          onOpenTechDetails={openTechDetails}
          onOpenDiagnostics={openDiagnostics}
          onOpenSettings={openSettings}
          actions={actions}
        />
        <div className="app-body">
          <Navigation navigation={navigation} theme={vm.theme} actions={actions} />
          <main className="workspace">
            {/* 本窗口聊天标签栏：切换标签聚焦本窗口视图，关闭标签只移除视图。 */}
            <ChatTabs
              tabs={vm.chatTabs}
              onSelect={selectTab}
              onClose={closeTab}
              onOpenWindow={openTabWindow}
            />
            {vm.status === "disconnected" || vm.status === "error" ? (
              <div className="connection-banner" role="alert">
                {vm.status === "disconnected"
                  ? "与本地服务失去连接，恢复前无法发送消息。已加载的对话仍可查看。"
                  : `本地服务出错，暂时无法发送消息${vm.error ? `：${vm.error}` : "。"}`}
                <button type="button" onClick={() => setTechDetailsOpen(true)}>
                  查看技术详情
                </button>
              </div>
            ) : vm.resyncing ? (
              <div className="connection-banner" role="status">
                正在与本地服务重新同步…
              </div>
            ) : null}
            {vm.mainView === "characters" ? (
              <CharacterLibraryPage vm={vm.characterLibrary} actions={actions} onConfigureCardVoice={openSettingsToVoiceCard} backend={backend} onReturnToChat={handleReturnToRunningChat} />
            ) : vm.mainView === "characterCreate" ? (
              <CharacterCreatePage vm={vm.characterCreate} actions={actions} onPickFile={(options) => backend.pickFile(options)} onReturnToChat={handleReturnToRunningChat} />
            ) : workspace ? (
              <Workspace
                workspace={workspace}
                pair={pair ?? navigation.currentPair}
                characterName={
                  activeCharacterName || (pair ?? navigation.currentPair).character.name
                }
                onQuickTask={submitQuickTask}
                onCloseWorkbench={closeWorkbench}
                onCancelDelegation={cancelDelegation}
              />
            ) : (
              <div className="workspace-split">
                <div className="app-state-page">
                  <h1>没有打开的聊天</h1>
                  <p>在左侧新建或选择一个聊天开始</p>
                </div>
              </div>
            )}
            {/* 角色库与创作页隐藏发送区、排队条与审批条，保留返回运行中聊天的入口。 */}
            {vm.mainView !== "chat" ? (
              totalRunningTasks > 0 ? (
                <div className="non-chat-running-banner" data-testid="non-chat-running-banner">
                  <div className="non-chat-running-info">
                    <span className="badge-busy-dot" aria-hidden />
                    <span>后台有 {totalRunningTasks} 个任务正在运行中</span>
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleReturnToRunningChat}
                  >
                    返回运行中聊天
                  </button>
                </div>
              ) : null
            ) : (
              <>
                {/* 上下文状态条（压缩与记忆）位于输入区之上，无数据时不渲染。 */}
                <ContextStatusStripHost actions={actions} />
                <ApprovalBar
                  approval={vm.approval}
                  actions={actions}
                  currentConversationId={navigation.currentConversationId}
                />
                {/* 排队条：忙碌时发送的消息在此可见可操作，空队列不渲染。 */}
                <QueueStrip
                  items={vm.queueItems}
                  names={queueNames}
                  onEdit={editQueueItem}
                  onWithdraw={withdrawQueueItem}
                  onPrioritize={prioritizeQueueItem}
                />
                <Composer
                  composer={vm.composer}
                  voice={vm.voice}
                  mode={workspace?.mode ?? "chat"}
                  actions={actions}
                  voiceMiniPlayer={vm.voiceMiniPlayer}
                  draftSeed={draftSeed}
                />
              </>
            )}
          </main>
        </div>
        <TechDetailsDrawer
          open={techDetailsOpen}
          status={connectionStatus}
          details={{ lastError: vm.error }}
          onClose={() => setTechDetailsOpen(false)}
          onReconnect={() => void actions.reconnect()}
        />
        {/* 诊断抽屉（指标与提示词装配），由 TopBar 入口打开。 */}
        <DiagnosticsDrawerHost
          open={diagnosticsOpen}
          onClose={closeDiagnostics}
          actions={actions}
        />
      </>
    );
  }

  return (
    <div
      className="app-shell"
      data-theme={vm.theme}
      data-pair={vm.currentPairId ?? undefined}
      data-testid="app-shell"
    >
      {body}
      {/* Toast 队列（右上角），空队列不渲染。 */}
      <ToastStack toasts={vm.toasts} onDismiss={dismissToast} onOpenDetails={openTechDetails} />
      {/* 电源提示（右下角）：挂载时查询 power.get_status，之后由 power.status_changed 更新；
          无风险、已关闭或平台不支持时不渲染。 */}
      <PowerPrompt actions={actions} />
      {/* 设置中心：打开时拉取 config.get，key 保证每次打开都重新水合表单。 */}
      <SettingsCenter
        key={settingsRevision}
        open={settingsOpen}
        page={settingsPage}
        onPageChange={setSettingsPage}
        onClose={() => {
          setSettingsOpen(false);
          // 关闭时清掉音色预选卡，下次从齿轮打开不残留。
          setVoiceCardFocus(null);
        }}
        account={vm.settings.account}
        model={vm.settings.model}
        voice={vm.settings.voice}
        characterVoice={vm.settings.characterVoice}
        voiceCardFocus={voiceCardFocus}
        actions={actions}
        onPickFile={(options) => backend.pickFile(options)}
        modelTest={modelTest}
        voicePreview={voicePreview}
        remote={vm.remotePairing}
        onIssuePairingCode={() => void actions.issuePairingCode()}
        onListRemoteDevices={() => void actions.listRemoteDevices()}
        onRevokeRemoteDevice={(deviceName) => void actions.revokeRemoteDevice(deviceName)}
        onSaveProfile={(displayName) => actions.updateAccountProfile(displayName)}
        onChangePassword={(oldPassword, newPassword) =>
          actions.changePassword(oldPassword, newPassword)
        }
        onLogout={() => {
          // 退出登录回到账号门；默认账号无密码，仍可空密码进入。
          setGateEntered(false);
          void actions.logoutAccount();
        }}
        onSaveModel={async (config) => {
          const updates: Record<string, string> = {
            "dialogue.provider": config.provider,
            "dialogue.base_url": config.baseUrl,
            "dialogue.model": config.model,
          };
          if (config.apiKey) updates["dialogue.api_key"] = config.apiKey;
          // 角色模型推理等级写入 dialogue.reasoning_effort，编程助手的 project.reasoning_effort
          // 由 Composer 单独保存。只有 DeepSeek 端点有推理档位，其他服务商不写这一项。
          if (config.provider === "deepseek") {
            updates["dialogue.reasoning_effort"] = config.reasoningEffort;
          }
          await actions.setConfig(updates);
        }}
        onTestModel={() =>
          runTest(setModelTest, () => actions.testConnection(), (result) => ({
            state: result.ok ? "ok" : "failed",
            text: result.message,
          }))
        }
        onSaveVoice={(config) => {
          // 只写本次变化的键：凭据（Key/服务地址）变化会让后端重建语音运行时并打断朗读，
          // 开关偏好由 config.set 直接作用于运行时。Key 只由后端写入 secret_refs。
          const updates: Record<string, string> = {};
          if (config.enabled !== undefined) updates["voice.enabled"] = String(config.enabled);
          if (config.assistantVoiceEnabled !== undefined) {
            updates["assistant_voice_enabled"] = String(config.assistantVoiceEnabled);
          }
          if (config.vadEnabled !== undefined) updates["vad_enabled"] = String(config.vadEnabled);
          if (config.baseUrl !== undefined) updates["voice.base_url"] = config.baseUrl;
          if (config.apiKey) updates["voice.api_key"] = config.apiKey;
          return actions.setConfig(updates);
        }}
        onProvisionVoices={(speakerIds, replaceExisting) =>
          actions.provisionVoices(speakerIds, replaceExisting)
        }
        onPreviewVoice={(voiceId, voiceName) =>
          // 试听请求被接受即入播放队列，合成结果由 voice 状态显示。
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
