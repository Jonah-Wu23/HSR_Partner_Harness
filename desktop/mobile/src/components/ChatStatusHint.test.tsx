import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ChatStatusHint } from "./ChatStatusHint";

afterEach(cleanup);

describe("ChatStatusHint（V0.3.9 V06 移动聊天页页内状态提示）", () => {
  it("正常连接、已水合且无失去控制权事实时返回 null，不占位", () => {
    const { container } = render(
      <ChatStatusHint
        connection="connected"
        resyncing={false}
        leaseLostAt={null}
        showConnection={false}
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("chat-status-hint")).toBeNull();
  });

  it("重新同步中（resyncing=true）：展示正在重新同步提示", () => {
    render(
      <ChatStatusHint
        connection="connected"
        resyncing={true}
        leaseLostAt={null}
        showConnection={false}
      />,
    );
    expect(screen.getByTestId("chat-status-hint")).toBeInTheDocument();
    expect(screen.getByTestId("chat-status-resync")).toHaveTextContent("正在重新同步…");
  });

  it("失去控制权（leaseLostAt 有有效时间戳）：展示本地化时间提示", () => {
    render(
      <ChatStatusHint
        connection="connected"
        resyncing={false}
        leaseLostAt="2026-01-01T12:00:00Z"
        showConnection={false}
      />,
    );
    expect(screen.getByTestId("chat-status-lease-lost")).toHaveTextContent(
      "已失去对电脑的控制权",
    );
  });

  it("showConnection=true 时展示非 connected 状态文案", () => {
    render(
      <ChatStatusHint
        connection="reconnecting"
        resyncing={false}
        leaseLostAt={null}
        showConnection={true}
      />,
    );
    expect(screen.getByTestId("chat-status-connection")).toHaveTextContent(
      "与桌面端连接中断，正在重连…",
    );
  });

  it("showConnection=false 时隐藏连接状态，避免与顶部 ConnectionBanner 重复", () => {
    render(
      <ChatStatusHint
        connection="reconnecting"
        resyncing={true}
        leaseLostAt={null}
        showConnection={false}
      />,
    );
    expect(screen.queryByTestId("chat-status-connection")).toBeNull();
    expect(screen.getByTestId("chat-status-resync")).toBeInTheDocument();
  });
});
