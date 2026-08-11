import type { CSSProperties } from "react";
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

/** 视觉根组件：只消费 ViewModel 与 HarnessActions，不触碰 store / 协议。 */
export function AppShell({ vm, actions }: AppShellProps) {
  const pair = vm.navigation?.currentPair ?? null;
  const themeVars = pair
    ? ({
        "--pair-character": pair.theme.character_primary,
        "--pair-character-deep": pair.theme.character_deep,
        "--pair-character-text": pair.theme.character_text,
        "--pair-assistant": pair.theme.assistant_primary,
        "--pair-assistant-deep": pair.theme.assistant_shadow,
        "--pair-assistant-text": pair.theme.assistant_bright,
      } as CSSProperties)
    : undefined;

  let body: React.ReactNode;
  if (vm.status === "booting") {
    body = <StatePage title="初始化中…" detail="正在连接本地后端" />;
  } else if (vm.status === "disconnected") {
    body = <StatePage title="后端连接已断开" detail="请确认本地服务仍在运行，然后重启应用" />;
  } else if (vm.status === "error") {
    body = <StatePage title="启动失败" detail={vm.error ?? "未知错误"} />;
  } else if (!vm.navigation || !vm.workspace) {
    body = <StatePage title="暂无打开的项目" detail="等待项目数据" />;
  } else {
    body = (
      <>
        <TopBar
          mode={vm.workspace.mode}
          pair={pair}
          assistantBusy={vm.workspace.assistant.busy}
          actions={actions}
        />
        <div className="app-body">
          <Navigation navigation={vm.navigation} theme={vm.theme} actions={actions} />
          <main className="workspace">
            <Workspace workspace={vm.workspace} pair={vm.navigation.currentPair} />
            <ApprovalBar approval={vm.approval} actions={actions} />
            <Composer
              composer={vm.composer}
              voice={vm.voice}
              mode={vm.workspace.mode}
              actions={actions}
            />
          </main>
        </div>
      </>
    );
  }

  return (
    <div className="app-shell" data-theme={vm.theme} data-testid="app-shell" style={themeVars}>
      {body}
    </div>
  );
}
