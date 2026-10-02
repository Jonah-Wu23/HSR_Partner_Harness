import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { clone, deepFreeze } from "../../__tests__/editorHelpers";
import { BLOCK_KEYS, RICH_HSR, makeHarness } from "./helpers";

afterEach(cleanup);

function blockOf(hsr: Record<string, unknown>, key: string): Record<string, unknown> {
  return hsr[key] as Record<string, unknown>;
}

describe("MufyAdvancedEditor 五块编辑往返保真", () => {
  it("五块各编辑一处，未触及字段（含未知键、受管理字段、command_panels）全部原样保留", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    fireEvent.change(screen.getByTestId("mufy-value-world_architecture.world_foundation.one_line_pitch"), {
      target: { value: "一座雨夜不停歇的港口城市。" },
    });
    fireEvent.click(screen.getByTestId("mufy-value-character_architecture.identity.nicknames-add"));
    fireEvent.change(screen.getByTestId("mufy-value-character_architecture.identity.nicknames-1"), {
      target: { value: "小厄" },
    });
    fireEvent.change(screen.getByTestId("mufy-value-relationship_system.with_user.关系定位"), {
      target: { value: "并肩者" },
    });
    fireEvent.click(screen.getByTestId("mufy-value-relationship_system.with_user.已确认关系"));
    fireEvent.change(
      screen.getByTestId("mufy-value-event_system.conditional_triggers.relationship_triggers.0.condition"),
      { target: { value: "好感度达到交付阶段" } },
    );
    fireEvent.change(screen.getByTestId("mufy-value-narrative_rules.violence_rules"), {
      target: { value: "用克制的笔触写残酷，不做猎奇化渲染。" },
    });

    const expected = clone(RICH_HSR);
    const foundation = blockOf(expected, "world_architecture").world_foundation as Record<string, unknown>;
    blockOf(expected, "world_architecture").world_foundation = {
      ...foundation,
      one_line_pitch: "一座雨夜不停歇的港口城市。",
    };
    const identity = blockOf(expected, "character_architecture").identity as Record<string, unknown>;
    identity.nicknames = ["阿厄", "小厄"];
    blockOf(expected, "relationship_system").with_user = { 关系定位: "并肩者", 已确认关系: false };
    const triggers = blockOf(expected, "event_system").conditional_triggers as Record<string, unknown>;
    (triggers.relationship_triggers as Record<string, unknown>[])[0].condition = "好感度达到交付阶段";
    expected.narrative_rules = {
      ...(expected.narrative_rules as Record<string, unknown>),
      violence_rules: "用克制的笔触写残酷，不做猎奇化渲染。",
    };

    expect(getLatest()).toEqual(expected);
  });

  it.each([
    {
      label: "块内未知键",
      path: "world_architecture.legacy_note",
      original: "旧版字段",
      applyTo: (hsr: Record<string, unknown>, value: unknown) => {
        blockOf(hsr, "world_architecture").legacy_note = value;
      },
    },
    {
      label: "顶层未知键",
      path: "future_extension",
      original: "invented",
      applyTo: (hsr: Record<string, unknown>, value: unknown) => {
        hsr.future_extension = value;
      },
    },
  ])("$label 以 raw JSON 呈现，应用编辑后其余内容原样保留", ({ path, original, applyTo }) => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    const raw = screen.getByTestId(`mufy-raw-${path}`) as HTMLTextAreaElement;
    expect(raw.value).toContain(original);
    fireEvent.change(raw, { target: { value: '{"text":"新注释","list":[1,2,3]}' } });
    fireEvent.click(screen.getByTestId(`mufy-raw-${path}-apply`));

    const expected = clone(RICH_HSR);
    applyTo(expected, { text: "新注释", list: [1, 2, 3] });
    expect(getLatest()).toEqual(expected);
  });

  it("raw JSON 解析失败时如实报错，且不产生任何改动", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    const raw = screen.getByTestId("mufy-raw-world_architecture.legacy_note");
    fireEvent.change(raw, { target: { value: "{broken json" } });
    fireEvent.click(screen.getByTestId("mufy-raw-world_architecture.legacy_note-apply"));

    const error = screen.getByTestId("mufy-raw-world_architecture.legacy_note-error");
    expect(error).toHaveTextContent("JSON 解析失败");
    expect(getLatest()).toBeNull();
  });

  it("对象列表可添加条目并通过逐键添加字段完成编辑，不丢其他内容", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    fireEvent.click(screen.getByTestId("mufy-objlist-add-world_architecture.geography.primary_setting.districts"));
    fireEvent.change(
      screen.getByTestId("mufy-addkey-input-world_architecture.geography.primary_setting.districts.1"),
      { target: { value: "name" } },
    );
    fireEvent.click(
      screen.getByTestId("mufy-addkey-apply-world_architecture.geography.primary_setting.districts.1"),
    );
    fireEvent.change(screen.getByTestId("mufy-value-world_architecture.geography.primary_setting.districts.1.name"), {
      target: { value: "灯塔区" },
    });

    const expected = clone(RICH_HSR);
    const geography = blockOf(expected, "world_architecture").geography as Record<string, unknown>;
    (geography.primary_setting as Record<string, unknown>).districts = [
      { name: "旧港", atmosphere: "霓虹灯把雨水染成粉色" },
      { name: "灯塔区" },
    ];
    expect(getLatest()).toEqual(expected);
  });

  it("字符串列表增删改不丢其他内容", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    const prefix = "mufy-value-world_architecture.world_foundation.genre_tone.sub_genres";
    fireEvent.change(screen.getByTestId(`${prefix}-0`), { target: { value: "公路旅行" } });
    fireEvent.click(screen.getByTestId(`${prefix}-add`));
    fireEvent.change(screen.getByTestId(`${prefix}-2`), { target: { value: "灰色道德" } });
    fireEvent.click(screen.getByTestId(`${prefix}-1-remove`));

    const expected = clone(RICH_HSR);
    const foundation = blockOf(expected, "world_architecture").world_foundation as Record<string, unknown>;
    (foundation.genre_tone as Record<string, unknown>).sub_genres = ["公路旅行", "灰色道德"];
    expect(getLatest()).toEqual(expected);
  });

  it("空 hsr 渲染五块空态，引导添加只写入选定键", () => {
    const { Harness, getLatest } = makeHarness({});
    render(<Harness />);

    for (const key of BLOCK_KEYS) {
      expect(screen.getByTestId(`mufy-empty-${key}`)).toBeInTheDocument();
    }
    expect(screen.queryByTestId("mufy-other-fields")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("mufy-add-world_architecture.world_foundation"));
    expect(getLatest()).toEqual({ world_architecture: { world_foundation: {} } });
  });

  it("readOnly 模式下输入禁用且无任何编辑入口", () => {
    const { Harness } = makeHarness(deepFreeze(clone(RICH_HSR)), { readOnly: true });
    render(<Harness />);

    expect(screen.getByTestId("mufy-value-world_architecture.world_foundation.one_line_pitch")).toBeDisabled();
    expect(screen.getByTestId("mufy-value-schema_version")).toBeDisabled();
    expect(screen.queryByTestId("mufy-add-world_architecture.world_foundation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mufy-addkey-apply-world_architecture")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mufy-block-raw-world_architecture")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mufy-objlist-add-world_architecture.geography.primary_setting.districts")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("mufy-trigger-event_system.timeline_events.absolute_timeline.events.0-turn"),
    ).not.toBeInTheDocument();
  });

  it("受管理字段（schema_version/avatar_asset/voice_profile）在可编辑模式下也只读展示", () => {
    const { Harness } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    expect(screen.getByTestId("mufy-value-schema_version")).toBeDisabled();
    expect(screen.getByTestId("mufy-value-avatar_asset.asset_id")).toBeDisabled();
    expect(screen.getByTestId("mufy-value-voice_profile.state")).toBeDisabled();
    expect(screen.queryByTestId("mufy-json-toggle-schema_version")).not.toBeInTheDocument();
  });
});
