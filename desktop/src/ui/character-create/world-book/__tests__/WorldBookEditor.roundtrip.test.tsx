import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { clone, deepFreeze } from "../../__tests__/editorHelpers";
import { WorldBookEditor } from "../WorldBookEditor";
import { RICH_BOOK, entryOf, makeHarness } from "./helpers";

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

    const expected = clone(RICH_BOOK);
    entryOf(expected, 0).comment = "世界观总纲（改）";
    entryOf(expected, 1).keys = ["药房"];
    entryOf(expected, 2).extensions = { depth: 3, role: "user" };
    expected.token_budget = 1800;
    expect(getLatest()).toEqual(expected);
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

  it.each<[string, Record<string, unknown> | null]>([
    ["空对象", {}],
    ["空条目列表", { name: "只有名字", entries: [] }],
    ["null", null],
  ])("%s 的世界书呈现引导空态", (_label, book) => {
    render(<WorldBookEditor book={book} onChange={() => {}} />);

    const empty = screen.getByTestId("wb-empty-entries");
    expect(empty).toHaveTextContent("这个世界书还没有条目");
    expect(empty).toHaveTextContent("新建条目");
  });

  it("空书新建条目写入默认条目并保留书级字段", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze({ name: "空书", entries: [] }));
    render(<Harness />);

    fireEvent.click(screen.getByTestId("wb-add-entry"));

    const latest = getLatest()!;
    expect(latest.name).toBe("空书");
    expect(latest.entries).toEqual([
      expect.objectContaining({ enabled: true, insertion_order: 100, position: "before_char" }),
    ]);
  });

  it.each<[string, unknown, string, string]>([
    ["book 不是对象", "不是对象", "wb-editor-invalid", "数据保持原样"],
    ["entries 不是数组", { entries: { note: "不是数组" } }, "wb-entries-malformed", "entries 不是数组"],
  ])("%s 时如实提示数据异常", (_label, book, testId, text) => {
    render(<WorldBookEditor book={book as Record<string, unknown>} onChange={() => {}} />);

    expect(screen.getByTestId(testId)).toHaveTextContent(text);
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
    expect(screen.getByTestId("wb-book-notrun")).toBeInTheDocument();
  });
});
