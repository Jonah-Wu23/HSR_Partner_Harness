import { describe, expect, it } from "vitest";

import { adaptMetricsQueryResult, adaptPromptAssembly } from "../types";

describe("诊断结果协议校验", () => {
  it.each([
    [
      "prompt_assembly 缺 modules 数组",
      () => adaptPromptAssembly({ conversation_id: "c1" }),
      /缺少 modules 数组（实际字段：conversation_id）/,
    ],
    [
      "装配模块缺 name",
      () => adaptPromptAssembly({ modules: [{ hash: "abc" }] }),
      /modules\[0\]\.name 缺失或不是非空字符串/,
    ],
    [
      "装配模块的字符范围不是数字",
      () => adaptPromptAssembly({ modules: [{ name: "character_frame", char_start: "0" }] }),
      /modules\[0\]\.char_start：期望数字或 null，实际收到 string/,
    ],
    [
      "metrics 记录缺协议字段",
      () => adaptMetricsQueryResult({ metrics: [{ metric_id: "tm-1", conversation_id: "c1" }] }),
      /缺少协议字段：.*tool_rounds/,
    ],
  ])("%s时抛出带实际内容的错误，不静默跳过", (_name, adapt, message) => {
    expect(adapt).toThrowError(message);
  });

  it("prompt_assembly 保留 null 与真实零值的区别", () => {
    // Sidecar 的装配结果：hash 与 summary 恒为 null，未请求原文时 hidden_content 为 null。
    const view = adaptPromptAssembly({
      conversation_id: "c1",
      source: "card",
      reason: null,
      generated_at: "2026-01-01T00:00:00+00:00",
      diagnostics: ["unexpanded_macros: 无"],
      modules: [
        {
          name: "character_frame",
          char_start: 0,
          char_end: 512,
          hash: null,
          summary: null,
          memory_injected: false,
          hidden_content: null,
        },
      ],
    });

    expect(view.modules).toEqual([
      {
        name: "character_frame",
        char_start: 0,
        char_end: 512,
        hash: null,
        summary: null,
        memory_injected: false,
        hidden_content: null,
      },
    ]);
    expect(view.diagnostics).toEqual(["unexpanded_macros: 无"]);
  });

  it("metrics 结果保留 null 与 0，并带回下一页游标", () => {
    const metric = {
      metric_id: "tm-1",
      account_id: "acct-1",
      project_id: "proj-1",
      conversation_id: "c1",
      pair_id: "pair-1",
      character_ref: "card:card-1",
      turn_kind: "character_turn",
      turn_id: "turn-1",
      task_id: null,
      engine_turn_id: null,
      provider: null,
      model: null,
      engine_type: null,
      reasoning_effort: null,
      status: "completed",
      started_at: "2026-01-01T00:00:00Z",
      first_event_at: null,
      completed_at: null,
      duration_ms: null,
      input_tokens: null,
      output_tokens: null,
      total_tokens: null,
      tool_rounds: 0,
      compression_count: 0,
      approval_count: 0,
      failure_type: null,
      failure_message: null,
      origin: "desktop",
      remote_device_key: null,
      remote_device_name: null,
    };
    const result = adaptMetricsQueryResult({ metrics: [metric], next_cursor: "cursor-2" });
    expect(result.metrics[0].input_tokens).toBeNull();
    expect(result.metrics[0].tool_rounds).toBe(0);
    expect(result.next_cursor).toBe("cursor-2");
  });
});
