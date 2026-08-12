import type { HarnessActions } from "../contracts/actions";
import type { PairRecord } from "../contracts/protocol";
import { StopIcon } from "../assets/icons/icons";

interface TopBarProps {
  mode: "chat" | "collaboration";
  pair: PairRecord | null;
  assistantBusy: boolean;
  actions: HarnessActions;
}

/** 顶栏：品牌与搭档、聊天/协作切换、任务取消。 */
export function TopBar({ mode, pair, assistantBusy, actions }: TopBarProps) {
  return (
    <header className="app-topbar">
      <div className="topbar-brand">
        <span className="topbar-title">Pair Harness</span>
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

      <button
        type="button"
        className="btn btn-danger-outline"
        disabled={!assistantBusy}
        onClick={() => void actions.cancelTask()}
        title={assistantBusy ? "取消当前任务" : "当前没有运行中的任务"}
      >
        <StopIcon />
        取消任务
      </button>
    </header>
  );
}
