import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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

  it("渲染待审批操作详情与「请在电脑端处理」标记", () => {
    render(<ApprovalCard approval={approval} conversationTitle="测试会话" />);

    expect(screen.getByTestId("approval-card")).toBeInTheDocument();
    expect(screen.getByText(/待审批操作 · 命令执行/)).toBeInTheDocument();
    expect(screen.getByText("请在电脑端处理")).toBeInTheDocument();
    expect(screen.getByText("清理构建目录并应用代码补丁")).toBeInTheDocument();
    expect(screen.getByText("rm -rf build/")).toBeInTheDocument();
    expect(screen.getByText("/project/build")).toBeInTheDocument();
    expect(screen.getByText("3 个文件")).toBeInTheDocument();
    expect(screen.getByText("高风险文件删除与代码修改操作")).toBeInTheDocument();
    expect(screen.getByText("测试会话")).toBeInTheDocument();
  });

  it("只读断言：UI 中严禁出现批准、允许、拒绝、否决等操作按钮", () => {
    render(<ApprovalCard approval={approval} />);

    // 严禁存在任何用于应答审批的交互按钮
    expect(screen.queryByRole("button", { name: /允许|批准|通过|仍要允许/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /否决|拒绝|取消/i })).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
