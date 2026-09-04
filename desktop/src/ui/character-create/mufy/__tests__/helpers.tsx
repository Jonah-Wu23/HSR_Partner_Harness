import { useState } from "react";
import type { ReactElement } from "react";
import { MufyAdvancedEditor } from "../MufyAdvancedEditor";

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
    const [hsr, setHsr] = useState(initial);
    return (
      <MufyAdvancedEditor
        hsr={hsr}
        onChange={(next) => {
          latest = next;
          setHsr(next);
        }}
        readOnly={options?.readOnly ?? false}
      />
    );
  }
  return { Harness, getLatest: () => latest };
}

export const RICH_HSR: Record<string, unknown> = {
  schema_version: "1.0",
  world_architecture: {
    world_foundation: {
      one_line_pitch: "一座永远下雨的港口城市。",
      genre_tone: { primary_genre: "现代都市", sub_genres: ["公路电影", "慢节奏生活"] },
    },
    geography: {
      primary_setting: {
        city_name: "临海",
        districts: [{ name: "旧港", atmosphere: "霓虹灯把雨水染成粉色" }],
      },
    },
    legacy_note: "旧版字段",
    unknown_mapping: { nested_unknown: [1, "two", null, true] },
  },
  character_architecture: {
    identity: { full_name: "白厄", nicknames: ["阿厄"] },
    psychological_core: { core_fear: "被证明不值得被爱" },
    extra_unknown_number: 42,
  },
  relationship_system: {
    relationship_gates: {
      progression_rule: "严格慢热。",
      stages: [{ stage: "阶段一", name: "警戒" }],
    },
    with_user: { 关系定位: "合伙人", 已确认关系: true },
  },
  event_system: {
    timeline_events: {
      absolute_timeline: {
        rule: "既定剧情节点。",
        events: [{ time: "第7天", event: "中药房失火。", runtime_trigger: { kind: "turn", turn: 7, once: true } }],
      },
      relative_timeline: {
        time_unit: "天",
        events: [{ trigger_after: "3天", event: "梅雨季开始，连续下雨。" }],
      },
    },
    conditional_triggers: {
      relationship_triggers: [{ condition: "好感度达到试探阶段", event: "他开始在常坐的位置放靠垫（不说）。" }],
    },
    prose_trigger: { time: "第7天", condition: "旧式散文触发条目，按未知键保留" },
  },
  narrative_rules: {
    pacing: { 整体节奏: "慢热——前期以日常碎片累积情感存量。" },
    violence_rules: "不回避暴力场景但不做猎奇化渲染。",
  },
  command_panels: [
    {
      command: "$状态",
      function: "显示角色当前状态",
      time_pause: false,
      output_format: '<div class="status-panel"><script>alert(1)</script></div>',
    },
    "纯文本面板条目",
  ],
  avatar_asset: { asset_id: "asset-1", source: "png_import", mime_type: "image/png" },
  voice_profile: { state: "voice_ready", voice_id: "qwen-audio-3.0-tts-flash-test" },
  future_extension: { invented: true },
};

export const BLOCK_KEYS = [
  "world_architecture",
  "character_architecture",
  "relationship_system",
  "event_system",
  "narrative_rules",
] as const;
