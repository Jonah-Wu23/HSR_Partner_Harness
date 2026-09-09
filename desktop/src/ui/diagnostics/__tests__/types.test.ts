import { describe, expect, it } from "vitest";

import { adaptMetricsQueryResult, adaptPromptAssembly } from "../types";

describe("诊断适配层（V0.3.9 V03）", () => {
  it("prompt_assembly 缺 modules 时抛真实错误并列出实际字段", () => {
    expect(() => adaptPromptAssembly({ conversation_id: "c1" })).toThrowError(
      /缺少 modules 数组（实际字段：conversation_id）/,
    );
  });

  it("prompt_assembly 模块缺 name 时抛错，不静默跳过", () => {
    expect(() => adaptPromptAssembly({ modules: [{ hash: "abc" }] })).toThrowError(
      /modules\[0\]\.name 缺失或不是非空字符串/,
    );
  });

  it("prompt_assembly 字段缺失保持 null，0 保持 0", () => {
    const view = adaptPromptAssembly({
      conversation_id: "c1",
      generated_at: "2026-01-01T00:00:00Z",
      diagnostics: ["ok"],
      modules: [
        { name: "character_frame", char_start: 0, char_end: 512, hash: "abc", summary: "角色框架" },
        { name: "pair_memory", memory_injected: true },
      ],
    });

    expect(view.modules[0]).toMatchObject({
      char_start: 0,
      char_end: 512,
      memory_injected: null,
      hidden_content: null,
    });
    expect(view.modules[1]).toMatchObject({
      char_start: null,
      char_end: null,
      hash: null,
      summary: null,
      memory_injected: true,
    });
    expect(view.diagnostics).toEqual(["ok"]);
  });

  it("metrics 缺契约字段时抛错（键必须存在）", () => {
    expect(() =>
      adaptMetricsQueryResult({ metrics: [{ metric_id: "tm-1", conversation_id: "c1" }] }),
    ).toThrowError(/缺少契约字段：.*tool_rounds/);
  });

  it("metrics 结果正常适配并保留 null 与 0", () => {
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
