import { useCallback, useRef, useState } from "react";
import type { PairRecord } from "../../contracts/protocol";
import type { WorkspaceViewModel } from "../../contracts/view-models";
import { MessageList } from "./MessageList";
import { ToolCard } from "./ToolCard";
import { CollapseIcon } from "../../assets/icons/icons";

interface WorkspaceProps {
  workspace: WorkspaceViewModel;
  pair: PairRecord;
  /** 工作台空状态的快捷任务：以「交给助手」发出预设任务。 */
  onQuickTask?: (text: string) => void;
  /** 工作台头部收起按钮：等同切回聊天模式。 */
  onCloseWorkbench?: () => void;
}

/**
 * 工作区：「一间房，两盏灯」。
 * 角色区常驻、永不卸载；工作台是可开合侧栏——聊天模式 = 收起（宽度 0，
 * DOM 与滚动位置保留），协作模式 = 打开。模式切换只是面板开合动画。
 */
export function Workspace({ workspace, pair, onQuickTask, onCloseWorkbench }: WorkspaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [workbenchPct, setWorkbenchPct] = useState(45);
  const [dragging, setDragging] = useState(false);
  const workbenchOpen = workspace.mode === "collaboration";

  const onHandlePointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  }, []);

  const onHandlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((rect.right - event.clientX) / rect.width) * 100;
      setWorkbenchPct(Math.min(60, Math.max(30, pct)));
    },
    [dragging],
  );

  const onHandlePointerUp = useCallback(() => setDragging(false), []);

  const onHandleKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setWorkbenchPct((value) =>
        Math.min(60, Math.max(30, value + (event.key === "ArrowLeft" ? 2 : -2))),
      );
    } else if (event.key === "Home") {
      event.preventDefault();
      setWorkbenchPct(30);
    } else if (event.key === "End") {
      event.preventDefault();
      setWorkbenchPct(60);
    }
  }, []);

  const workbenchEmpty =
    workspace.assistant.messages.length === 0 && workspace.assistant.toolRuns.length === 0;

  return (
    <div className="workspace-split" ref={containerRef}>
      <section className="pane pane-character" aria-label="角色区">
        <div className="pane-header">
          <span className="pair-dot pair-dot-character" />
          {pair.character.name}
          <span className="pane-header-tag" aria-live="polite">
            {workspace.character.isStreaming ? "正在回复…" : "空闲"}
          </span>
        </div>
        {!workbenchOpen ? (
          <div className="capability-tag" role="note">
            纯聊天 · {pair.character.name} 暂时看不到你的项目
            <span className="capability-tag-hint">切到协作模式即可让它读写项目</span>
          </div>
        ) : null}
        <MessageList
          timeline={workspace.character}
          pair={pair}
          emptyText={`和 ${pair.character.name} 聊聊吧`}
        />
      </section>

      <div
        className={`split-handle${dragging ? " is-dragging" : ""}${workbenchOpen ? "" : " is-hidden"}`}
        role="separator"
        aria-orientation="vertical"
        aria-label="调整工作区宽度"
        aria-valuemin={30}
        aria-valuemax={60}
        aria-valuenow={workbenchPct}
        tabIndex={workbenchOpen ? 0 : -1}
        aria-hidden={!workbenchOpen}
        onPointerDown={onHandlePointerDown}
        onPointerMove={onHandlePointerMove}
        onPointerUp={onHandlePointerUp}
        onKeyDown={onHandleKeyDown}
      />

      <section
        className={`pane pane-workbench${workbenchOpen ? "" : " is-closed"}`}
        style={workbenchOpen ? { width: `${workbenchPct}%` } : undefined}
        aria-label="助手工作台"
        aria-hidden={!workbenchOpen}
      >
        <div className="pane pane-workbench-inner">
          <div className="pane-header">
            <span className="pair-dot pair-dot-assistant" />
            {pair.assistant.name}
            <span className="pane-header-tag" aria-live="polite">
              {workspace.assistant.busy ? "任务运行中" : "空闲"}
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
          <div className="message-scroll">
            <div className="message-column">
              {workspace.assistant.messages
                .filter((message) => message.source !== "tool")
                .map((message) => (
                  <div key={message.message_id} className="msg-row" data-message-source="assistant">
                    <div className="msg-bubble msg-assistant">
                      <span className="msg-source">{pair.assistant.name}</span>
                      {message.text}
                      {message.streaming ? <span className="msg-streaming-caret" aria-hidden /> : null}
                    </div>
                  </div>
                ))}
              {workspace.assistant.toolRuns.map((run) => (
                <ToolCard key={run.tool_call_id} run={run} />
              ))}
              {workbenchEmpty ? (
                <div className="workbench-empty">
                  <p>把任务交给 {pair.assistant.name}，执行记录会出现在这里</p>
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
              ) : null}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
