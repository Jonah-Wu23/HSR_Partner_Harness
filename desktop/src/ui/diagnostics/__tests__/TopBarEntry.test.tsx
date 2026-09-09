import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HarnessActions } from "../../../contracts/actions";
import { TopBar } from "../../TopBar";
import { TechDetailsDrawer } from "../../status/TechDetailsDrawer";

afterEach(cleanup);

const mockActions = {} as unknown as HarnessActions;

describe("TopBar 与 TechDetailsDrawer 诊断入口（V0.3.9 V03）", () => {
  describe("TopBar", () => {
    it("未提供 onOpenDiagnostics 时不渲染诊断按钮（无动作不留入口）", () => {
      render(
        <TopBar
          mode="chat"
          pair={null}
          assistantBusy={false}
          connectionStatus="connected"
          onOpenTechDetails={() => {}}
          onOpenSettings={() => {}}
          actions={mockActions}
        />,
      );

      expect(screen.queryByTestId("topbar-diagnostics")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "诊断" })).not.toBeInTheDocument();
    });

    it("提供 onOpenDiagnostics 时渲染诊断按钮并响应点击", () => {
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
          actions={mockActions}
        />,
      );

      const btn = screen.getByTestId("topbar-diagnostics");
      expect(btn).toBeInTheDocument();
      expect(btn).toHaveTextContent("诊断");

      fireEvent.click(btn);
      expect(onOpenDiagnostics).toHaveBeenCalledTimes(1);
    });
  });

  describe("TechDetailsDrawer", () => {
    it("未提供 onOpenDiagnostics 时不渲染诊断按钮", () => {
      render(
        <TechDetailsDrawer
          open
          status="connected"
          details={{}}
          onClose={() => {}}
        />,
      );

      expect(screen.queryByTestId("tech-drawer-open-diagnostics")).not.toBeInTheDocument();
    });

    it("提供 onOpenDiagnostics 时渲染打开诊断按钮，点击时关闭抽屉并触发诊断", () => {
      const onClose = vi.fn();
      const onOpenDiagnostics = vi.fn();
      render(
        <TechDetailsDrawer
          open
          status="connected"
          details={{}}
          onClose={onClose}
          onOpenDiagnostics={onOpenDiagnostics}
        />,
      );

      const btn = screen.getByTestId("tech-drawer-open-diagnostics");
      expect(btn).toBeInTheDocument();
      expect(btn).toHaveTextContent("打开诊断（指标与装配）");

      fireEvent.click(btn);
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(onOpenDiagnostics).toHaveBeenCalledTimes(1);
    });
  });
});
