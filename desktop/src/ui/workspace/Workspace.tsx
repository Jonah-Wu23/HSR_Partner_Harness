import { useCallback, useRef, useState } from "react";
import type { PairRecord } from "../../contracts/protocol";
import type { WorkspaceViewModel } from "../../contracts/view-models";
import { MessageList } from "./MessageList";
import { ToolCard } from "./ToolCard";

interface WorkspaceProps {
  workspace: WorkspaceViewModel;
  pair: PairRecord;
}

/** 工作区：聊天模式单栏角色区；协作模式角色区 + 助手工作台双栏，可拖拽分栏。 */
export function Workspace({ workspace, pair }: WorkspaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [workbenchPct, setWorkbenchPct] = useState(45);
  const [dragging, setDragging] = useState(false);

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

  const characterPane = (
    <section className="pane pane-character" aria-label="角色区">
      <div className="pane-header">
        <span className="pair-dot pair-dot-character" />
        {pair.character.name}
        <span className="pane-header-tag">
          {workspace.character.isStreaming ? "正在回复…" : "角色扮演区"}
        </span>
      </div>
      <MessageList
        timeline={workspace.character}
        pair={pair}
        emptyText={`和 ${pair.character.name} 聊聊吧`}
      />
    </section>
  );

  if (workspace.mode === "chat") {
    return <div className="workspace-split">{characterPane}</div>;
  }

  return (
    <div className="workspace-split" ref={containerRef}>
      {characterPane}
      <div
        className={`split-handle${dragging ? " is-dragging" : ""}`}
        role="separator"
        aria-orientation="vertical"
        aria-label="调整工作区宽度"
        onPointerDown={onHandlePointerDown}
        onPointerMove={onHandlePointerMove}
        onPointerUp={onHandlePointerUp}
      />
      <section
        className="pane pane-workbench"
        style={{ width: `${workbenchPct}%` }}
        aria-label="助手工作台"
      >
        <div className="pane-header">
          <span className="pair-dot pair-dot-assistant" />
          {pair.assistant.name}
          <span className="pane-header-tag">
            {workspace.assistant.busy ? "任务运行中" : "工作台"}
          </span>
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
            {workspace.assistant.messages.length === 0 &&
            workspace.assistant.toolRuns.length === 0 ? (
              <div className="msg-row msg-row-system">
                <div className="msg-bubble msg-system">
                  把任务交给 {pair.assistant.name}，执行记录会出现在这里
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
