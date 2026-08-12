import { useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { NavigationViewModel } from "../../contracts/view-models";
import { CollapseIcon } from "../../assets/icons/icons";
import { ChatColumn } from "./ChatColumn";
import { ProjectRail } from "./ProjectRail";

interface NavigationProps {
  navigation: NavigationViewModel;
  theme: "dark" | "light";
  actions: HarnessActions;
}

/** 双层导航：56px 项目轨道 + 224px 聊天栏，聊天栏可整体收起。 */
export function Navigation({ navigation, theme, actions }: NavigationProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <nav className="app-nav">
      <ProjectRail navigation={navigation} actions={actions} />
      <div className={`chat-column${collapsed ? " is-collapsed" : ""}`} aria-hidden={collapsed}>
        <ChatColumn
          navigation={navigation}
          theme={theme}
          actions={actions}
          onCollapse={() => setCollapsed(true)}
        />
      </div>
      {collapsed ? (
        <button
          type="button"
          className="icon-btn nav-expand"
          onClick={() => setCollapsed(false)}
          title="展开聊天栏"
          aria-label="展开聊天栏"
        >
          <CollapseIcon style={{ transform: "rotate(180deg)" }} />
        </button>
      ) : null}
    </nav>
  );
}
