import { cleanup, render, screen } from "@testing-library/react";
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
});
