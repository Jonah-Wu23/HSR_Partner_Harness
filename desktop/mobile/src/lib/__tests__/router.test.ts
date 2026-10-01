import { describe, expect, it, vi } from "vitest";
import { navigate, navigateBack, parseHash } from "../router";

describe("router navigateBack 返回式导航", () => {
  it("应用内进入聊天后返回走 history.back，不新增历史条目", async () => {
    window.location.hash = "#/list";
    navigate({ name: "chat", conversationId: "c1" });
    await vi.waitFor(() => expect(window.location.hash).toBe("#/chat/c1"));

    const lengthBeforeBack = window.history.length;
    navigateBack({ name: "list" });

    await vi.waitFor(() => expect(window.location.hash).toBe("#/list"));
    expect(window.history.length).toBe(lengthBeforeBack);
    expect(parseHash(window.location.hash)).toEqual({ name: "list" });
  });

  it("深链或刷新直接落在聊天页时以 replace 回列表，不新增条目", () => {
    // 直接赋值 hash 得到一条不是应用内压栈产生的条目，等同刷新后的落点。
    window.location.hash = "#/chat/c1";
    const lengthBeforeBack = window.history.length;

    navigateBack({ name: "list" });

    expect(window.location.hash).toBe("#/list");
    expect(window.history.length).toBe(lengthBeforeBack);
    expect(parseHash(window.location.hash)).toEqual({ name: "list" });
  });
});
