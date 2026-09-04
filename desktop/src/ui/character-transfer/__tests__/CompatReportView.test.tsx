import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { CompatReportPayload } from "../../../contracts/protocol";
import { CompatReportView } from "../CompatReportView";

function sampleReport(overrides: Partial<CompatReportPayload> = {}): CompatReportPayload {
  return {
    applied: ["data.name", "data.description"],
    preserved: ["data.extensions.talkativeness"],
    not_executed: [
      "character_book.entries[2].probability（存而不运行）",
      "macro:{{setvar::x::1}} @ data.personality（未展开，2 处）",
      "hsr.event_system.events[0].runtime_trigger.kind=time（存而不运行）",
      "data.extensions.hsr.command_panels",
    ],
    normalized_from_root: ["spec_version"],
    warnings: ["世界书条目 3 的正则关键字非法，已退化为字面匹配"],
    errors: [],
    ...overrides,
  };
}

describe("CompatReportView（冻结 §11 六字段分组）", () => {
  afterEach(() => {
    cleanup();
  });

  it("非空字段按组呈现，空字段不渲染占位组", () => {
    render(<CompatReportView report={sampleReport()} />);

    expect(screen.getByText("已应用")).toBeInTheDocument();
    expect(screen.getByText("已保留（原样存储）")).toBeInTheDocument();
    expect(screen.getByText("未执行（存而不运行）")).toBeInTheDocument();
    expect(screen.getByText("根级字段回退（已归一化）")).toBeInTheDocument();
    expect(screen.getByText("警告")).toBeInTheDocument();
    // errors 为空 → 不渲染错误组
    expect(screen.queryByText("错误")).not.toBeInTheDocument();
    expect(screen.getByText("data.name")).toBeInTheDocument();
    expect(screen.getByText("spec_version")).toBeInTheDocument();
  });

  it("not_executed 内部按冻结 §11 类别再分组并展示计数", () => {
    render(<CompatReportView report={sampleReport()} />);

    expect(screen.getByText("世界书存而不运行字段（1）")).toBeInTheDocument();
    expect(screen.getByText("未展开宏（1）")).toBeInTheDocument();
    expect(screen.getByText("非 turn 触发（存而不运行）（1）")).toBeInTheDocument();
    expect(screen.getByText("其他保留项（1）")).toBeInTheDocument();
    expect(
      screen.getByText("macro:{{setvar::x::1}} @ data.personality（未展开，2 处）"),
    ).toBeInTheDocument();
  });

  it("错误组以危险色标签呈现", () => {
    render(<CompatReportView report={sampleReport({ errors: ["spec_version 缺失"] })} />);

    expect(screen.getByText("错误")).toBeInTheDocument();
    expect(screen.getByText("spec_version 缺失")).toBeInTheDocument();
  });

  it("全部字段为空时呈现「无兼容报告项」", () => {
    render(
      <CompatReportView
        report={{
          applied: [],
          preserved: [],
          not_executed: [],
          normalized_from_root: [],
          warnings: [],
          errors: [],
        }}
      />,
    );

    expect(screen.getByText("无兼容报告项")).toBeInTheDocument();
    expect(screen.queryByText("已应用")).not.toBeInTheDocument();
  });

  it("可选标题渲染在报告体之前", () => {
    render(<CompatReportView report={sampleReport()} title="兼容报告" />);

    expect(screen.getByText("兼容报告")).toBeInTheDocument();
  });

  it("compact 变体挂载紧凑类，默认不挂载", () => {
    const compact = render(<CompatReportView report={sampleReport()} compact />);
    expect(compact.container.firstElementChild?.className).toContain("xfer-compat-report-compact");
    compact.unmount();

    const plain = render(<CompatReportView report={sampleReport()} />);
    expect(plain.container.firstElementChild?.className).not.toContain("xfer-compat-report-compact");
  });
});
