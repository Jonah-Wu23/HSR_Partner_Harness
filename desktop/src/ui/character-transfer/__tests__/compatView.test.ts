import { describe, expect, it } from "vitest";
import { deriveCompatViewFromCard, groupNotExecuted } from "../compatView";

describe("groupNotExecuted（冻结 §11 分组）", () => {
  it("按世界书字段/未展开宏/非 turn 触发分类，其余进「其他保留项」，不丢弃条目", () => {
    const groups = groupNotExecuted([
      "character_book.entries[2].probability（存而不运行）",
      "character_book.entries[...].sticky（存而不运行，共 3 条）",
      "macro:{{setvar::x::1}} @ data.personality（未展开，2 处）",
      "hsr.event_system.events[0].runtime_trigger.kind=time（存而不运行）",
      "data.extensions.hsr.command_panels",
    ]);

    expect(groups.map((g) => g.key)).toEqual([
      "worldBookStoredFields",
      "unexpandedMacros",
      "nonTurnTrigger",
      "other",
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

describe("deriveCompatViewFromCard（从卡 JSON 派生兼容性视图）", () => {
  it("空卡返回六字段全空", () => {
    expect(deriveCompatViewFromCard({})).toEqual({
      applied: [],
      preserved: [],
      not_executed: [],
      normalized_from_root: [],
      warnings: [],
      errors: [],
    });
  });

  it("世界书存而不运行字段逐条列出；同字段多条目合并计数；位置越界与 @@ 装饰器如实标注", () => {
    const view = deriveCompatViewFromCard({
      data: {
        character_book: {
          entries: [
            { keys: ["a"], content: "内容一", probability: 60, useProbability: true },
            { keys: ["b"], content: "内容二", probability: 100, group: "组A" },
            { keys: ["c"], content: "@@dont_activate 保留内容", position: 3, extensions: { scanDepth: 4 } },
          ],
        },
      },
    });

    expect(view.not_executed).toContain("character_book.entries[0].useProbability（存而不运行）");
    expect(view.not_executed).toContain(
      "character_book.entries[...].probability（存而不运行，共 2 条）",
    );
    expect(view.not_executed).toContain("character_book.entries[1].group（存而不运行）");
    expect(view.not_executed).toContain("character_book.entries[2].position=3（存而不运行，条目不注入）");
    expect(view.not_executed).toContain("character_book.entries[2].content（@@ 装饰器，存而不运行）");
    expect(view.not_executed).toContain("character_book.entries[2].scanDepth（存而不运行）");
    expect(view.warnings).toEqual([]);
  });

  it("extensions.world 外链只对非空值报告，空串视为未挂载", () => {
    const view = deriveCompatViewFromCard({
      data: {
        character_book: {
          entries: [
            { keys: ["a"], content: "x", extensions: { world: "" } },
            { keys: ["b"], content: "y", extensions: { world: "外部世界书" } },
          ],
        },
      },
    });
    expect(view.not_executed).toContain("character_book.entries[1].world（存而不运行）");
    expect(view.not_executed).not.toContain("character_book.entries[0].world（存而不运行）");
  });

  it("非白名单宏按「macro:token @ 字段（未展开，N 处）」合并；{{char}}/{{user}} 与大小写变体不报告", () => {
    const view = deriveCompatViewFromCard({
      data: {
        description: "{{char}}和{{USER}}是伙伴，{{setvar::x::1}}出现了两次 {{setvar::x::1}}，还有 {{random:a,b}}",
        first_mes: "{{time}} 了",
        alternate_greetings: ["{{roll:d20}}"],
      },
    });

    expect(view.not_executed).toContain("macro:{{setvar::x::1}} @ data.description（未展开，2 处）");
    expect(view.not_executed).toContain("macro:{{random:a,b}} @ data.description（未展开）");
    expect(view.not_executed).toContain("macro:{{time}} @ data.first_mes（未展开）");
    expect(view.not_executed).toContain("macro:{{roll:d20}} @ data.alternate_greetings[0]（未展开）");
    expect(view.not_executed.every((item) => !item.includes("{{char}} @"))).toBe(true);
    expect(view.not_executed.every((item) => !item.includes("{{USER}} @"))).toBe(true);
  });

  it("世界书条目 content 中的非白名单宏按条目路径报告", () => {
    const view = deriveCompatViewFromCard({
      data: {
        character_book: {
          entries: [{ keys: ["a"], content: "内容 {{getvar::hp}}" }],
        },
      },
    });
    expect(view.not_executed).toContain(
      "macro:{{getvar::hp}} @ data.character_book.entries[0].content（未展开）",
    );
  });

  it("runtime_trigger 仅 turn kind 被执行，非 turn 与缺失 kind 进 not_executed（路径含下标）", () => {
    const view = deriveCompatViewFromCard({
      data: {
        extensions: {
          hsr: {
            event_system: {
              events: [
                { runtime_trigger: { kind: "time", turn: 7 } },
                { runtime_trigger: { kind: "turn", turn: 12 } },
                { note: "普通条目" },
                { runtime_trigger: {} },
              ],
            },
          },
        },
      },
    });

    expect(view.not_executed).toContain(
      "hsr.event_system.events[0].runtime_trigger.kind=time（存而不运行）",
    );
    expect(view.not_executed).toContain(
      "hsr.event_system.events[3].runtime_trigger.kind=缺失（存而不运行）",
    );
    expect(
      view.not_executed.some((item) => item.includes("kind=turn")),
    ).toBe(false);
  });

  it("selectiveLogic 越界值进 warnings，0-3 不报告", () => {
    const view = deriveCompatViewFromCard({
      data: {
        character_book: {
          entries: [
            { keys: ["a"], content: "x", extensions: { selectiveLogic: 7 } },
            { keys: ["b"], content: "y", extensions: { selectiveLogic: 2 } },
          ],
        },
      },
    });
    expect(view.warnings).toEqual([
      "character_book.entries[0].extensions.selectiveLogic=7（越界，运行时按 0 处理）",
    ]);
  });

  it("导入时事实字段（applied/preserved/normalized_from_root/errors）恒为空，不伪造结论", () => {
    const view = deriveCompatViewFromCard({
      data: { description: "带 {{setvar::x::1}} 的卡" },
    });
    expect(view.applied).toEqual([]);
    expect(view.preserved).toEqual([]);
    expect(view.normalized_from_root).toEqual([]);
    expect(view.errors).toEqual([]);
  });
});
