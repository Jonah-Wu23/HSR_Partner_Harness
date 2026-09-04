import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WorldBookEditor } from "../WorldBookEditor";
import { RICH_BOOK, clone, deepFreeze, entryOf, makeHarness } from "./helpers";

afterEach(cleanup);

function renderRichHarness() {
  const harness = makeHarness(deepFreeze(clone(RICH_BOOK)));
  const utils = render(<harness.Harness />);
  return { ...harness, ...utils };
}

describe("WorldBookEditor 编辑往返保真", () => {
  it("各条目各编辑一处 + 书级预算，未触及字段（含存而不运行字段与未知 extras）全部原样保留", () => {
    const { Harness, getLatest } = renderRichHarness();

    for (const index of [0, 1, 2]) {
      fireEvent.click(screen.getByTestId(`wb-entry-toggle-${index}`));
    }
    fireEvent.change(screen.getByTestId("wb-entry-0-comment"), { target: { value: "世界观总纲（改）" } });
    fireEvent.change(screen.getByTestId("wb-entry-1-keys-0"), { target: { value: "药房" } });
    fireEvent.change(screen.getByTestId("wb-entry-2-depth"), { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("wb-token-budget"), { target: { value: "1800" } });

    const latest = getLatest();
    expect(latest).not.toBeNull();

    // 未触及字段逐一核对：条目级存而不运行字段、未知 extras、书级未知键
    const e0 = entryOf(latest!, 0);
    expect(e0.extensions).toEqual(RICH_BOOK_EXTENSIONS_0_WITH_LOGIC(2));
    expect((e0.extensions as Record<string, unknown>).unknown_ext).toEqual([1, "two"]);
    expect(entryOf(latest!, 1).future_unknown).toEqual({ nested: true });
    expect(entryOf(latest!, 3).position).toBe("EMTop");
    expect(latest!.recursive_scanning).toBe(true);
    expect(latest!.extensions).toEqual(RICH_BOOK.extensions);

    // 全量对比
    const expected = clone(RICH_BOOK);
    entryOf(expected, 0).comment = "世界观总纲（改）";
    entryOf(expected, 1).keys = ["药房"];
    entryOf(expected, 2).extensions = { depth: 3, role: "user" };
    expected.token_budget = 1800;
    expect(latest).toEqual(expected);
  });

  it("新建条目只追加默认条目，既有内容全部保留", () => {
    const { Harness, getLatest } = renderRichHarness();

    fireEvent.click(screen.getByTestId("wb-add-entry"));

    const latest = getLatest();
    expect(latest).not.toBeNull();
    const entries = latest!.entries as Record<string, unknown>[];
    expect(entries).toHaveLength(5);
    expect(entries[4]).toEqual({
      keys: [],
      secondary_keys: [],
      content: "",
      comment: "",
      enabled: true,
      insertion_order: 100,
      position: "before_char",
      constant: false,
      selective: false,
      case_sensitive: false,
      use_regex: false,
      extensions: {},
    });
    for (let i = 0; i < 4; i += 1) {
      expect(entries[i]).toEqual(entryOf(RICH_BOOK, i));
    }
  });

  it("复制在原位插入完整副本，删除只移除目标条目", () => {
    const { Harness, getLatest } = renderRichHarness();

    fireEvent.click(screen.getByTestId("wb-entry-toggle-1"));
    fireEvent.click(screen.getByTestId("wb-entry-copy-1"));
    let latest = getLatest()!;
    let entries = latest.entries as Record<string, unknown>[];
    expect(entries).toHaveLength(5);
    expect(entries[2]).toEqual(entryOf(RICH_BOOK, 1));
    expect(entries[2]).not.toBe(entries[1]);

    fireEvent.click(screen.getByTestId("wb-entry-remove-1"));
    latest = getLatest()!;
    entries = latest.entries as Record<string, unknown>[];
    expect(entries).toHaveLength(4);
    expect(entries[1]).toEqual(entryOf(RICH_BOOK, 1));
    expect(entries[2]).toEqual(entryOf(RICH_BOOK, 2));
    expect(entries[3]).toEqual(entryOf(RICH_BOOK, 3));
  });

  it("scan_depth / token_budget 留空即删键回缺省语义", () => {
    const { Harness, getLatest } = renderRichHarness();

    fireEvent.change(screen.getByTestId("wb-scan-depth"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("wb-token-budget"), { target: { value: "" } });

    const latest = getLatest()!;
    expect("scan_depth" in latest).toBe(false);
    expect("token_budget" in latest).toBe(false);
    expect(latest.entries).toEqual(RICH_BOOK.entries);
  });

  it("空书呈现引导空态；null book 也走空态；非对象 entries 如实暴露", () => {
    const empty = makeHarness({});
    render(<empty.Harness />);
    expect(screen.getByTestId("wb-empty-entries")).toHaveTextContent("这个世界书还没有条目");
    expect(screen.getByTestId("wb-empty-entries")).toHaveTextContent("新建条目");
    fireEvent.click(screen.getByTestId("wb-add-entry"));
    expect(empty.getLatest()).toEqual({ entries: [expect.any(Object)] });
    const added = (empty.getLatest()!.entries as Record<string, unknown>[])[0];
    expect(added.enabled).toBe(true);
    expect(added.insertion_order).toBe(100);
    expect(added.position).toBe("before_char");
    cleanup();

    const emptyList = makeHarness({ name: "只有名字", entries: [] });
    render(<emptyList.Harness />);
    expect(screen.getByTestId("wb-empty-entries")).toBeInTheDocument();
    cleanup();

    render(
      <WorldBookEditor book={null} onChange={() => {}} />,
    );
    expect(screen.getByTestId("wb-empty-entries")).toBeInTheDocument();
    cleanup();

    render(
      <WorldBookEditor book={"不是对象" as unknown as Record<string, unknown>} onChange={() => {}} />,
    );
    expect(screen.getByTestId("wb-editor-invalid")).toHaveTextContent("数据保持原样");
    cleanup();

    const malformed = makeHarness({ entries: { note: "不是数组" } });
    render(<malformed.Harness />);
    expect(screen.getByTestId("wb-entries-malformed")).toHaveTextContent("entries 不是数组");
  });

  it("readOnly 模式无任何编辑入口且输入禁用", () => {
    const { Harness } = makeHarness(deepFreeze(clone(RICH_BOOK)), { readOnly: true });
    render(<Harness />);

    expect(screen.getByTestId("wb-scan-depth")).toBeDisabled();
    expect(screen.getByTestId("wb-token-budget")).toBeDisabled();
    expect(screen.queryByTestId("wb-add-entry")).not.toBeInTheDocument();
    expect(screen.getByTestId("wb-entry-toggle-0")).toBeInTheDocument();
    expect(screen.queryByTestId("wb-entry-up-0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("wb-entry-copy-0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("wb-entry-remove-0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("wb-book-notrun")).not.toBeNull();
  });
});

/** entry0.extensions 的期望值（selectiveLogic 可变，其余原样）。 */
function RICH_BOOK_EXTENSIONS_0_WITH_LOGIC(logic: number): Record<string, unknown> {
  const extensions = clone((entryOf(RICH_BOOK, 0).extensions ?? {}) as Record<string, unknown>);
  extensions.selectiveLogic = logic;
  return extensions;
}
