import { useState } from "react";

import type { HarnessActions } from "../contracts/actions";
import type { AppShellViewModel } from "../contracts/view-models";
import { TopBar } from "./TopBar";
import { Navigation } from "./navigation/Navigation";
import { Workspace } from "./workspace/Workspace";
import { ApprovalBar } from "./approval/ApprovalBar";
import { Composer } from "./composer/Composer";
import { TechDetailsDrawer } from "./status/TechDetailsDrawer";
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
  const pair = vm.navigation?.currentPair ?? null;
  const [techDetailsOpen, setTechDetailsOpen] = useState(false);
  const connectionStatus = toConnectionStatus(vm.status);

  let body: React.ReactNode;
  if (vm.status === "booting") {
    body = <StatePage title="初始化中…" detail="正在唤醒本地服务…" />;
  } else if (vm.status === "error" && !vm.navigation) {
    body = <StatePage title="启动失败" detail={vm.error ?? "未知错误"} />;
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
                pair={vm.navigation.currentPair}
                onQuickTask={(text) => void actions.submitMessage(text, "assistant")}
                onCloseWorkbench={() => actions.switchMode("chat")}
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
            <Composer
              composer={vm.composer}
              voice={vm.voice}
              mode={workspace?.mode ?? "chat"}
              actions={actions}
            />
          </main>
        </div>
        <TechDetailsDrawer
          open={techDetailsOpen}
          status={connectionStatus}
          details={{ lastError: vm.error }}
          onClose={() => setTechDetailsOpen(false)}
        />
      </>
    );
  }

  return (
    <div className="app-shell" data-theme={vm.theme} data-testid="app-shell">
      {body}
    </div>
  );
}
