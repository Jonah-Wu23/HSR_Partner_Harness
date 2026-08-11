import type { HarnessActions } from "../contracts/actions";
import type { AppShellViewModel } from "../contracts/view-models";
import { TopBar } from "./TopBar";
import { Navigation } from "./navigation/Navigation";
import { Workspace } from "./workspace/Workspace";
import { ApprovalBar } from "./approval/ApprovalBar";
import { Composer } from "./composer/Composer";

import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/app.css";

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

/**
 * 视觉根组件：只消费 ViewModel 与 HarnessActions，不触碰 store / 协议。
 * 搭档色走 tokens.css 的双主题令牌（白厄色值有测试锁定）；
 * 不做 PairRecord.theme 内联注入——它会覆盖浅色主题的搭档色调整，
 * 多搭档配色接入时在令牌层统一扩展。
 */
export function AppShell({ vm, actions }: AppShellProps) {
  const pair = vm.navigation?.currentPair ?? null;

  let body: React.ReactNode;
  if (vm.status === "booting") {
    body = <StatePage title="初始化中…" detail="正在连接本地后端" />;
  } else if (vm.status === "disconnected") {
    body = <StatePage title="后端连接已断开" detail="请确认本地服务仍在运行，然后重启应用" />;
  } else if (vm.status === "error") {
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
          actions={actions}
        />
        <div className="app-body">
          <Navigation navigation={vm.navigation} theme={vm.theme} actions={actions} />
          <main className="workspace">
            {workspace ? (
              <Workspace workspace={workspace} pair={vm.navigation.currentPair} />
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
      </>
    );
  }

  return (
    <div className="app-shell" data-theme={vm.theme} data-testid="app-shell">
      {body}
    </div>
  );
}
