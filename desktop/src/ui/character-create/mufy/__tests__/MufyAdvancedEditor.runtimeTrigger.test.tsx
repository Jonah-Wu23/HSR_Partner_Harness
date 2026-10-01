import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { clone, deepFreeze } from "../../__tests__/editorHelpers";
import { makeHarness } from "./helpers";

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

describe("MufyAdvancedEditor runtime_trigger", () => {
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

  it.each([
    { label: "kind=time", trigger: { kind: "time", at: "07:00" }, rawText: "07:00" },
    { label: "非对象值", trigger: "每天早晨", rawText: "每天早晨" },
  ])("$label 的 runtime_trigger 显示「存而不运行」，无 turn/once 编辑入口，编辑同条目其他字段时原样保留", ({ trigger, rawText }) => {
    const { Harness, getLatest } = makeHarness(deepFreeze(clone(eventSystemFixture(trigger))));
    render(<Harness />);

    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-badge`)).toHaveTextContent("存而不运行");
    expect(screen.queryByTestId(`mufy-trigger-${EVENTS_PATH}-turn`)).not.toBeInTheDocument();
    expect(screen.queryByTestId(`mufy-trigger-${EVENTS_PATH}-once`)).not.toBeInTheDocument();
    expect(screen.getByTestId(`mufy-trigger-${EVENTS_PATH}-raw`).textContent).toContain(rawText);

    fireEvent.change(screen.getByTestId(`mufy-value-${EVENTS_PATH}.event`), {
      target: { value: "中药房失火，他冲了进去。" },
    });
    const latest = getLatest();
    expect(eventsOf(latest!).runtime_trigger).toEqual(trigger);
    expect(eventsOf(latest!).event).toBe("中药房失火，他冲了进去。");
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
