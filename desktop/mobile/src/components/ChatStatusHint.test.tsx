import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ChatStatusHint } from "./ChatStatusHint";

afterEach(cleanup);

describe("ChatStatusHint 聊天页同步提示", () => {
  it("不在重新同步时不渲染", () => {
    const { container } = render(<ChatStatusHint resyncing={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("重新同步中展示「正在重新同步…」", () => {
    render(<ChatStatusHint resyncing={true} />);
    expect(screen.getByTestId("chat-status-resync")).toHaveTextContent("正在重新同步…");
  });
});
