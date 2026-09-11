import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, it } from "vitest";

import { AppShell } from "../../AppShell";
import type { MockScenarioName } from "../../../mocks/scenarios";
import { createMockScenario } from "../../../mocks/scenarios";
import { presentAppShell } from "../../../presenters/presenters";
import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";

async function renderScenario(name: MockScenarioName) {
  const backend = new MockDesktopBackend(name);
  const controller = createActionController(backend);
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  const present = () => presentAppShell(desktopStore.getState());
  const start = performance.now();
  const { rerender } = render(<AppShell vm={present()} actions={controller.actions} />);
  const ms = performance.now() - start;
  return { backend, controller, rerender, present, ms };
}

function report(label: string, ms: number) {
  const nodes = document.querySelectorAll("*").length;
  console.log(`[perf] ${label}: render=${ms.toFixed(1)}ms nodes=${nodes}`);
  return nodes;
}

describe("V05 基线测量（jsdom 离线，非真机/浏览器证据）", () => {
  afterEach(() => {
    cleanup();
    desktopStore.getState().setStatus("booting");
  });

  it("performance-500 消息流 + 流式 rerender 成本", async () => {
    const { rerender, present, controller, ms } = await renderScenario("performance-500");
    report("performance-500 初次渲染", ms);
    // 模拟 10 次流式 delta：消息数不变、最后一条文本增长
    let rectCalls = 0;
    const original = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function (this: Element) {
      rectCalls += 1;
      return original.call(this);
    };
    try {
      const state = desktopStore.getState();
      for (let i = 0; i < 10; i += 1) {
        desktopStore.getState().applyEvents([
          {
            kind: "event",
            event: "message.delta",
            sequence: 100 + i,
            payload: {
              message_id: "message-1",
              conversation_id: state.currentConversationId,
              source: "user",
              kind: "user.text",
              delta: "…",
            },
          },
        ]);
        rerender(<AppShell vm={present()} actions={controller.actions} />);
      }
    } finally {
      Element.prototype.getBoundingClientRect = original;
    }
    console.log(`[perf] performance-500 10 次流式 rerender getBoundingClientRect=${rectCalls}`);
  });

  it("perf-many-conversations 导航聊天列表", async () => {
    const { ms } = await renderScenario("perf-many-conversations");
    report("perf-many-conversations（400 聊天）", ms);
  });

  it("perf-many-projects 项目轨道", async () => {
    const { ms } = await renderScenario("perf-many-projects");
    report("perf-many-projects（200 项目）", ms);
  });

  it("perf-long-workbench 工作台时间线", async () => {
    const { ms, controller, rerender, present } = await renderScenario("perf-long-workbench");
    report("perf-long-workbench 初次渲染（chat 模式）", ms);
    await controller.actions.switchMode("collaboration");
    const start = performance.now();
    rerender(<AppShell vm={present()} actions={controller.actions} />);
    report("perf-long-workbench 工作台展开", performance.now() - start);
  });

  it("many-projects 基准", async () => {
    const { ms } = await renderScenario("many-projects");
    report("many-projects（5 项目 × 6 聊天）", ms);
  });

  it("场景构造耗时", () => {
    for (const name of ["performance-500", "perf-many-conversations", "perf-many-projects", "perf-long-workbench"] as const) {
      const start = performance.now();
      createMockScenario(name);
      console.log(`[perf] createMockScenario(${name})=${(performance.now() - start).toFixed(1)}ms`);
    }
  });
});
