import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ToolRun } from "../../contracts/protocol";
import { ReasoningRibbon } from "../workspace/ReasoningRibbon";
import { ToolCard } from "../workspace/ToolCard";
import { VoiceMiniPlayer } from "../composer/VoiceMiniPlayer";

afterEach(cleanup);

/** ToolCard 的展开状态由时间线保存，单测用本地状态充当时间线。 */
function ControlledToolCard({ run }: { run: ToolRun }) {
  const [expanded, setExpanded] = useState(false);
  return <ToolCard run={run} expanded={expanded} onExpandedChange={setExpanded} />;
}

describe("ReasoningRibbon", () => {
  it("流式期间显示「正在思考…」与脉动点，内容增量渲染", () => {
    render(<ReasoningRibbon text="先分析项目结构" streaming />);
    expect(screen.getByText("正在思考…")).toBeInTheDocument();
    expect(screen.getByText(/先分析项目结构/)).toBeInTheDocument();
  });

  it("结束后自动折叠成摘要，点击重新展开", () => {
    const { rerender } = render(<ReasoningRibbon text="完整思考" streaming />);
    rerender(<ReasoningRibbon text="完整思考" streaming={false} />);

    const toggle = screen.getByRole("button", { name: "思考完成 · 展开" });
    expect(screen.queryByText("完整思考")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByText("完整思考")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "思考完成 · 收起" }));
    expect(screen.queryByText("完整思考")).not.toBeInTheDocument();
  });

  it("无内容且非流式时不渲染", () => {
    const { container } = render(<ReasoningRibbon text="" streaming={false} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("VoiceMiniPlayer", () => {
  const base = {
    speaker: "character" as const,
    speakerName: "白厄",
    summary: "好的，我来看看",
    queuedCount: 0,
  };

  it.each([
    ["synthesizing", { ...base, status: "synthesizing" as const }, ["正在合成语音…"]],
    ["playing", { ...base, status: "playing" as const, queuedCount: 1 }, [/白厄：好的，我来看看/, /队列还有 1 条/]],
    ["failed", { ...base, status: "failed" as const, errorText: "语音服务没响应" }, ["语音服务没响应"]],
  ])("%s 态显示对应说明", (_status, view, texts) => {
    render(<VoiceMiniPlayer view={view} onStop={() => {}} onSkip={() => {}} onClose={() => {}} />);
    for (const text of texts) expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("播放中可停止与跳下一条", () => {
    const onStop = vi.fn();
    const onSkip = vi.fn();
    render(
      <VoiceMiniPlayer view={{ ...base, status: "playing", queuedCount: 2 }} onStop={onStop} onSkip={onSkip} onClose={() => {}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    expect(onStop).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "跳下一条" }));
    expect(onSkip).toHaveBeenCalled();
  });
});

describe("ToolCard", () => {
  it("折叠时隐藏命令与结果，展开后同时显示", () => {
    render(
      <ControlledToolCard
        run={{
          tool_call_id: "tool-1",
          conversation_id: "conv-1",
          task_id: "task-1",
          engine_turn_id: "turn-1",
          sequence: 1,
          timeline_order: 1,
          status: "succeeded",
          title: "Get-ChildItem -Force",
          summary: "已完成",
          details: "desktop\nsrc\ntests",
        }}
      />,
    );
    expect(screen.queryByText("Get-ChildItem -Force")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /工具调用/ }));
    expect(screen.getByText("命令")).toBeInTheDocument();
    expect(screen.getByText("Get-ChildItem -Force")).toBeInTheDocument();
    expect(screen.getByText("执行结果")).toBeInTheDocument();
    expect(screen.getByText(/desktop/)).toBeInTheDocument();
  });

  it.each([
    ["running", "运行中"],
    ["succeeded", "已完成"],
    ["failed", "失败"],
    ["denied", "已否决"],
  ] as const)("工具卡片 %s 态显示「%s」并标记状态", (status, label) => {
    const { container } = render(
      <ToolCard
        run={{
          tool_call_id: `tool-${status}`,
          conversation_id: "conv-1",
          task_id: "task-1",
          engine_turn_id: "turn-1",
          sequence: 1,
          timeline_order: 1,
          status,
          title: "命令占位",
          summary: "摘要",
          details: "明细",
        }}
        expanded={false}
        onExpandedChange={() => {}}
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.querySelector("[data-tool-status]")).toHaveAttribute("data-tool-status", status);
  });
});
