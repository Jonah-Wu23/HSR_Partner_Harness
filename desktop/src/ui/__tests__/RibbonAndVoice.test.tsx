import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReasoningRibbon } from "../workspace/ReasoningRibbon";
import { ToolCard } from "../workspace/ToolCard";
import { VoiceMiniPlayer } from "../composer/VoiceMiniPlayer";

afterEach(cleanup);

describe("ReasoningRibbon", () => {
  it("流式期间显示「正在思考…」与脉动点，内容增量渲染", () => {
    render(<ReasoningRibbon text="先分析项目结构" streaming />);
    expect(screen.getByText("正在思考…")).toBeInTheDocument();
    expect(screen.getByText(/先分析项目结构/)).toBeInTheDocument();
  });

  it("结束后自动折叠成耗时摘要，点击重新展开", () => {
    const { rerender } = render(<ReasoningRibbon text="完整思考" streaming />);
    rerender(<ReasoningRibbon text="完整思考" streaming={false} elapsedSeconds={8} />);

    const toggle = screen.getByRole("button", { name: "思考了 8 秒 · 展开" });
    expect(screen.queryByText("完整思考")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByText("完整思考")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "思考了 8 秒 · 收起" }));
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

  it("合成中 / 播放中 / 失败三态", () => {
    const { rerender } = render(
      <VoiceMiniPlayer view={{ ...base, status: "synthesizing" }} onStop={() => {}} onSkip={() => {}} onClose={() => {}} />,
    );
    expect(screen.getByText("正在合成语音…")).toBeInTheDocument();

    rerender(
      <VoiceMiniPlayer view={{ ...base, status: "playing", queuedCount: 1 }} onStop={() => {}} onSkip={() => {}} onClose={() => {}} />,
    );
    expect(screen.getByText(/白厄：好的，我来看看/)).toBeInTheDocument();
    expect(screen.getByText(/队列还有 1 条/)).toBeInTheDocument();

    rerender(
      <VoiceMiniPlayer
        view={{ ...base, status: "failed", errorText: "语音服务没响应" }}
        onStop={() => {}}
        onSkip={() => {}}
        onRetry={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("语音服务没响应")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
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
      <ToolCard
        run={{
          tool_call_id: "tool-1",
          conversation_id: "conv-1",
          task_id: "task-1",
          engine_turn_id: "turn-1",
          sequence: 1,
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
});
