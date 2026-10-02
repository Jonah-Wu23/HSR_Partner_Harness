import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PendingApproval } from "@shared/contracts/protocol";
import { ApprovalCard } from "../ApprovalCard";

describe("ApprovalCard", () => {
  afterEach(() => {
    cleanup();
  });
  const approval: PendingApproval = {
    approval_id: "app-1",
    conversation_id: "c1",
    operation: {
      tool_kind: "shell",
      command: "rm -rf build/",
      paths: ["/project/build"],
      patch_file_count: 3,
      summary: "清理构建目录并应用代码补丁",
    },
    reason: "高风险文件删除与代码修改操作",
    task_id: "task-1",
  };

  it("渲染待审批操作详情与操作按钮", () => {
    render(<ApprovalCard approval={approval} conversationTitle="测试会话" />);

    expect(screen.getByTestId("approval-card")).toBeInTheDocument();
    expect(screen.getByText(/待审批操作 · 命令执行/)).toBeInTheDocument();
    expect(screen.getByText("清理构建目录并应用代码补丁")).toBeInTheDocument();
    expect(screen.getByText("rm -rf build/")).toBeInTheDocument();
    expect(screen.getByText("/project/build")).toBeInTheDocument();
    expect(screen.getByText("3 个文件")).toBeInTheDocument();
    expect(screen.getByText("高风险文件删除与代码修改操作")).toBeInTheDocument();
    expect(screen.getByText("测试会话")).toBeInTheDocument();
    expect(screen.getByTestId("approval-approve")).toBeInTheDocument();
    expect(screen.getByTestId("approval-reject")).toBeInTheDocument();
  });

  it.each([
    { button: "approval-approve", handler: "onApprove" },
    { button: "approval-allow-conversation", handler: "onAllowForConversation" },
    { button: "approval-reject", handler: "onReject" },
  ] as const)("点击 $button 只触发 $handler", ({ button, handler }) => {
    const callbacks = { onApprove: vi.fn(), onAllowForConversation: vi.fn(), onReject: vi.fn() };
    render(<ApprovalCard approval={approval} {...callbacks} />);

    fireEvent.click(screen.getByTestId(button));

    for (const [name, callback] of Object.entries(callbacks)) {
      expect(callback).toHaveBeenCalledTimes(name === handler ? 1 : 0);
    }
  });

  it("没有本会话批准回调时不显示该按钮", () => {
    render(<ApprovalCard approval={approval} onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.queryByTestId("approval-allow-conversation")).toBeNull();
  });

  it("提交中时按钮禁用并显示提交中", () => {
    render(<ApprovalCard approval={approval} resolving onApprove={vi.fn()} onReject={vi.fn()} />);

    const approve = screen.getByTestId("approval-approve");
    expect(approve).toBeDisabled();
    expect(screen.getByTestId("approval-reject")).toBeDisabled();
    expect(approve).toHaveTextContent("提交中…");
  });

  it.each([
    { resolvedBy: "desktop", decision: "deny", status: "已拒绝", text: "由 桌面端 已拒绝" },
    { resolvedBy: "remote", decision: "allow", status: "已批准", text: "由 手机端 已批准" },
  ] as const)("$resolvedBy 裁决后展示决策与处理端，不再提供操作按钮", ({
    resolvedBy,
    decision,
    status,
    text,
  }) => {
    render(
      <ApprovalCard approval={approval} status="resolved" decision={decision} resolvedBy={resolvedBy} />,
    );

    expect(screen.getByText(/已决操作 · 命令执行/)).toBeInTheDocument();
    expect(screen.getByTestId("approval-status")).toHaveTextContent(status);
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent(text);
    expect(screen.queryByTestId("approval-approve")).toBeNull();
    expect(screen.queryByTestId("approval-reject")).toBeNull();
  });

  it("服务端超时终态展示系统来源、处理者、终态原因、错误码与时间", () => {
    render(
      <ApprovalCard
        approval={approval}
        status="resolved"
        decision="timeout"
        resolvedBy="system"
        actor="system"
        resolutionReason="等待审批超时"
        errorCode="approval_timeout"
        resolvedAt="2026-01-01T00:00:00Z"
      />,
    );
    expect(screen.getByTestId("approval-status")).toHaveTextContent("已超时");
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent("由 系统 已超时");
    expect(screen.getByTestId("approval-resolved-actor")).toHaveTextContent("处理者：系统");
    expect(screen.getByTestId("approval-resolved-reason")).toHaveTextContent("等待审批超时");
    expect(screen.getByTestId("approval-resolved-error-code")).toHaveTextContent(
      "approval_timeout",
    );
    expect(screen.getByTestId("approval-resolved-at")).toHaveTextContent(
      "2026-01-01T00:00:00Z",
    );
  });

  it("审查智能体裁决：resolved_by 为 null，只展示决策，处理者为审核者", () => {
    render(
      <ApprovalCard
        approval={approval}
        status="resolved"
        decision="allow_for_conversation"
        resolvedBy={null}
        actor="reviewer"
      />,
    );
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent("已批准（本会话）");
    expect(screen.getByTestId("approval-resolved-by")).not.toHaveTextContent(/桌面端|手机端|由/);
    expect(screen.getByTestId("approval-resolved-actor")).toHaveTextContent("处理者：审核者");
  });
});
