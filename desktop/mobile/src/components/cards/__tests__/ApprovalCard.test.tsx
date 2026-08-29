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

  it("点击批准/拒绝触发对应回调", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(<ApprovalCard approval={approval} onApprove={onApprove} onReject={onReject} />);

    screen.getByTestId("approval-approve").click();
    expect(onApprove).toHaveBeenCalledTimes(1);

    screen.getByTestId("approval-reject").click();
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it("resolving=true 时按钮禁用并显示提交中", () => {
    render(<ApprovalCard approval={approval} resolving onApprove={vi.fn()} onReject={vi.fn()} />);

    const approve = screen.getByTestId("approval-approve");
    const reject = screen.getByTestId("approval-reject");
    expect(approve).toBeDisabled();
    expect(reject).toBeDisabled();
    expect(approve.textContent).toBe("提交中…");
  });

  it("已决状态展示决策与处理端", () => {
    render(
      <ApprovalCard
        approval={approval}
        status="resolved"
        decision="deny"
        resolvedBy="desktop"
        conversationTitle="测试会话"
      />,
    );

    expect(screen.getByText(/已决操作 · 命令执行/)).toBeInTheDocument();
    expect(screen.getByTestId("approval-status")).toHaveTextContent("已拒绝");
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent(/桌面端/);
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent(/已拒绝/);
    expect(screen.queryByTestId("approval-approve")).toBeNull();
    expect(screen.queryByTestId("approval-reject")).toBeNull();
  });

  it("mobile / remote 处理端统一显示为手机端", () => {
    render(<ApprovalCard approval={approval} status="resolved" decision="allow" resolvedBy="remote" />);
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent(/手机端/);

    cleanup();

    render(<ApprovalCard approval={approval} status="resolved" decision="allow" resolvedBy="mobile" />);
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent(/手机端/);
  });

  it("V0.3.5：提供「本会话批准」（allow_for_conversation）真实回调", () => {
    const onApprove = vi.fn();
    const onAllowForConversation = vi.fn();
    const onReject = vi.fn();
    render(
      <ApprovalCard
        approval={approval}
        onApprove={onApprove}
        onAllowForConversation={onAllowForConversation}
        onReject={onReject}
      />,
    );
    expect(screen.getByTestId("approval-approve")).toBeTruthy();
    expect(screen.getByTestId("approval-allow-conversation")).toBeTruthy();
    expect(screen.getByTestId("approval-reject")).toBeTruthy();
    fireEvent.click(screen.getByTestId("approval-allow-conversation"));
    expect(onAllowForConversation).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });

  it("V0.3.5：未传 onAllowForConversation 时不渲染该按钮（向后兼容）", () => {
    render(<ApprovalCard approval={approval} onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.queryByTestId("approval-allow-conversation")).toBeNull();
  });

  it("V0.3.5：未知 decision 值显示中性文案，不伪造批准方向", () => {
    render(<ApprovalCard approval={approval} status="resolved" decision="" resolvedBy="desktop" />);
    expect(screen.getByTestId("approval-status")).toHaveTextContent(/已处理/);
  });
});
