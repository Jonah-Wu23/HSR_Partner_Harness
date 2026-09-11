import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopCommand, DesktopEvent, TurnMetric } from "../../../contracts/protocol";
import { createMockScenario } from "../../../mocks/scenarios";
import type { DesktopBackend } from "../../../services/backend";
import { createActionController } from "../../../services/actions";
import { desktopStore } from "../../../stores/desktopStore";
import { DiagnosticsDrawerHost } from "../DiagnosticsDrawerHost";

afterEach(cleanup);

function metricRecord(metricId: string): TurnMetric {
  return {
    metric_id: metricId,
    account_id: "acc-1",
    project_id: "project-1",
    conversation_id: "conv-1",
    pair_id: "phainon_ancient_machine",
    character_ref: "builtin:phainon",
    assistant_identity: "character",
    turn_kind: "character_turn",
    turn_id: `turn-${metricId}`,
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
}

/** 只实现 request 的假后端：按命令与 cursor 返回真实形状的应答。 */
function fakeBackend(
  respond: (command: DesktopCommand) => unknown,
): { backend: DesktopBackend } {
  const backend = {
    async request<T>(command: DesktopCommand): Promise<T> {
      return respond(command) as T;
    },
    openChatWindow: vi.fn(),
    pickFolder: vi.fn(),
    pickFile: vi.fn(),
    saveFile: vi.fn(),
    subscribe: (_listener: (event: DesktopEvent) => void) => () => {},
    reconnectSidecar: vi.fn(),
  } as unknown as DesktopBackend;
  return { backend };
}

describe("DiagnosticsDrawerHost 指标分页（V0.3.9 V03）", () => {
  beforeEach(() => {
    desktopStore.setState({
      turnMetrics: [],
      metricsCursor: null,
      metricsLoading: false,
      metricsError: null,
      promptAssembly: null,
      promptAssemblyLoading: false,
      promptAssemblyError: null,
      promptAssemblyRevealed: false,
    });
    desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("加载更多追加第二页而同屏保留第一页，刷新仍整体替换", async () => {
    const pageOne = [metricRecord("m1"), metricRecord("m2")];
    const pageTwo = [metricRecord("m3"), metricRecord("m4")];
    const { backend } = fakeBackend((command) => {
      if (command.method === "metrics.query") {
        return command.params.cursor
          ? { metrics: pageTwo, next_cursor: null }
          : { metrics: pageOne, next_cursor: "c1" };
      }
      if (command.method === "diagnostics.prompt_assembly") {
        return { modules: [], diagnostics: [], generated_at: "2026-01-01T00:00:00Z" };
      }
      return {};
    });
    const { actions } = createActionController(backend);

    render(<DiagnosticsDrawerHost open onClose={() => {}} actions={actions} />);

    // 首屏：2 条 + 下一页游标。
    await waitFor(() =>
      expect(screen.getByTestId("diag-metrics-count")).toHaveTextContent("共 2 条指标记录。"),
    );
    expect(screen.getByTestId("diag-metric-m1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /加载更多/ }));

    // 加载更多：第二页追加，第一页不得消失。
    await waitFor(() =>
      expect(screen.getByTestId("diag-metrics-count")).toHaveTextContent("共 4 条指标记录。"),
    );
    for (const id of ["m1", "m2", "m3", "m4"]) {
      expect(screen.getByTestId(`diag-metric-${id}`)).toBeInTheDocument();
    }

    // 刷新（无 cursor）仍是整体替换：回到第一页，第二页行消失。
    fireEvent.click(screen.getByRole("button", { name: "刷新指标" }));
    await waitFor(() =>
      expect(screen.getByTestId("diag-metrics-count")).toHaveTextContent("共 2 条指标记录。"),
    );
    expect(screen.queryByTestId("diag-metric-m3")).not.toBeInTheDocument();
  });
});
