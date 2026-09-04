import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RICH_HSR, clone, deepFreeze, makeHarness } from "./helpers";

afterEach(cleanup);

function renderRichHarness() {
  const harness = makeHarness(deepFreeze(clone(RICH_HSR)));
  const utils = render(<harness.Harness />);
  return { ...harness, ...utils };
}

describe("CommandPanelsView 只读声明式呈现", () => {
  it("标注「仅保存为数据，不会在应用内执行」，面板以转义文本呈现，无任何编辑控件", () => {
    const { container } = renderRichHarness();

    expect(screen.getByTestId("mufy-command-panels-notice")).toHaveTextContent("仅保存为数据，不会在应用内执行");

    const section = screen.getByTestId("mufy-command-panels");
    expect(within(section).getAllByTestId(/^mufy-command-panel-/)).toHaveLength(2);
    // HTML/script 原文作为文本展示，不进入 DOM 结构
    expect(container.querySelector("script")).toBeNull();
    const card0 = screen.getByTestId("mufy-command-panel-0");
    expect(card0.textContent).toContain('<div class="status-panel"><script>alert(1)</script></div>');
    expect(card0.textContent).toContain("$状态");

    // 只读：无输入框、无勾选框、无按钮
    expect(within(section).queryAllByRole("textbox")).toHaveLength(0);
    expect(within(section).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(section).queryAllByRole("button")).toHaveLength(0);
    expect(within(section).queryAllByRole("spinbutton")).toHaveLength(0);
  });

  it("非对象面板条目与非数组 command_panels 以原始 JSON 呈现", () => {
    renderRichHarness();

    const card1 = screen.getByTestId("mufy-command-panel-1");
    expect(card1.textContent).toContain("纯文本面板条目");

    cleanup();
    const mixed = makeHarness({ command_panels: { note: "不是数组" } });
    render(<mixed.Harness />);
    const section = screen.getByTestId("mufy-command-panels");
    expect(section.textContent).toContain("不是数组");
    expect(section.textContent).toContain("原始数据");
  });

  it("未声明 command_panels 时呈现空态", () => {
    const { Harness } = makeHarness({});
    render(<Harness />);

    expect(screen.getByTestId("mufy-command-panels-empty")).toHaveTextContent("未声明 command_panels 数据");
  });

  it("编辑其他分区后 command_panels 深度不变", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    fireEvent.change(screen.getByTestId("mufy-value-world_architecture.world_foundation.one_line_pitch"), {
      target: { value: "改动世界描述。" },
    });

    const latest = getLatest();
    expect(latest).not.toBeNull();
    expect(latest!.command_panels).toEqual(RICH_HSR.command_panels);
  });
});
