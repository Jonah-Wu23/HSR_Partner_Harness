import { describe, expect, it, vi } from "vitest";
import { navigate, navigateBack, parseHash } from "../router";

/**
 * V0.3.7 V9 收尾：返回式导航语义。
 * 修复前聊天页返回走 navigate 压栈，「列表 → 聊天 → 列表」每轮进出累积一条历史，
 * WebView 返回键会在假栈里反复后退；修复后返回回退既有条目或以 replace 兜底。
 */
describe("router navigateBack 返回式导航", () => {
  it("应用内进入聊天后返回走 history.back，不累积历史", async () => {
    window.location.hash = "#/list";
    navigate({ name: "chat", conversationId: "c1" });
    await vi.waitFor(() => expect(window.location.hash).toBe("#/chat/c1"));

    const lengthBeforeBack = window.history.length;
    navigateBack({ name: "list" });

    await vi.waitFor(() => expect(window.location.hash).toBe("#/list"));
    expect(window.history.length).toBe(lengthBeforeBack);
    expect(parseHash(window.location.hash)).toEqual({ name: "list" });
  });

  it("深链/刷新直接落在聊天页时以 replace 回列表，不新增条目", () => {
    // 直接赋值 hash 模拟非应用内压栈的既有条目（如刷新后落点）
    window.location.hash = "#/chat/c1";
    const lengthBeforeBack = window.history.length;

    navigateBack({ name: "list" });

    expect(window.location.hash).toBe("#/list");
    expect(window.history.length).toBe(lengthBeforeBack);
    expect(parseHash(window.location.hash)).toEqual({ name: "list" });
  });

  it("连续进出会话不再累积历史", async () => {
    window.location.hash = "#/list";
    navigate({ name: "chat", conversationId: "c1" });
    await vi.waitFor(() => expect(window.location.hash).toBe("#/chat/c1"));
    navigateBack({ name: "list" });
    await vi.waitFor(() => expect(window.location.hash).toBe("#/list"));
    const lengthAfterFirstRound = window.history.length;

    // 第二轮进出
    navigate({ name: "chat", conversationId: "c1" });
    await vi.waitFor(() => expect(window.location.hash).toBe("#/chat/c1"));
    navigateBack({ name: "list" });
    await vi.waitFor(() => expect(window.location.hash).toBe("#/list"));

    expect(window.history.length).toBe(lengthAfterFirstRound);
  });
});
