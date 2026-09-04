import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RICH_BOOK, clone, deepFreeze, entryOf, makeHarness } from "./helpers";

afterEach(cleanup);

function renderRichHarness() {
  const harness = makeHarness(deepFreeze(clone(RICH_BOOK)));
  const utils = render(<harness.Harness />);
  return { ...harness, ...utils };
}

describe("WorldBookEditor 行为", () => {
  it("selectiveLogic 四档切换写回 extensions.selectiveLogic，其余扩展字段不动", () => {
    const { Harness, getLatest } = renderRichHarness();
    fireEvent.click(screen.getByTestId("wb-entry-toggle-0"));

    const select = screen.getByTestId("wb-entry-0-selective-logic") as HTMLSelectElement;
    expect(select.value).toBe("2");

    fireEvent.change(select, { target: { value: "3" } });
    const e0 = entryOf(getLatest()!, 0);
    expect(e0.extensions).toEqual({
      ...(entryOf(RICH_BOOK, 0).extensions as Record<string, unknown>),
      selectiveLogic: 3,
    });

    fireEvent.change(screen.getByTestId("wb-entry-0-selective-logic"), { target: { value: "0" } });
    expect((entryOf(getLatest()!, 0).extensions as Record<string, unknown>).selectiveLogic).toBe(0);
  });

  it("位置切换 after_char → atDepth 展开深度与角色，depth/role 写入 extensions", () => {
    const { Harness, getLatest } = renderRichHarness();
    fireEvent.click(screen.getByTestId("wb-entry-toggle-1"));

    const select = screen.getByTestId("wb-entry-1-position") as HTMLSelectElement;
    expect(select.value).toBe("after_char");
    expect(screen.queryByTestId("wb-entry-1-depth")).not.toBeInTheDocument();

    fireEvent.change(select, { target: { value: "atDepth" } });
    const moved = entryOf(getLatest()!, 1);
    expect(moved.position).toBe("atDepth");

    fireEvent.change(screen.getByTestId("wb-entry-1-depth"), { target: { value: "7" } });
    fireEvent.change(screen.getByTestId("wb-entry-1-role"), { target: { value: "assistant" } });

    const e1 = entryOf(getLatest()!, 1);
    expect(e1.extensions).toEqual({ depth: 7, role: "assistant" });
    expect(e1.keys).toEqual(["中药房"]);
    expect(e1.insertion_order).toBe(50);
  });

  it("atDepth 缺省显示 4/system，留空 depth 删键回缺省", () => {
    const { Harness, getLatest } = renderRichHarness();
    fireEvent.click(screen.getByTestId("wb-entry-toggle-2"));

    expect(screen.getByTestId("wb-entry-2-depth")).toHaveValue("6");
    expect((screen.getByTestId("wb-entry-2-role") as HTMLSelectElement).value).toBe("user");

    fireEvent.change(screen.getByTestId("wb-entry-2-depth"), { target: { value: "" } });
    const ext = entryOf(getLatest()!, 2).extensions as Record<string, unknown>;
    expect("depth" in ext).toBe(false);
    expect(ext.role).toBe("user");
  });

  it("不支持的位置原样保留不静默改写，用户显式选择后才切换", () => {
    const { Harness, getLatest } = renderRichHarness();
    fireEvent.click(screen.getByTestId("wb-entry-toggle-3"));

    const select = screen.getByTestId("wb-entry-3-position") as HTMLSelectElement;
    expect(select.value).toBe("__unsupported__");
    expect(within(select).getByRole("option", { name: /不支持的位置：EMTop/ })).toBeInTheDocument();
    expect(screen.getByTestId("wb-entry-3-notrun-position")).toHaveTextContent("不支持的位置");

    // 编辑同条目其他字段，position 保持 EMTop 原值
    fireEvent.change(screen.getByTestId("wb-entry-3-comment"), { target: { value: "改个备注" } });
    expect(entryOf(getLatest()!, 3).position).toBe("EMTop");

    // 显式选择支持位置后才写入
    fireEvent.change(screen.getByTestId("wb-entry-3-position"), { target: { value: "before_char" } });
    expect(entryOf(getLatest()!, 3).position).toBe("before_char");
    expect(entryOf(getLatest()!, 3).comment).toBe("改个备注");
  });

  it("上下移交换相邻条目并同步交换 insertion_order", () => {
    const { Harness, getLatest } = renderRichHarness();

    expect(screen.getByTestId("wb-entry-up-0")).toBeDisabled();
    expect(screen.getByTestId("wb-entry-down-3")).toBeDisabled();

    fireEvent.click(screen.getByTestId("wb-entry-down-0"));
    let entries = getLatest()!.entries as Record<string, unknown>[];
    expect(entries[0].comment).toBe("中药房");
    expect(entries[0].insertion_order).toBe(100);
    expect(entries[1].comment).toBe("世界观总纲");
    expect(entries[1].insertion_order).toBe(50);

    // 世界观总纲(50) 与 雨夜(200) 交换：雨夜落到 50，世界观总纲升到 200
    fireEvent.click(screen.getByTestId("wb-entry-down-1"));
    entries = getLatest()!.entries as Record<string, unknown>[];
    expect(entries[1].comment).toBe("雨夜相遇");
    expect(entries[1].insertion_order).toBe(50);
    expect(entries[2].comment).toBe("世界观总纲");
    expect(entries[2].insertion_order).toBe(200);
    // 其余条目不受影响
    expect(entries[0]).toEqual({ ...entryOf(RICH_BOOK, 1), insertion_order: 100 });
    expect(entries[3]).toEqual(entryOf(RICH_BOOK, 3));
  });

  it("列表摘要展示启用态/常驻/位置/关键字", () => {
    renderRichHarness();

    const row0 = screen.getByTestId("wb-entry-row-0");
    expect(within(row0).getByText("启用")).toBeInTheDocument();
    expect(within(row0).getByText("角色定义前")).toBeInTheDocument();
    expect(within(row0).getByText(/临海、\/雨\\d\+天\/g/)).toBeInTheDocument();

    const row1 = screen.getByTestId("wb-entry-row-1");
    expect(within(row1).getByText("常驻")).toBeInTheDocument();
    expect(within(row1).getByText("角色定义后")).toBeInTheDocument();

    const row2 = screen.getByTestId("wb-entry-row-2");
    expect(within(row2).getByText("已停用")).toBeInTheDocument();
    expect(within(row2).getByText("对话深度 6 · user")).toBeInTheDocument();

    const row3 = screen.getByTestId("wb-entry-row-3");
    expect(within(row3).getByText(/不支持的位置 EMTop/)).toBeInTheDocument();
  });

  it("空条目列表呈现引导空态并新建默认条目", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze({ name: "空书", entries: [] })) as ReturnType<
      typeof makeHarness
    >;
    render(<Harness />);

    const empty = screen.getByTestId("wb-empty-entries");
    expect(empty).toHaveTextContent("这个世界书还没有条目");
    expect(empty).toHaveTextContent("关键字");
    expect(empty).toHaveTextContent("常驻");

    fireEvent.click(screen.getByTestId("wb-add-entry"));
    const latest = getLatest()!;
    expect(latest.name).toBe("空书");
    const entries = latest.entries as Record<string, unknown>[];
    expect(entries).toHaveLength(1);
    expect(entries[0].enabled).toBe(true);
    expect(entries[0].insertion_order).toBe(100);
    expect(entries[0].position).toBe("before_char");
  });

  it("非法正则关键字只警告不阻断，且不改写关键字", () => {
    const book = {
      entries: [
        {
          keys: ["/([a/"],
          content: "坏正则形态条目",
          enabled: true,
          insertion_order: 1,
          position: "before_char",
          extensions: {},
        },
        {
          keys: ["[bad"],
          use_regex: true,
          content: "裸关键字坏正则",
          enabled: true,
          insertion_order: 2,
          position: "before_char",
          extensions: {},
        },
      ],
    };
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(book)));
    render(<Harness />);

    fireEvent.click(screen.getByTestId("wb-entry-toggle-0"));
    fireEvent.click(screen.getByTestId("wb-entry-toggle-1"));

    const warning0 = screen.getByTestId("wb-entry-0-regex-warning");
    expect(warning0).toHaveTextContent("不是合法正则");
    expect(warning0).toHaveTextContent("退化为字面包含匹配");
    expect(screen.getByTestId("wb-entry-1-regex-warning")).toHaveTextContent("[bad");

    // 警告不阻断编辑，关键字原样保留
    fireEvent.change(screen.getByTestId("wb-entry-0-comment"), { target: { value: "备注" } });
    const latest = getLatest()!;
    expect(latest).not.toBeNull();
    expect((latest.entries as Record<string, unknown>[])[0].keys).toEqual(["/([a/"]);
    expect((latest.entries as Record<string, unknown>[])[1].keys).toEqual(["[bad"]);
  });

  it("存而不运行字段在条目与书级展示「保留但不运行」只读标识", () => {
    renderRichHarness();
    fireEvent.click(screen.getByTestId("wb-entry-toggle-0"));

    const notrun = screen.getByTestId("wb-entry-0-notrun");
    expect(within(notrun).getByTestId("wb-entry-0-notrun-ext-probability")).toHaveTextContent("触发概率");
    expect(within(notrun).getByTestId("wb-entry-0-notrun-ext-sticky")).toBeInTheDocument();
    expect(within(notrun).getByTestId("wb-entry-0-notrun-ext-automationId")).toBeInTheDocument();
    expect(within(notrun).getByTestId("wb-entry-0-notrun-ext-scanDepth")).toBeInTheDocument();
    expect(within(notrun).getByTestId("wb-entry-0-notrun-ext-matchPersonaDescription")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("wb-entry-toggle-2"));
    expect(screen.getByTestId("wb-entry-2-notrun-content-decorator")).toHaveTextContent("@@activate");

    const bookNotrun = screen.getByTestId("wb-book-notrun");
    expect(within(bookNotrun).getByTestId("wb-book-notrun-book-recursive_scanning")).toHaveTextContent(
      "recursive_scanning",
    );
    expect(within(bookNotrun).getByTestId("wb-book-notrun-book-ext-world")).toHaveTextContent("外链世界书");
  });
});
