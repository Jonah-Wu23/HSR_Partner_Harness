import { memo, useCallback, useMemo, useRef, useState, type CSSProperties } from "react";
import type { PairRecord } from "../../contracts/protocol";
import type {
  AssistantWorkbenchViewModel,
  ConversationTimelineViewModel,
  WorkbenchItem,
  WorkspaceViewModel,
} from "../../contracts/view-models";
import { MessageBubble, MessageList, renderJumpToLatest } from "./MessageList";
import { ConversationList, type ConversationItemState } from "../conversation/ConversationList";
import { ToolCard } from "./ToolCard";
import { DelegationCard, type DelegationCardView } from "./DelegationCard";
import { CollapseIcon } from "../../assets/icons/icons";

interface WorkspaceProps {
  workspace: WorkspaceViewModel;
  pair: PairRecord;
  /** 工作台空状态的快捷任务：以「交给助手」发出预设任务。 */
  onQuickTask?: (text: string) => void;
  /** 工作台头部收起按钮：等同切回聊天模式。 */
  onCloseWorkbench?: () => void;
  /** 委派卡取消回调（task.cancel）。 */
  onCancelDelegation?: () => void;
}

const WORKBENCH_MIN_PCT = 30;
const WORKBENCH_MAX_PCT = 60;

function clampWorkbenchPct(pct: number): number {
  return Math.min(WORKBENCH_MAX_PCT, Math.max(WORKBENCH_MIN_PCT, pct));
}

const workbenchItemKey = (item: WorkbenchItem) =>
  item.kind === "message" ? `message:${item.message.message_id}` : `tool:${item.run.tool_call_id}`;

interface CharacterPaneProps {
  timeline: ConversationTimelineViewModel;
  pair: PairRecord;
  workbenchOpen: boolean;
  delegation: DelegationCardView | null;
  onCancelDelegation?: () => void;
}

/** 角色区：常驻、永不卸载。工作台流式更新时不重渲染。 */
const CharacterPane = memo(function CharacterPane({
  timeline,
  pair,
  workbenchOpen,
  delegation,
  onCancelDelegation,
}: CharacterPaneProps) {
  return (
    <section className="pane pane-character" aria-label="角色区">
      <div className="pane-header">
        <span className="pair-dot pair-dot-character" />
        {pair.character.name}
        <span className="pane-header-tag" aria-live="polite">
          {timeline.isStreaming ? "正在回复…" : "空闲"}
        </span>
      </div>
      {!workbenchOpen ? (
        <div className="capability-tag" role="note">
          纯聊天 · {pair.character.name} 暂时看不到你的项目
          <span className="capability-tag-hint">切到协作模式即可让它读写项目</span>
        </div>
      ) : null}
      <MessageList timeline={timeline} pair={pair} emptyText={`和 ${pair.character.name} 聊聊吧`} />
      {delegation ? <DelegationCard delegation={delegation} onCancel={onCancelDelegation} /> : null}
    </section>
  );
});

interface WorkbenchPaneProps {
  assistant: AssistantWorkbenchViewModel;
  pair: PairRecord;
  open: boolean;
  onQuickTask?: (text: string) => void;
  onCloseWorkbench?: () => void;
}

/** 助手工作台：聊天模式下收起（宽度 0，DOM 与滚动位置保留）。角色区流式更新时不重渲染。 */
const WorkbenchPane = memo(function WorkbenchPane({
  assistant,
  pair,
  open,
  onQuickTask,
  onCloseWorkbench,
}: WorkbenchPaneProps) {
  const workbenchEmpty = assistant.messages.length === 0 && assistant.toolRuns.length === 0;
  const assistantName = pair.assistant.name;
  const emptyContent = useMemo(
    () =>
      workbenchEmpty ? (
        <div className="workbench-empty">
          <p>把任务交给 {assistantName}，执行记录会出现在这里</p>
          {onQuickTask ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => onQuickTask("介绍一下这个项目")}
            >
              试试：让它介绍一下这个项目
            </button>
          ) : null}
        </div>
      ) : null,
    [assistantName, onQuickTask, workbenchEmpty],
  );
  const renderItem = useCallback(
    (item: WorkbenchItem, itemState: ConversationItemState) =>
      item.kind === "message" ? (
        <MessageBubble message={item.message} pair={pair} itemState={itemState} />
      ) : (
        <ToolCard
          run={item.run}
          expanded={itemState.isExpanded(`tool:${item.run.tool_call_id}`)}
          onExpandedChange={(expanded) => itemState.setExpanded(`tool:${item.run.tool_call_id}`, expanded)}
        />
      ),
    [pair],
  );

  return (
    <section
      className={`pane pane-workbench${open ? "" : " is-closed"}`}
      aria-label="助手工作台"
      aria-hidden={!open}
      inert={!open}
    >
      <div className="pane pane-workbench-inner">
        <div className="pane-header">
          <span className="pair-dot pair-dot-assistant" />
          {pair.assistant.name}
          <span className="pane-header-tag" aria-live="polite">
            {assistant.busy ? "任务运行中" : "空闲"}
          </span>
          {onCloseWorkbench ? (
            <button
              type="button"
              className="icon-btn workbench-collapse"
              aria-label="收起工作台"
              title="收起工作台（切回聊天模式）"
              onClick={onCloseWorkbench}
            >
              <CollapseIcon />
            </button>
          ) : null}
        </div>
        <ConversationList
          active={open}
          conversationId={assistant.conversationId}
          listId="workbench"
          items={assistant.items}
          getItemKey={workbenchItemKey}
          estimateSize={80}
          overscan={8}
          scrollClassName="message-scroll"
          contentClassName="message-column"
          rowClassName="message-virtual-row"
          emptyContent={emptyContent}
          renderItem={renderItem}
          renderJumpButton={renderJumpToLatest}
        />
      </div>
    </section>
  );
});

