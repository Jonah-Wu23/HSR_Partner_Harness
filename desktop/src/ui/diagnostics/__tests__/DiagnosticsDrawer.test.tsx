import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TurnMetric } from "../../../contracts/protocol";
import { DiagnosticsDrawer } from "../DiagnosticsDrawer";
import type { PromptAssemblyView } from "../types";

afterEach(cleanup);

const loadProps = { onLoadMetrics: () => {}, onLoadMoreMetrics: () => {} };

function metricRecord(overrides: Partial<TurnMetric> = {}): TurnMetric {
  return {
    metric_id: "tm-1",
    account_id: "acct-1",
    project_id: "proj-1",
    conversation_id: "c1",
    pair_id: "pair-1",
    character_ref: "card:card-1",
    assistant_identity: "character",
    turn_kind: "character_turn",
    turn_id: "turn-1",
    task_id: null,
    engine_turn_id: null,
    provider: "deepseek",
    model: "deepseek-v4-flash",
    engine_type: "deepseek",
    reasoning_effort: "high",
    status: "completed",
    started_at: "2026-01-01T00:00:00Z",
    first_event_at: "2026-01-01T00:00:01Z",
    completed_at: "2026-01-01T00:00:05Z",
    duration_ms: 5000,
    input_tokens: null,
    output_tokens: null,
    total_tokens: 0,
    tool_rounds: 0,
    compression_count: 0,
    approval_count: 0,
    failure_type: null,
    failure_message: null,
    origin: "desktop",
    remote_device_key: null,
    remote_device_name: null,
    ...overrides,
  };
}

