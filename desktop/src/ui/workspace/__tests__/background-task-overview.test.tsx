import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProjectViewModel } from "../../../contracts/view-models";
import { BackgroundTaskOverview } from "../../navigation/BackgroundTaskOverview";

function makeProject(
  id: string,
  name: string,
  convs: Array<{ id: string; title: string; isRunning: boolean }>,
  activeTaskCount = 0,
): ProjectViewModel {
  return {
    project_id: id,
    name,
    root_path: `C:/Projects/${id}`,
    approval_mode: "request_approval",
    reasoning_effort: "low",
    archived: false,
    created_at: null,
    last_opened_at: null,
    path_available: true,
    isCurrent: false,
    isBusy: activeTaskCount > 0,
    activeTaskCount,
    conversations: convs.map((c) => ({
      conversation_id: c.id,
      project_id: id,
      pair_id: "pair-1",
      title: c.title,
      last_mode: "chat",
      archived: false,
      created_at: "2026-09-09T00:00:00Z",
      updated_at: "2026-09-09T00:00:00Z",
      isCurrent: false,
      isRunning: c.isRunning,
      isTaskOrigin: c.isRunning,
    })),
  };
}

describe("V0.3.9 V01 BackgroundTaskOverview 跨聊天后台任务总览", () => {
  afterEach(cleanup);

  it("isOpen=false 时不渲染任何内容", () => {
    const { container } = render(
      <BackgroundTaskOverview
        projects={[]}
        actions={{} as any}
        isOpen={false}
        onClose={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("无任务运行时显示空状态提示", () => {
    const projects = [makeProject("p-1", "星穹项目", [{ id: "c-1", title: "聊天1", isRunning: false }])];
    render(
      <BackgroundTaskOverview
        projects={projects}
        actions={{} as any}
        isOpen={true}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("当前没有正在运行的后台任务")).toBeInTheDocument();
  });

  it("跨项目多任务运行时，汇总展示各任务并可一键跳转", () => {
    const selectProject = vi.fn();
    const openConversationTab = vi.fn();
    const onClose = vi.fn();

    const projects = [
      makeProject(
        "p-1",
        "星穹项目",
        [
          { id: "c-1", title: "长世界书校对", isRunning: true },
          { id: "c-2", title: "普通问答", isRunning: false },
        ],
        1,
      ),
      makeProject(
        "p-2",
        "日常项目",
        [{ id: "c-3", title: "甜点配方生成", isRunning: true }],
        1,
      ),
    ];

    render(
      <BackgroundTaskOverview
        projects={projects}
        actions={{ selectProject, openConversationTab } as any}
        isOpen={true}
        onClose={onClose}
      />,
    );

    expect(screen.getByText("跨聊天后台任务总览")).toBeInTheDocument();
    expect(screen.getByText("2 个运行中")).toBeInTheDocument();
    expect(screen.getByText("长世界书校对")).toBeInTheDocument();
    expect(screen.getByText("甜点配方生成")).toBeInTheDocument();

    const jumpButtons = screen.getAllByRole("button", { name: "前往该聊天" });
    expect(jumpButtons).toHaveLength(2);

    fireEvent.click(jumpButtons[0]);
    expect(selectProject).toHaveBeenCalledWith("p-1");
    expect(openConversationTab).toHaveBeenCalledWith("c-1");
    expect(onClose).toHaveBeenCalled();
  });
});
