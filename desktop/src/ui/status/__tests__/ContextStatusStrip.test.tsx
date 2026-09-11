import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationSummary, PairMemory } from "../../../contracts/protocol";
import {
  ContextStatusStrip,
  type SummaryRegenerateTarget,
  type SummaryTriggerInfo,
} from "../ContextStatusStrip";

afterEach(cleanup);

function summaryRecord(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    summary_id: "s1",
    conversation_id: "c1",
    status: "running",
    covers_from_message_id: "m1",
    covers_to_message_id: "m80",
    covers_message_count: 80,
    content: null,
    provider: "deepseek",
    model: "deepseek-v4-flash",
    error_code: null,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:10Z",
    ...overrides,
  };
}

function memoryRecord(overrides: Partial<PairMemory> = {}): PairMemory {
  return {
    memory_id: "mem1",
    scope: {
      account_id: "acct-1",
      project_id: "proj-1",
      pair_id: "pair-1",
      character_ref: "card:card-1",
      assistant_identity: "ancient-machine",
    },
    content: { note: "用户喜欢先看结论" },
    status: "active",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ContextStatusStrip（V0.3.9 V02 压缩/记忆状态条）", () => {
  it("无摘要也无记忆数据时不渲染（不伪造状态）", () => {
    const { container } = render(<ContextStatusStrip summaries={null} memories={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("idle 摘要不渲染，running 摘要显示状态与触发原因", () => {
    const triggers: Record<string, SummaryTriggerInfo> = {
      s1: { reason: "message_count", observed: 80, threshold: 80 },
    };
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ summary_id: "idle-1", status: "idle" }), summaryRecord()]}
        triggers={triggers}
      />,
    );

    expect(screen.getByTestId("context-status-strip")).toBeInTheDocument();
    expect(screen.getByTestId("context-strip-status-s1")).toHaveTextContent("正在压缩上下文…");
    expect(screen.getByTestId("context-strip-summary-s1")).toHaveTextContent("已观测：80 条");
    expect(screen.getByTestId("context-strip-summary-s1")).toHaveTextContent("阈值：80 条");
    expect(screen.queryByTestId("context-strip-summary-idle-1")).not.toBeInTheDocument();
  });

  it("触发原因缺失时如实显示「未报告」，不硬编码阈值", () => {
    render(<ContextStatusStrip summaries={[summaryRecord()]} triggers={null} />);
    const trigger = screen.getByTestId("context-strip-trigger-s1");
    expect(trigger).toHaveTextContent("触发原因：未报告");
    expect(trigger).not.toHaveTextContent("阈值");
  });

  it("契约 §9 summary.failed 样例：失败可展开 error_code 与原始 error", () => {
    // 契约 §9：{conversation_id:"c1", summary_id:"s1", status:"failed",
    //            error_code:"summary_timeout", error:"provider timeout"}
    render(
      <ContextStatusStrip
        summaries={[
          summaryRecord({ status: "failed", error_code: "summary_timeout", error: "provider timeout" }),
        ]}
      />,
    );

    expect(screen.getByTestId("context-strip-status-s1")).toHaveTextContent("压缩失败");
    expect(screen.queryByTestId("context-strip-error-s1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("context-strip-expand-s1"));
    const errorBox = screen.getByTestId("context-strip-error-s1");
    expect(errorBox).toHaveTextContent("summary_timeout");
    expect(errorBox).toHaveTextContent("provider timeout");

    fireEvent.click(screen.getByTestId("context-strip-expand-s1"));
    expect(screen.queryByTestId("context-strip-error-s1")).not.toBeInTheDocument();
  });

  it("失败行不会自动消失；未提供 onDismiss 时不渲染关闭按钮", () => {
    const { rerender } = render(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "failed", error_code: "summary_timeout", error: "provider timeout" })]}
      />,
    );
    expect(screen.getByTestId("context-strip-summary-s1")).toBeInTheDocument();
    expect(screen.queryByLabelText(/关闭/)).not.toBeInTheDocument();

    rerender(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "failed", error_code: "summary_timeout", error: "provider timeout" })]}
      />,
    );
    expect(screen.getByTestId("context-strip-summary-s1")).toBeInTheDocument();
  });

  it("没有真实 summary.regenerate 对象时不显示恢复按钮", () => {
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "failed", error_code: "summary_timeout", error: "provider timeout" })]}
        regenerate={null}
        onRegenerate={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "重新生成摘要" })).not.toBeInTheDocument();
  });

  it("真实失败记录上显示恢复按钮，失败时原文上屏（不吞异常）", async () => {
    const target: SummaryRegenerateTarget = {
      summary_id: "s1",
      conversation_id: "c1",
      reason: "failed_record",
    };
    const onRegenerate = vi
      .fn()
      .mockRejectedValue(new Error("summary_provider_error: provider 返回 500"));
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "failed", error_code: "summary_timeout", error: "provider timeout" })]}
        regenerate={target}
        onRegenerate={onRegenerate}
      />,
    );

    fireEvent.click(screen.getByTestId("context-strip-regenerate-s1"));
    expect(onRegenerate).toHaveBeenCalledWith(target);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("summary_provider_error: provider 返回 500");
  });

  it("已完成摘要不因 failed_record 目标而显示恢复按钮", () => {
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "completed" })]}
        regenerate={{ summary_id: "s1", conversation_id: "c1", reason: "failed_record" }}
        onRegenerate={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "重新生成摘要" })).not.toBeInTheDocument();
  });

  it("用户显式请求可对已完成摘要重新生成", () => {
    const onRegenerate = vi.fn().mockResolvedValue(undefined);
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "completed" })]}
        regenerate={{ summary_id: "s1", conversation_id: "c1", reason: "user_request" }}
        onRegenerate={onRegenerate}
      />,
    );
    fireEvent.click(screen.getByTestId("context-strip-regenerate-s1"));
    expect(onRegenerate).toHaveBeenCalledOnce();
  });

  it("记忆空数组是真实零值，null 不渲染任何零指标", () => {
    const { rerender } = render(<ContextStatusStrip summaries={null} memories={[]} />);
    expect(screen.getByTestId("context-strip-memory-count")).toHaveTextContent("0 条生效");

    rerender(<ContextStatusStrip summaries={null} memories={null} />);
    expect(screen.queryByTestId("context-strip-memory")).not.toBeInTheDocument();
    expect(screen.queryByTestId("context-strip-memory-count")).not.toBeInTheDocument();
  });

  it("记忆只展示服务端解析的作用域分量，不拼接键", () => {
    render(<ContextStatusStrip summaries={null} memories={[memoryRecord()]} />);
    const scope = screen.getByTestId("context-strip-memory-scope");
    expect(scope).toHaveTextContent("card:card-1");
    expect(scope).toHaveTextContent("ancient-machine");
    expect(scope).toHaveTextContent("proj-1");
    expect(scope).not.toHaveTextContent("acct-1:proj-1:pair-1");
    expect(screen.getByTestId("context-strip-memory")).toHaveTextContent("配对共享");
    expect(screen.getByTestId("context-strip-memory")).toHaveTextContent(
      "作用域由服务端解析，客户端只传 conversation_id",
    );
  });

  it("已删除记忆不计入生效条数，但记录总数如实展示", () => {
    render(
      <ContextStatusStrip
        summaries={null}
        memories={[memoryRecord(), memoryRecord({ memory_id: "mem2", status: "deleted" })]}
      />,
    );
    expect(screen.getByTestId("context-strip-memory-count")).toHaveTextContent("1 条生效");
    expect(screen.getByTestId("context-strip-memory-count")).toHaveTextContent("共 2 条记录");
  });

  it("日常聊天（project 为空）如实说明不读写长期记忆", () => {
    render(<ContextStatusStrip summaries={null} memories={null} projectId={null} />);
    expect(screen.getByTestId("context-strip-memory-disabled")).toHaveTextContent(
      "日常聊天（无项目）不读写长期记忆",
    );
  });

  it("提供 onDismiss 时关闭按钮触发回调", async () => {
    const onDismiss = vi.fn();
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "completed" })]}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByLabelText("关闭压缩已完成状态条"));
    await waitFor(() => expect(onDismiss).toHaveBeenCalledWith("s1"));
  });

  it("长期记忆作用域展示完整五元组（账号/项目/搭档/角色/助手身份）", () => {
    render(<ContextStatusStrip summaries={null} memories={[memoryRecord()]} />);
    const scope = screen.getByTestId("context-strip-memory-scope");
    expect(scope).toHaveTextContent("acct-1");
    expect(scope).toHaveTextContent("proj-1");
    expect(scope).toHaveTextContent("pair-1");
    expect(scope).toHaveTextContent("card:card-1");
    expect(scope).toHaveTextContent("ancient-machine");
  });

  it("当全部记忆均为已删除时，作用域信息仍如实展示且生效条数为 0", () => {
    render(
      <ContextStatusStrip
        summaries={null}
        memories={[memoryRecord({ status: "deleted" })]}
      />,
    );
    expect(screen.getByTestId("context-strip-memory-count")).toHaveTextContent("0 条生效");
    expect(screen.getByTestId("context-strip-memory-scope")).toHaveTextContent("card:card-1");
  });

  it("重新生成因超时失败时，如实上屏错误信息（契约 §7 summary_timeout）", async () => {
    const target: SummaryRegenerateTarget = {
      summary_id: "s1",
      conversation_id: "c1",
      reason: "failed_record",
    };
    const onRegenerate = vi
      .fn()
      .mockRejectedValue(new Error("summary_timeout: 模型生成超时（60s）"));
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ status: "failed", error_code: "summary_timeout", error: "provider timeout" })]}
        regenerate={target}
        onRegenerate={onRegenerate}
      />,
    );
    fireEvent.click(screen.getByTestId("context-strip-regenerate-s1"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("summary_timeout: 模型生成超时（60s）");
  });

  it("摘要渲染覆盖消息范围 tooltip", () => {
    render(
      <ContextStatusStrip
        summaries={[
          summaryRecord({
            covers_from_message_id: "msg-start",
            covers_to_message_id: "msg-end",
            covers_message_count: 80,
          }),
        ]}
      />,
    );
    const valueEl = screen.getByText(/已覆盖 80 条/);
    expect(valueEl).toHaveAttribute("title", "覆盖范围：msg-start 至 msg-end");
  });
});
