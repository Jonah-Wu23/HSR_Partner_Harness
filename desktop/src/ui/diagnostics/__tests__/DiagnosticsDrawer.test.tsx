import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TurnMetric } from "../../../contracts/protocol";
import { DiagnosticsDrawer } from "../DiagnosticsDrawer";
import type { PromptAssemblyView } from "../types";

afterEach(cleanup);

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

function assemblyView(overrides: Partial<PromptAssemblyView> = {}): PromptAssemblyView {
  return {
    conversation_id: "c1",
    modules: [
      {
        name: "character_frame",
        char_start: 0,
        char_end: 512,
        hash: "abc123",
        summary: "角色框架",
        memory_injected: false,
        hidden_content: null,
      },
      {
        name: "pair_memory",
        char_start: 513,
        char_end: 700,
        hash: "def456",
        summary: "配对记忆片段",
        memory_injected: true,
        hidden_content: null,
      },
    ],
    diagnostics: ["世界书命中 2 条"],
    generated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("DiagnosticsDrawer（V0.3.9 V03 诊断抽屉）", () => {
  it("关闭时不渲染；打开时渲染抽屉并各触发一次显式查询", () => {
    const onLoadMetrics = vi.fn();
    const onLoadAssembly = vi.fn();
    const { rerender } = render(
      <DiagnosticsDrawer
        open={false}
        onClose={() => {}}
        onLoadMetrics={onLoadMetrics}
        onLoadAssembly={onLoadAssembly}
      />,
    );
    expect(screen.queryByRole("dialog", { name: "诊断" })).not.toBeInTheDocument();

    rerender(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        onLoadMetrics={onLoadMetrics}
        onLoadAssembly={onLoadAssembly}
      />,
    );
    expect(screen.getByRole("dialog", { name: "诊断" })).toBeInTheDocument();
    expect(onLoadMetrics).toHaveBeenCalledTimes(1);
    expect(onLoadAssembly).toHaveBeenCalledTimes(1);
  });

  it("未读取（null）与真实零条（[]）区分", () => {
    const { rerender } = render(<DiagnosticsDrawer open onClose={() => {}} metrics={null} />);
    expect(screen.getByTestId("diag-metrics-nodata")).toHaveTextContent("无数据：尚未读取指标。");

    rerender(<DiagnosticsDrawer open onClose={() => {}} metrics={[]} />);
    expect(screen.getByTestId("diag-metrics-empty")).toHaveTextContent("查询返回 0 条指标记录。");
    expect(screen.queryByTestId("diag-metrics-nodata")).not.toBeInTheDocument();
  });

  it("未观测 token 显示「无数据」，真实零值显示 0", () => {
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
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

  it("查询失败如实显示错误原文，不伪造数据", () => {
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        metrics={null}
        metricsState="failed"
        metricsError="metrics_query_failed: sidecar 连接中断"
      />,
    );
    const alert = screen.getByTestId("diag-metrics-error");
    expect(alert).toHaveTextContent("metrics_query_failed: sidecar 连接中断");
    expect(alert).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("diag-metrics-nodata")).toHaveTextContent("指标未读取到");
  });

  it("详情展开渲染 TurnMetric 全字段（含 null 与零值）", () => {
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        metrics={[metricRecord({ status: "failed", failure_type: "provider_error", failure_message: "500" })]}
      />,
    );
    expect(screen.getByTestId("diag-metric-tm-1")).toHaveTextContent("失败");
    expect(screen.getByTestId("diag-metric-tm-1")).toHaveTextContent("provider_error");

    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    const detail = screen.getByTestId("diag-metric-detail-tm-1");
    expect(detail).toHaveTextContent("acct-1");
    expect(detail).toHaveTextContent("card:card-1");
    expect(detail).toHaveTextContent("task_id");
    expect(detail).toHaveTextContent("remote_device_key");
    expect(detail).toHaveTextContent("reasoning_effort");
    expect(detail).toHaveTextContent("high");
  });

  it("装配页签渲染模块字段；未提供隐藏原文回调时不显示按钮", () => {
    render(<DiagnosticsDrawer open onClose={() => {}} assembly={assemblyView()} initialTab="assembly" />);

    expect(screen.getByTestId("diag-module-character_frame")).toHaveTextContent("字符范围 0 – 512");
    expect(screen.getByTestId("diag-module-character_frame")).toHaveTextContent("hash abc123");
    expect(screen.getByTestId("diag-module-character_frame")).toHaveTextContent("记忆 未注入");
    expect(screen.getByTestId("diag-module-pair_memory")).toHaveTextContent("记忆 已注入");
    expect(screen.getByTestId("diag-assembly-diagnostics")).toHaveTextContent("世界书命中 2 条");
    expect(screen.queryByRole("button", { name: "显示原文" })).not.toBeInTheDocument();
  });

  it("隐藏原文只在显式请求后显示，关闭抽屉即清除且不自动重新请求", async () => {
    const onRequestHiddenContent = vi.fn().mockResolvedValue("原始提示词：角色框架全文");
    const { rerender } = render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
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
        assembly={assemblyView()}
        initialTab="assembly"
        onRequestHiddenContent={onRequestHiddenContent}
      />,
    );
    expect(screen.queryByTestId("diag-module-hidden-character_frame")).not.toBeInTheDocument();
    await waitFor(() => expect(onRequestHiddenContent).toHaveBeenCalledTimes(1));
  });

  it("隐藏原文请求失败原文上屏（不吞异常）", async () => {
    const onRequestHiddenContent = vi
      .fn()
      .mockRejectedValue(new Error("prompt_assembly_unavailable: 服务端拒绝返回原文"));
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        assembly={assemblyView()}
        initialTab="assembly"
        onRequestHiddenContent={onRequestHiddenContent}
      />,
    );

    fireEvent.click(screen.getByTestId("diag-module-hidden-btn-character_frame"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("prompt_assembly_unavailable: 服务端拒绝返回原文");
    expect(screen.queryByTestId("diag-module-hidden-character_frame")).not.toBeInTheDocument();
  });

  it("关闭按钮与 Esc 都调用 onClose", () => {
    const onClose = vi.fn();
    render(<DiagnosticsDrawer open onClose={onClose} />);
    fireEvent.click(screen.getByLabelText("关闭诊断"));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("契约 §9 timeout 样例：TurnMetric 渲染 approval_timeout 与 summary_timeout 终态", () => {
    // 契约 §9 approval.resolved 超时：decision:"timeout", error_code:"approval_timeout", reason:"等待审批超时"
    // 契约 §9 summary.failed 超时：error_code:"summary_timeout", error:"provider timeout"
    render(
      <DiagnosticsDrawer
        open
        onClose={() => {}}
        metrics={[
          metricRecord({
            metric_id: "tm-approval-timeout",
            turn_kind: "assistant_task",
            status: "failed",
            failure_type: "approval_timeout",
            failure_message: "等待审批超时",
          }),
          metricRecord({
            metric_id: "tm-summary-timeout",
            turn_kind: "character_turn",
            status: "failed",
            failure_type: "summary_timeout",
            failure_message: "provider timeout",
          }),
        ]}
      />,
    );

    const approvalRow = screen.getByTestId("diag-metric-tm-approval-timeout");
    expect(approvalRow).toHaveTextContent("助手任务");
    expect(approvalRow).toHaveTextContent("失败");
    expect(approvalRow).toHaveTextContent("approval_timeout");
    expect(approvalRow).toHaveTextContent("等待审批超时");

    const summaryRow = screen.getByTestId("diag-metric-tm-summary-timeout");
    expect(summaryRow).toHaveTextContent("角色回合");
    expect(summaryRow).toHaveTextContent("失败");
    expect(summaryRow).toHaveTextContent("summary_timeout");
    expect(summaryRow).toHaveTextContent("provider timeout");

    // 展开详情验证全量字段完整呈现
    fireEvent.click(within(approvalRow).getByRole("button", { name: "详情" }));
    const detail = screen.getByTestId("diag-metric-detail-tm-approval-timeout");
    expect(detail).toHaveTextContent("turn_kind");
    expect(detail).toHaveTextContent("assistant_task");
    expect(detail).toHaveTextContent("status");
    expect(detail).toHaveTextContent("failed");
    expect(detail).toHaveTextContent("approval_timeout");
    expect(detail).toHaveTextContent("等待审批超时");
  });
});