/**
 * 工作区：同一条会话分成角色区与助手工作台两栏。
 * 角色区常驻、永不卸载；工作台是可开合侧栏，聊天模式下收起，协作模式下打开。
 * 工作台宽度写在容器的 --workbench-width 变量上：拖动分隔条时直接改变量，松手才提交 state。
 */
export const Workspace = memo(function Workspace({
  workspace,
  pair,
  onQuickTask,
  onCloseWorkbench,
  onCancelDelegation,
}: WorkspaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ rect: DOMRect; pct: number } | null>(null);
  const [workbenchPct, setWorkbenchPct] = useState(45);
  const [dragging, setDragging] = useState(false);
  const workbenchOpen = workspace.mode === "collaboration";

  const onHandlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      // 拖动期间容器自身尺寸不变，按下时量一次即可，移动中不再读布局。
      dragRef.current = { rect: containerRef.current!.getBoundingClientRect(), pct: workbenchPct };
      setDragging(true);
    },
    [workbenchPct],
  );

  const onHandlePointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    drag.pct = clampWorkbenchPct(((drag.rect.right - event.clientX) / drag.rect.width) * 100);
    containerRef.current!.style.setProperty("--workbench-width", `${drag.pct}%`);
    handleRef.current!.setAttribute("aria-valuenow", String(Math.round(drag.pct)));
  }, []);

  const onHandlePointerUp = useCallback(() => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    setDragging(false);
    setWorkbenchPct(drag.pct);
  }, []);

  const onHandleKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setWorkbenchPct((value) => clampWorkbenchPct(value + (event.key === "ArrowLeft" ? 2 : -2)));
    } else if (event.key === "Home") {
      event.preventDefault();
      setWorkbenchPct(WORKBENCH_MIN_PCT);
    } else if (event.key === "End") {
      event.preventDefault();
      setWorkbenchPct(WORKBENCH_MAX_PCT);
    }
  }, []);

  return (
    <div
      className="workspace-split"
      ref={containerRef}
      style={{ "--workbench-width": `${workbenchPct}%` } as CSSProperties}
    >
      <CharacterPane
        timeline={workspace.character}
        pair={pair}
        workbenchOpen={workbenchOpen}
        delegation={workspace.delegation}
        onCancelDelegation={onCancelDelegation}
      />

      <div
        ref={handleRef}
        className={`split-handle${dragging ? " is-dragging" : ""}${workbenchOpen ? "" : " is-hidden"}`}
        role="separator"
        aria-orientation="vertical"
        aria-label="调整工作区宽度"
        aria-valuemin={WORKBENCH_MIN_PCT}
        aria-valuemax={WORKBENCH_MAX_PCT}
        aria-valuenow={Math.round(workbenchPct)}
        tabIndex={workbenchOpen ? 0 : -1}
        aria-hidden={!workbenchOpen}
        onPointerDown={onHandlePointerDown}
        onPointerMove={onHandlePointerMove}
        onPointerUp={onHandlePointerUp}
        onPointerCancel={onHandlePointerUp}
        onKeyDown={onHandleKeyDown}
      />

      <WorkbenchPane
        assistant={workspace.assistant}
        pair={pair}
        open={workbenchOpen}
        onQuickTask={onQuickTask}
        onCloseWorkbench={onCloseWorkbench}
      />
    </div>
  );
});
