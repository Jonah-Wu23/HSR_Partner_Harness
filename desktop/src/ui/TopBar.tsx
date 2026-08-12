import type { HarnessActions } from "../contracts/actions";
import type { PairRecord } from "../contracts/protocol";
import type { ConnectionViewStatus } from "./status/types";
import { ConnectionPill } from "./status/ConnectionPill";
import { StopIcon } from "../assets/icons/icons";

interface TopBarProps {
  mode: "chat" | "collaboration";
  pair: PairRecord | null;
  assistantBusy: boolean;
  connectionStatus: ConnectionViewStatus;
  onOpenTechDetails: () => void;
  actions: HarnessActions;
}

/** 状态条：连接药丸、品牌与搭档、聊天/协作切换；取消按钮只在忙碌时出现。 */
export function TopBar({
  mode,
  pair,
  assistantBusy,
  connectionStatus,
  onOpenTechDetails,
  actions,
}: TopBarProps) {
  return (
    <header className="app-topbar">
      <ConnectionPill status={connectionStatus} onOpenDetails={onOpenTechDetails} />

      <div className="topbar-brand">
        <span className="topbar-title">HSR Partner Harness</span>
        {pair ? (
          <span className="topbar-pair">
            <span className="pair-dot pair-dot-character" />
            {pair.character.name}
            <span aria-hidden>×</span>
            <span className="pair-dot pair-dot-assistant" />
            {pair.assistant.name}
          </span>
        ) : null}
      </div>

      <div className="topbar-spacer" />

      <div className="segmented" role="tablist" aria-label="模式切换">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "chat"}
          className={`segmented-item${mode === "chat" ? " is-selected" : ""}`}
          onClick={() => actions.switchMode("chat")}
        >
          聊天
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "collaboration"}
          className={`segmented-item${mode === "collaboration" ? " is-selected" : ""}`}
          onClick={() => actions.switchMode("collaboration")}
        >
          协作
        </button>
      </div>

      <div className="topbar-spacer" />

      {assistantBusy ? (
        <button
          type="button"
          className="btn btn-danger-outline"
          onClick={() => void actions.cancelTask()}
          title="取消当前任务"
        >
          <StopIcon />
          取消任务
        </button>
      ) : null}
    </header>
  );
}
