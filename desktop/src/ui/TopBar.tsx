import { memo } from "react";
import type { HarnessActions } from "../contracts/actions";
import type { PairRecord } from "../contracts/protocol";
import type { ConnectionViewStatus } from "./status/types";
import { ConnectionPill } from "./status/ConnectionPill";
import { DemoModeNotice } from "./status/DemoModeNotice";
import { SettingIcon, StopIcon } from "../assets/icons/icons";
import { getPairAvatars, useCardAvatar } from "../assets/pairs/avatars";
import {
  useDesktopStore,
  selectWindowCharacterCardId,
  selectWindowCharacterIdentity,
} from "../stores/desktopStore";

interface TopBarProps {
  mode: "chat" | "collaboration";
  pair: PairRecord | null;
  assistantBusy: boolean;
  connectionStatus: ConnectionViewStatus;
  onOpenTechDetails: () => void;
  /** 诊断抽屉入口（指标与提示词装配）。 */
  onOpenDiagnostics: () => void;
  /** 设置中心入口（右侧按钮）。 */
  onOpenSettings: () => void;
  actions: HarnessActions;
}

/** 状态条：连接药丸、品牌与搭档、聊天/协作切换；取消按钮只在忙碌时出现。 */
export const TopBar = memo(function TopBar({
  mode,
  pair,
  assistantBusy,
  connectionStatus,
  onOpenTechDetails,
  onOpenDiagnostics,
  onOpenSettings,
  actions,
}: TopBarProps) {
  // 本窗口活动会话的身份由后端统一解析：卡会话显示卡名与卡头像，缺失时退回几何占位。
  // 顶栏的 pair 来自按 pair_id 匹配的目录项，卡会话的 pair_id 指向 base 搭档，因此身份以会话记录为准。
  const characterIdentity = useDesktopStore(selectWindowCharacterIdentity);
  const characterCardId = useDesktopStore(selectWindowCharacterCardId);
  const isCardCharacter = characterIdentity?.source === "card" && characterIdentity.missing !== true;
  const cardAvatar = useCardAvatar(
    actions.fetchCardAvatar,
    isCardCharacter ? characterCardId : null,
    characterIdentity?.avatar_version ?? null,
  );
  const avatars = pair ? getPairAvatars(pair.pair_id) : null;
  const characterName = characterIdentity?.name || pair?.character.name || "";
  // 卡会话只用卡头像；卡头像未就绪时退回几何占位，不借用内置角色头像。
  const characterAvatar =
    cardAvatar ?? (characterIdentity?.source === "card" ? null : avatars?.character ?? null);

  return (
    <header className="app-topbar">
      <ConnectionPill status={connectionStatus} onOpenDetails={onOpenTechDetails} />
      {/* 演示模式标识与连接药丸并列，各自表达一件事 */}
      <DemoModeNotice />

      <div className="topbar-brand">
        <span className="topbar-title">HSR Partner Harness</span>
        {pair ? (
          <span className="topbar-pair">
            <span className="topbar-pair-avatars">
              {characterAvatar ? (
                <img src={characterAvatar} alt={characterName} className="topbar-avatar" />
              ) : (
                <span className="pair-dot pair-dot-character" />
              )}
              {avatars ? (
                <img src={avatars.assistant} alt={pair.assistant.name} className="topbar-avatar" />
              ) : (
                <span className="pair-dot pair-dot-assistant" />
              )}
            </span>
            <span className="topbar-pair-names">
              {characterName}
              <span aria-hidden>×</span>
              {pair.assistant.name}
            </span>
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

      <button
        type="button"
        className="btn btn-outline"
        onClick={onOpenDiagnostics}
        title="诊断（指标与提示词装配）"
        data-testid="topbar-diagnostics"
      >
        诊断
      </button>

      {/* 设置中心入口（打开时拉取 config.get） */}
      <button
        type="button"
        className="icon-btn"
        onClick={onOpenSettings}
        title="设置"
        aria-label="设置"
      >
        <SettingIcon />
      </button>
    </header>
  );
});
