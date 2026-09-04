import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RICH_HSR, clone, deepFreeze, makeHarness } from "./helpers";

afterEach(cleanup);

const EVENTS_PATH = "event_system.timeline_events.absolute_timeline.events.0";

function eventSystemFixture(runtimeTrigger: unknown): Record<string, unknown> {
  return {
    event_system: {
      timeline_events: {
        absolute_timeline: {
          events: [{ time: "第7天", event: "中药房失火。", runtime_trigger: runtimeTrigger }],
        },
      },
    },
  };
}

function eventsOf(latest: Record<string, unknown>): Record<string, unknown> {
  const timeline = (latest.event_system as Record<string, unknown>).timeline_events as Record<string, unknown>;
  const absolute = timeline.absolute_timeline as Record<string, unknown>;
  return (absolute.events as unknown[])[0] as Record<string, unknown>;
}

describe("MufyAdvancedEditor runtime_trigger（冻结契约 §6）", () => {
  it("kind=turn 显示「第 N 回合触发」徽章，turn 与 once 可编辑且其余字段原样保留", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(eventSystemFixture({ kind: "turn", turn: 7, once: true }))));
    render(<Harness />);

    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-badge`)).toHaveTextContent("第 7 回合触发");

    fireEvent.change(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-turn`), { target: { value: "9" } });
    let latest = getLatest();
    expect(latest).not.toBeNull();
    expect(eventsOf(latest!).runtime_trigger).toEqual({ kind: "turn", turn: 9, once: true });
    expect(eventsOf(latest!).time).toBe("第7天");
    expect(eventsOf(latest!).event).toBe("中药房失火。");

    fireEvent.click(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-once`));
    latest = getLatest();
    expect(eventsOf(latest!).runtime_trigger).toEqual({ kind: "turn", turn: 9, once: false });
  });

  it("once 缺省时按开启呈现，编辑 turn 不补写 once 键", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(eventSystemFixture({ kind: "turn", turn: 3 }))));
    render(<Harness />);

    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-badge`)).toHaveTextContent("第 3 回合触发");
    const once = screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-once`) as HTMLInputElement;
    expect(once.checked).toBe(true);

    fireEvent.change(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-turn`), { target: { value: "5" } });
    const latest = getLatest();
    const trigger = eventsOf(latest!).runtime_trigger as Record<string, unknown>;
    expect(trigger).toEqual({ kind: "turn", turn: 5 });
    expect("once" in trigger).toBe(false);
  });

  it("kind=time 显示「存而不运行」，无 turn/once 编辑入口，且绝不被改写成 turn", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(eventSystemFixture({ kind: "time", at: "07:00" }))));
    render(<Harness />);

    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-badge`)).toHaveTextContent("存而不运行");
    expect(screen.queryByTestId(`mufy-trigger-${EVENTS_PATH}-turn`)).not.toBeInTheDocument();
    expect(screen.queryByTestId(`mufy-trigger-${EVENTS_PATH}-once`)).not.toBeInTheDocument();
    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-raw`).textContent).toContain("07:00");

    // 同一条目的其他字段可编辑，runtime_trigger 保持原样
    fireEvent.change(screen.getByTestId(`mufy-value-${EVENTS_PATH}.event`), {
      target: { value: "中药房失火，他冲了进去。" },
    });
    const latest = getLatest();
    expect(eventsOf(latest!).runtime_trigger).toEqual({ kind: "time", at: "07:00" });
    expect(eventsOf(latest!).event).toBe("中药房失火，他冲了进去。");
  });

  it("runtime_trigger 为非对象值时同样存而不运行", () => {
    const { Harness } = makeHarness(deepFreeze(clone(eventSystemFixture("每天早晨"))));
    render(<Harness />);

    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-badge`)).toHaveTextContent("存而不运行");
    expect(screen.queryByTestId(`mufy-trigger-${EVENTS_PATH}-turn`)).not.toBeInTheDocument();
    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-raw`).textContent).toContain("每天早晨");
  });

  it("散文触发字段（condition/trigger_after 等自由文本）原样编辑，代码不做解析", () => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(RICH_HSR)));
    render(<Harness />);

    fireEvent.change(screen.getByTestId("mufy-value-event_system.timeline_events.relative_timeline.events.0.trigger_after"), {
      target: { value: "7天以后" },
    });
    fireEvent.change(screen.getByTestId("mufy-value-event_system.conditional_triggers.relationship_triggers.0.condition"), {
      target: { value: "user第一次在他面前哭" },
    });

    const latest = getLatest();
    expect(latest).not.toBeNull();
    const expected = clone(RICH_HSR);
    const timeline = (expected.event_system as Record<string, unknown>).timeline_events as Record<string, unknown>;
    ((timeline.relative_timeline as Record<string, unknown>).events as Record<string, unknown>[])[0].trigger_after =
      "7天以后";
    const triggers = (expected.event_system as Record<string, unknown>).conditional_triggers as Record<string, unknown>;
    (triggers.relationship_triggers as Record<string, unknown>[])[0].condition = "user第一次在他面前哭";
    // runtime_trigger 条目与未知散文键都未被触碰
    expect(latest!.event_system).toEqual(expected.event_system);
  });

  it("trigger 呈现仅限 event_system 子树，其他块中的 runtime_trigger 按普通嵌套对象处理", () => {
    const { Harness } = makeHarness(
      deepFreeze(
        clone({
          relationship_system: {
            with_user: { 关系定位: "合伙人", runtime_trigger: { kind: "turn", turn: 2 } },
          },
        }),
      ),
    );
    render(<Harness />);

    expect(screen.queryByTestId("mufy-trigger-relationship_system.with_user-badge")).not.toBeInTheDocument();
    expect(screen.getByTestId("mufy-row-relationship_system.with_user.runtime_trigger")).toBeInTheDocument();
  });
});