/** diagnostics.prompt_assembly 经 adaptPromptAssembly 适配后的结果；Sidecar 的 hash 与 summary 恒为 null。 */
function assemblyView(overrides: Partial<PromptAssemblyView> = {}): PromptAssemblyView {
  return {
    conversation_id: "c1",
    modules: [
      {
        name: "character_frame",
        char_start: 0,
        char_end: 512,
        hash: null,
        summary: null,
        memory_injected: false,
        hidden_content: null,
      },
      {
        name: "pair_memory",
        char_start: 513,
        char_end: 700,
        hash: null,
        summary: null,
        memory_injected: true,
        hidden_content: null,
      },
    ],
    diagnostics: ["world_book_hits: 2"],
    generated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("DiagnosticsDrawer 诊断抽屉", () => {
  it("关闭时不渲染；打开时渲染抽屉并各触发一次显式查询", () => {
    const onLoadMetrics = vi.fn();
    const onLoadAssembly = vi.fn();
    const props = {
      onClose: () => {},
      onLoadMetrics,
      onLoadMoreMetrics: () => {},
      onLoadAssembly,
    };
    const { rerender } = render(<DiagnosticsDrawer open={false} {...props} />);
    expect(screen.queryByRole("dialog", { name: "诊断" })).not.toBeInTheDocument();

    rerender(<DiagnosticsDrawer open {...props} />);
    expect(screen.getByRole("dialog", { name: "诊断" })).toBeInTheDocument();
    expect(onLoadMetrics).toHaveBeenCalledTimes(1);
    expect(onLoadAssembly).toHaveBeenCalledTimes(1);
  });

  it("未读取（null）与真实零条（[]）区分", () => {
    const { rerender } = render(<DiagnosticsDrawer open onClose={() => {}} {...loadProps} metrics={null} />);
    expect(screen.getByTestId("diag-metrics-nodata")).toHaveTextContent("无数据：尚未读取指标。");

    rerender(<DiagnosticsDrawer open onClose={() => {}} {...loadProps} metrics={[]} />);
    expect(screen.getByTestId("diag-metrics-empty")).toHaveTextContent("查询返回 0 条指标记录。");
    expect(screen.queryByTestId("diag-metrics-nodata")).not.toBeInTheDocument();
  });

  it("未观测 token 显示「无数据」，真实零值显示 0", () => {
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        {...loadProps}
        metrics={[
          metricRecord({ metric_id: "tm-null", input_tokens: null, output_tokens: null, total_tokens: 0 }),
          metricRecord({ metric_id: "tm-zero", input_tokens: 0, output_tokens: 0, total_tokens: 0 }),
        ]}
      />,
    );

    expect(screen.getByTestId("diag-tokens-tm-null")).toHaveTextContent("入 无数据");
    expect(screen.getByTestId("diag-tokens-tm-null")).toHaveTextContent("合 0");
    expect(screen.getByTestId("diag-tokens-tm-zero")).toHaveTextContent("入 0");
    expect(screen.getByTestId("diag-tokens-tm-zero")).toHaveTextContent("出 0");
    expect(screen.getByTestId("diag-tokens-tm-zero")).toHaveTextContent("合 0");
    expect(screen.getByTestId("diag-toolrounds-tm-null")).toHaveTextContent("0");
    expect(screen.getByTestId("diag-toolrounds-tm-zero")).toHaveTextContent("0");
  });

  it("查询失败以告警显示错误原文，不给出「0 条」结论", () => {
    // 首次查询失败时 Host 传下来的仍是 store 初值 []。
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        {...loadProps}
        metrics={[]}
        metricsState="failed"
        metricsError="backend_timeout: metrics.query 未在 30s 内返回"
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveAttribute("data-testid", "diag-metrics-error");
    expect(alert).toHaveTextContent("backend_timeout: metrics.query 未在 30s 内返回");
    expect(screen.queryByTestId("diag-metrics-empty")).not.toBeInTheDocument();
    expect(screen.queryByTestId("diag-metrics-count")).not.toBeInTheDocument();
    expect(screen.getByTestId("diag-metrics-nodata")).toHaveTextContent("指标未读取到");
  });

  it("刷新失败但保留上次结果时，标注为上一次成功读取的结果", () => {
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        {...loadProps}
        metrics={[metricRecord({ metric_id: "tm-stale" })]}
        metricsState="failed"
        metricsError="backend_timeout"
      />,
    );

    expect(screen.getByTestId("diag-metrics-error")).toHaveTextContent("backend_timeout");
    expect(screen.getByTestId("diag-metrics-stale")).toHaveTextContent(
      "本次读取失败，以下 1 条是上一次成功读取的结果。",
    );
    // 旧数据仍在屏幕上，但不得被冒充成本次查询的结论
    expect(screen.queryByTestId("diag-metrics-count")).not.toBeInTheDocument();
    expect(screen.getByTestId("diag-metric-tm-stale")).toBeInTheDocument();
  });

  it("首次读取中不提前给出「0 条」结论", () => {
    render(<DiagnosticsDrawer open onClose={() => {}} {...loadProps} metrics={[]} metricsState="loading" />);

    expect(screen.getByText("正在读取指标…")).toBeInTheDocument();
    expect(screen.queryByTestId("diag-metrics-empty")).not.toBeInTheDocument();
    expect(screen.queryByTestId("diag-metrics-nodata")).not.toBeInTheDocument();
  });

  it("失败回合在行内显示失败类型与原因，详情展开列出全部字段", () => {
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        {...loadProps}
        metrics={[
          metricRecord({
            turn_kind: "assistant_task",
            status: "failed",
            failure_type: "turn_failed",
            failure_message: "等待审批超时",
          }),
        ]}
      />,
    );
    const row = screen.getByTestId("diag-metric-tm-1");
    expect(row).toHaveTextContent("助手任务");
    expect(row).toHaveTextContent("失败");
    expect(row).toHaveTextContent("turn_failed");
    expect(row).toHaveTextContent("等待审批超时");

    fireEvent.click(within(row).getByRole("button", { name: "详情" }));
    const detail = screen.getByTestId("diag-metric-detail-tm-1");
    expect(detail).toHaveTextContent("acct-1");
    expect(detail).toHaveTextContent("card:card-1");
    expect(detail).toHaveTextContent("task_id无数据");
    expect(detail).toHaveTextContent("remote_device_key无数据");
    expect(detail).toHaveTextContent("reasoning_efforthigh");
    expect(detail).toHaveTextContent("approval_count0");
  });

  it("装配页签渲染模块的字符范围、记忆注入与服务端诊断，未提供的字段显示无数据", () => {
    render(<DiagnosticsDrawer open onClose={() => {}} {...loadProps} assembly={assemblyView()} initialTab="assembly" />);

    const frame = screen.getByTestId("diag-module-character_frame");
    expect(frame).toHaveTextContent("字符范围 0 – 512");
    expect(frame).toHaveTextContent("hash 无数据");
    expect(frame).toHaveTextContent("记忆 未注入");
    expect(screen.getByTestId("diag-module-pair_memory")).toHaveTextContent("记忆 已注入");
    expect(screen.getByTestId("diag-assembly-diagnostics")).toHaveTextContent("world_book_hits: 2");
    expect(screen.queryByRole("button", { name: "显示原文" })).not.toBeInTheDocument();
  });

  it("隐藏原文只在显式请求后显示，关闭抽屉即清除且不自动重新请求", async () => {
    const onRequestHiddenContent = vi.fn().mockResolvedValue("原始提示词：角色框架全文");
    const { rerender } = render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        {...loadProps}
        assembly={assemblyView()}
        initialTab="assembly"
        onRequestHiddenContent={onRequestHiddenContent}
      />,
    );

    expect(screen.queryByTestId("diag-module-hidden-character_frame")).not.toBeInTheDocument();
    expect(onRequestHiddenContent).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("diag-module-hidden-btn-character_frame"));
    const hidden = await screen.findByTestId("diag-module-hidden-character_frame");
    expect(hidden).toHaveTextContent("原始提示词：角色框架全文");
    expect(onRequestHiddenContent).toHaveBeenCalledWith("character_frame");

    // 关闭抽屉：内容随内容组件卸载清除。
    rerender(
      <DiagnosticsDrawer
        open={false}
        onClose={() => {}}
        {...loadProps}
        assembly={assemblyView()}
        initialTab="assembly"
        onRequestHiddenContent={onRequestHiddenContent}
      />,
    );
    expect(screen.queryByTestId("diag-module-hidden-character_frame")).not.toBeInTheDocument();

    // 重新打开：隐藏原文不会自动回来，也不会自动再次请求。
    rerender(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        {...loadProps}
        assembly={assemblyView()}
        initialTab="assembly"
        onRequestHiddenContent={onRequestHiddenContent}
      />,
    );
    expect(screen.queryByTestId("diag-module-hidden-character_frame")).not.toBeInTheDocument();
    await waitFor(() => expect(onRequestHiddenContent).toHaveBeenCalledTimes(1));
  });

  it("隐藏原文请求失败时以告警显示错误原文", async () => {
    const onRequestHiddenContent = vi
      .fn()
      .mockRejectedValue(new Error("服务端没有返回模块「character_frame」的隐藏原文"));
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        {...loadProps}
        assembly={assemblyView()}
        initialTab="assembly"
        onRequestHiddenContent={onRequestHiddenContent}
      />,
    );

    fireEvent.click(screen.getByTestId("diag-module-hidden-btn-character_frame"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("服务端没有返回模块「character_frame」的隐藏原文");
    expect(screen.queryByTestId("diag-module-hidden-character_frame")).not.toBeInTheDocument();
  });

  it("关闭按钮与 Esc 都调用 onClose", () => {
    const onClose = vi.fn();
    render(<DiagnosticsDrawer open onClose={onClose} {...loadProps} />);
    fireEvent.click(screen.getByLabelText("关闭诊断"));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
