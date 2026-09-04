import { useState } from "react";
import { WorldBookEditor } from "../WorldBookEditor";

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** 深冻结：任何对既有数据的原地修改都会在严格模式下抛 TypeError，锁定不突变。 */
export function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    for (const child of Object.values(value as Record<string, unknown>)) {
      deepFreeze(child);
    }
    Object.freeze(value);
  }
  return value;
}

export function makeHarness(initial: Record<string, unknown>, options?: { readOnly?: boolean }) {
  let latest: Record<string, unknown> | null = null;
  function Harness() {
    const [book, setBook] = useState(initial);
    return (
      <WorldBookEditor
        book={book}
        onChange={(next) => {
          latest = next;
          setBook(next);
        }}
        readOnly={options?.readOnly ?? false}
      />
    );
  }
  return { Harness, getLatest: () => latest };
}

export function entryOf(book: Record<string, unknown>, index: number): Record<string, unknown> {
  return (book.entries as Record<string, unknown>[])[index];
}

export const RICH_BOOK: Record<string, unknown> = {
  name: "临海世界书",
  description: "港口城市背景设定",
  scan_depth: 3,
  token_budget: 1500,
  recursive_scanning: true,
  extensions: { world: "外部世界书链接", unknown_book_ext: { keep: true } },
  entries: [
    {
      keys: ["临海", "/雨\\d+天/g"],
      secondary_keys: ["港口"],
      content: "临海是一座永远下雨的港口城市。",
      comment: "世界观总纲",
      enabled: true,
      insertion_order: 100,
      constant: false,
      selective: true,
      position: "before_char",
      case_sensitive: false,
      use_regex: false,
      id: 101,
      extensions: {
        selectiveLogic: 2,
        probability: 60,
        useProbability: true,
        sticky: 3,
        cooldown: 2,
        delay: 1,
        group: "weather",
        groupOverride: false,
        groupWeight: 100,
        automationId: "auto-1",
        ignoreBudget: true,
        scanDepth: 5,
        matchPersonaDescription: true,
        matchCharacterDescription: false,
        excludeRecursion: true,
        minActivations: 1,
        unknown_ext: [1, "two"],
      },
    },
    {
      keys: ["中药房"],
      secondary_keys: [],
      content: "旧城区的中药房，第7天失火。",
      comment: "中药房",
      enabled: true,
      insertion_order: 50,
      constant: true,
      selective: false,
      position: 1,
      extensions: {},
      future_unknown: { nested: true },
    },
    {
      keys: ["雨夜"],
      content: "@@activate 雨夜在灯笼下相遇的桥段。",
      comment: "雨夜相遇",
      enabled: false,
      insertion_order: 200,
      constant: false,
      position: "atDepth",
      extensions: { depth: 6, role: "user" },
    },
    {
      keys: ["EM 条目"],
      content: "作者注释区域条目。",
      comment: "不支持位置",
      enabled: true,
      insertion_order: 10,
      position: "EMTop",
      extensions: { role: 2 },
    },
  ],
};
