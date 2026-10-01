import { describe, expect, it } from "vitest";
import { groupNotExecuted } from "../compatView";

describe("groupNotExecuted 按 category 分组", () => {
  it("按后端 category 分组，组序固定，不丢弃条目", () => {
    const groups = groupNotExecuted([
      { category: "command_panels", text: "data.extensions.hsr.command_panels" },
      { category: "world_book", text: "character_book.entries[2].probability（存而不运行）" },
      { category: "macro", text: "macro:{{setvar::x::1}} @ data.personality（未展开，2 处）" },
      { category: "world_book", text: "character_book.entries[...].sticky（存而不运行，共 3 条）" },
      {
        category: "runtime_trigger",
        text: "hsr.event_system.events[0].runtime_trigger.kind=time（存而不运行）",
      },
    ]);

    expect(groups.map((g) => g.category)).toEqual([
      "world_book",
      "macro",
      "runtime_trigger",
      "command_panels",
    ]);
    expect(groups[0].items).toEqual([
      "character_book.entries[2].probability（存而不运行）",
      "character_book.entries[...].sticky（存而不运行，共 3 条）",
    ]);
    expect(groups[1].items).toEqual(["macro:{{setvar::x::1}} @ data.personality（未展开，2 处）"]);
    expect(groups[2].items).toEqual([
      "hsr.event_system.events[0].runtime_trigger.kind=time（存而不运行）",
    ]);
    expect(groups[3].items).toEqual(["data.extensions.hsr.command_panels"]);
  });

  it("空列表返回空分组", () => {
    expect(groupNotExecuted([])).toEqual([]);
  });
});
