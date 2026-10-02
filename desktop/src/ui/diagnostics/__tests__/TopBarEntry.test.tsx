import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { TopBar } from "../../TopBar";

afterEach(cleanup);

describe("顶栏诊断入口", () => {
  it("顶栏「诊断」按钮打开诊断抽屉", () => {
    const onOpenDiagnostics = vi.fn();
    render(
      <TopBar
        mode="chat"
        pair={null}
        assistantBusy={false}
        connectionStatus="connected"
        onOpenTechDetails={() => {}}
        onOpenDiagnostics={onOpenDiagnostics}
        onOpenSettings={() => {}}
        actions={createActionController(new MockDesktopBackend("single-project")).actions}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "诊断" }));
    expect(onOpenDiagnostics).toHaveBeenCalledTimes(1);
  });
});
