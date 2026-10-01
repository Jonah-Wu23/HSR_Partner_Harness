import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WsAddressInput } from "../WsAddressInput";
import { parseWsAddress } from "../../lib/wsClient";

afterEach(() => {
  cleanup();
});

describe("parseWsAddress 输入校验", () => {
  it.each(["", "   "])("空输入 %j 不能保存，也不算错误", (raw) => {
    expect(parseWsAddress(raw)).toEqual({ ok: false, error: null });
  });

  it("去掉首尾空白后接受完整地址", () => {
    expect(parseWsAddress("  ws://192.168.1.50:8765/ws  ")).toEqual({
      ok: true,
      url: "ws://192.168.1.50:8765/ws",
    });
  });

  it.each([
    // 裸地址会被 URL 解析为 scheme「192.168.1.50」，同样按协议错误提示。
    { raw: "http://192.168.1.50:8765/ws", fragment: "ws://" },
    { raw: "192.168.1.50:8765/ws", fragment: "ws://" },
    { raw: "随便写的一句话", fragment: "完整地址" },
    { raw: "ws://192.168.1.50:8765", fragment: "/ws" },
    { raw: "ws://192.168.1.50:8765/hello", fragment: "/ws" },
  ])("拒绝 $raw 并在提示里说明 $fragment", ({ raw, fragment }) => {
    const result = parseWsAddress(raw);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error).toContain(fragment);
  });
});

describe("WsAddressInput 组件", () => {
  it("输入变化经 onChange 回传原始文本", () => {
    const handleChange = vi.fn();
    render(<WsAddressInput value="" onChange={handleChange} />);

    fireEvent.change(screen.getByTestId("ws-address-input"), {
      target: { value: "ws://192.168.1.50:8765/ws" },
    });

    expect(handleChange).toHaveBeenCalledWith("ws://192.168.1.50:8765/ws");
  });

  it("地址合法时显示说明而非错误", () => {
    render(<WsAddressInput value="ws://192.168.1.50:8765/ws" onChange={() => {}} />);
    expect(screen.queryByTestId("ws-address-error")).toBeNull();
    expect(screen.getByTestId("ws-address-hint")).toBeInTheDocument();
  });

  it("未失焦时不打扰输入过程，失焦后展示具体错误", () => {
    render(<WsAddressInput value="http://192.168.1.50:8765/ws" onChange={() => {}} />);
    const input = screen.getByTestId("ws-address-input");
    expect(screen.queryByTestId("ws-address-error")).toBeNull();

    fireEvent.blur(input);
    const error = screen.getByTestId("ws-address-error");
    expect(error).toHaveTextContent("ws://");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it.each([
    { change: "修正为合法地址", next: "ws://192.168.1.50:8765/ws" },
    { change: "清空输入", next: "" },
  ])("$change后错误提示消失", ({ next }) => {
    const { rerender } = render(
      <WsAddressInput value="ws://192.168.1.50:8765" onChange={() => {}} />,
    );
    const input = screen.getByTestId("ws-address-input");
    fireEvent.blur(input);
    expect(screen.getByTestId("ws-address-error")).toBeInTheDocument();

    rerender(<WsAddressInput value={next} onChange={() => {}} />);
    expect(screen.queryByTestId("ws-address-error")).toBeNull();
    expect(screen.getByTestId("ws-address-hint")).toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-invalid");
  });
});
