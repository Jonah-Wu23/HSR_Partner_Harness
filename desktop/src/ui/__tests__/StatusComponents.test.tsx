import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConnectionPill } from "../status/ConnectionPill";
import { ToastStack } from "../status/ToastStack";
import { TechDetailsDrawer } from "../status/TechDetailsDrawer";
import { QueueStrip } from "../status/QueueStrip";
import type { QueueItemView, ToastItem } from "../status/types";

afterEach(cleanup);

describe("ConnectionPill", () => {
  it.each([
    ["connected", "已连接"],
    ["connecting", "连接中…"],
    ["disconnected", "连接已断开"],
  ] as const)("%s 显示「%s」", (status, label) => {
    render(<ConnectionPill status={status} onOpenDetails={() => {}} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("点击打开技术详情", () => {
    const onOpen = vi.fn();
    render(<ConnectionPill status="disconnected" onOpenDetails={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /连接状态/ }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("ToastStack", () => {
  const toasts: ToastItem[] = [
    { id: "t1", kind: "error", text: "与本地服务失去连接，正在重试。", hasDetails: true },
    { id: "t2", kind: "success", text: "已恢复连接" },
  ];

  it("空队列不渲染", () => {
    const { container } = render(<ToastStack toasts={[]} onDismiss={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("渲染通知并可关闭、可查看详情", () => {
    const onDismiss = vi.fn();
    const onOpenDetails = vi.fn();
    render(<ToastStack toasts={toasts} onDismiss={onDismiss} onOpenDetails={onOpenDetails} />);

    expect(screen.getByText("与本地服务失去连接，正在重试。")).toBeInTheDocument();
    fireEvent.click(screen.getByText("查看技术详情"));
    expect(onOpenDetails).toHaveBeenCalledWith("t1");
    fireEvent.click(screen.getAllByLabelText("关闭通知")[0]);
    expect(onDismiss).toHaveBeenCalledWith("t1");
  });
});

describe("TechDetailsDrawer", () => {
  it("关闭时不渲染；打开时展示技术信息与重连动作", () => {
    const { rerender } = render(
      <TechDetailsDrawer
        open={false}
        status="disconnected"
        details={{}}
        onClose={() => {}}
        onReconnect={() => {}}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    rerender(
      <TechDetailsDrawer
        open
        status="disconnected"
        details={{ lastError: "websocket:close status: 1011", logPath: "C:/logs/sidecar.log" }}
        onClose={() => {}}
        onReconnect={() => {}}
      />,
    );
    expect(screen.getByRole("dialog", { name: "技术详情" })).toBeInTheDocument();
    expect(screen.getByText("websocket:close status: 1011")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即重连" })).toBeInTheDocument();
  });
});

describe("QueueStrip", () => {
  const items: QueueItemView[] = [
    {
      queueItemId: "q1",
      target: "character",
      summary: "帮我想想这个名字",
      position: 1,
      waitingFor: "等待当前回复结束",
      intent: "followup",
      failed: false,
      error: null,
    },
    {
      queueItemId: "q2",
      target: "assistant",
      summary: "跑一下测试",
      position: 2,
      waitingFor: "等待上一个任务结束",
      intent: "followup",
      failed: false,
      error: null,
    },
  ];

  it("空队列不渲染", () => {
    const { container } = render(
      <QueueStrip items={[]} onEdit={() => {}} onWithdraw={() => {}} onPrioritize={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("显示发给谁、摘要与等待说明，三个操作各自回调", () => {
    const onEdit = vi.fn();
    const onWithdraw = vi.fn();
    const onPrioritize = vi.fn();
    render(
      <QueueStrip
        items={items}
        names={{ character: "白厄", assistant: "机枢" }}
        onEdit={onEdit}
        onWithdraw={onWithdraw}
        onPrioritize={onPrioritize}
      />,
    );

    expect(screen.getByLabelText("排队 2 条")).toBeInTheDocument();
    expect(screen.getByText("给白厄")).toBeInTheDocument();
    expect(screen.getByText("给机枢")).toBeInTheDocument();
    expect(screen.getByText(/等待上一个任务结束/)).toBeInTheDocument();

    const capsules = screen.getAllByRole("listitem");
    fireEvent.click(within(capsules[0]).getByText("编辑"));
    expect(onEdit).toHaveBeenCalledWith("q1");
    fireEvent.click(within(capsules[1]).getByText("撤回"));
    expect(onWithdraw).toHaveBeenCalledWith("q2");
    fireEvent.click(within(capsules[1]).getByText("立即插入"));
    expect(onPrioritize).toHaveBeenCalledWith("q2");
  });

  it("派发失败的排队项显示错误原文，只保留撤回", () => {
    const onWithdraw = vi.fn();
    render(
      <QueueStrip
        items={[{ ...items[0], failed: true, error: "编程助手进程已退出" }]}
        onEdit={() => {}}
        onWithdraw={onWithdraw}
        onPrioritize={() => {}}
      />,
    );

    const capsule = screen.getByRole("listitem");
    expect(capsule).toHaveAttribute("data-queue-status", "failed");
    expect(within(capsule).getByRole("alert")).toHaveTextContent("派发失败：编程助手进程已退出");
    expect(within(capsule).queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    expect(within(capsule).queryByRole("button", { name: "立即插入" })).not.toBeInTheDocument();
    fireEvent.click(within(capsule).getByRole("button", { name: "撤回" }));
    expect(onWithdraw).toHaveBeenCalledWith("q1");
  });
});
