import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  WsAddressInput,
  validateWsAddress,
} from "../WsAddressInput";

afterEach(() => {
  cleanup();
});

describe("validateWsAddress 格式校验", () => {
  it("接受 ws:// 与 wss:// 完整地址", () => {
    expect(validateWsAddress("ws://192.168.1.50:8765/ws")).toEqual({
      valid: true,
      error: null,
    });
    expect(validateWsAddress("wss://pc.example.com/ws")).toEqual({
      valid: true,
      error: null,
    });
    expect(validateWsAddress("  ws://192.168.1.50:8765/ws  ")).toEqual({
      valid: true,
      error: null,
    });
  });

  it("空输入 valid=false 且不算错误文案", () => {
    expect(validateWsAddress("")).toEqual({ valid: false, error: null });
    expect(validateWsAddress("   ")).toEqual({ valid: false, error: null });
  });

  it("非 ws/wss 协议给出协议错误提示", () => {
    const result = validateWsAddress("http://192.168.1.50:8765/ws");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("ws://");
  });

  it("缺协议的裸地址按协议错误提示", () => {
    // "192.168.1.50:8765/ws" 会被 URL 解析为 scheme "192.168.1.50"，仍属协议错误
    const result = validateWsAddress("192.168.1.50:8765/ws");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("ws://");
  });

  it("任意字符串按地址不完整提示", () => {
    const result = validateWsAddress("随便写的一句话");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("完整地址");
  });

  it("缺少 /ws 路径时给出路径提示", () => {
    for (const bad of ["ws://192.168.1.50:8765", "ws://192.168.1.50:8765/hello"]) {
      const result = validateWsAddress(bad);
      expect(result.valid).toBe(false);
      expect(result.error).toContain("/ws");
    }
  });
});

describe("WsAddressInput 组件", () => {
  it("受控值与 onChange 事件", () => {
    const handleChange = vi.fn();
    const { rerender } = render(
      <WsAddressInput value="" onChange={handleChange} />,
    );

    const input = screen.getByTestId("ws-address-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ws://192.168.1.50:8765/ws" } });
    expect(handleChange).toHaveBeenCalledWith("ws://192.168.1.50:8765/ws");

    rerender(<WsAddressInput value="ws://192.168.1.50:8765/ws" onChange={handleChange} />);
    expect(input.value).toBe("ws://192.168.1.50:8765/ws");
  });

  it("初始状态合法时回传 valid=true 且显示提示而非错误", () => {
    const onValidityChange = vi.fn();
    render(
      <WsAddressInput
        value="ws://192.168.1.50:8765/ws"
        onChange={() => {}}
        onValidityChange={onValidityChange}
      />,
    );
    expect(onValidityChange).toHaveBeenCalledWith(true);
    expect(screen.queryByTestId("ws-address-error")).toBeNull();
    expect(screen.getByTestId("ws-address-hint")).toBeInTheDocument();
  });

  it("未失焦时不打扰输入过程，失焦后展示具体错误", () => {
    const onValidityChange = vi.fn();
    render(
      <WsAddressInput
        value="http://192.168.1.50:8765/ws"
        onChange={() => {}}
        onValidityChange={onValidityChange}
      />,
    );
    const input = screen.getByTestId("ws-address-input");
    expect(screen.queryByTestId("ws-address-error")).toBeNull();

    fireEvent.blur(input);
    const error = screen.getByTestId("ws-address-error");
    expect(error).toHaveTextContent("ws://");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("修正为合法地址后错误消失并回传 valid=true", () => {
    const onValidityChange = vi.fn();
    const { rerender } = render(
      <WsAddressInput
        value="ws://192.168.1.50:8765"
        onChange={() => {}}
        onValidityChange={onValidityChange}
      />,
    );
    const input = screen.getByTestId("ws-address-input");
    fireEvent.blur(input);
    expect(screen.getByTestId("ws-address-error")).toBeInTheDocument();

    rerender(
      <WsAddressInput
        value="ws://192.168.1.50:8765/ws"
        onChange={() => {}}
        onValidityChange={onValidityChange}
      />,
    );
    expect(screen.queryByTestId("ws-address-error")).toBeNull();
    expect(screen.getByTestId("ws-address-hint")).toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-invalid");
    // 回调序列：初始 false → 修正后 true，合法值内连续变化不重复回传
    expect(onValidityChange.mock.calls.map((call) => call[0])).toEqual([false, true]);
  });

  it("清空输入后错误消失但仍回传 valid=false", () => {
    const onValidityChange = vi.fn();
    const { rerender } = render(
      <WsAddressInput
        value="http://192.168.1.50:8765/ws"
        onChange={() => {}}
        onValidityChange={onValidityChange}
      />,
    );
    fireEvent.blur(screen.getByTestId("ws-address-input"));
    expect(screen.getByTestId("ws-address-error")).toBeInTheDocument();

    rerender(
      <WsAddressInput value="" onChange={() => {}} onValidityChange={onValidityChange} />,
    );
    expect(screen.queryByTestId("ws-address-error")).toBeNull();
    expect(onValidityChange).toHaveBeenLastCalledWith(false);
  });

  it("移动端可用性：URL 键盘与关闭自动纠错", () => {
    render(<WsAddressInput value="" onChange={() => {}} />);
    const input = screen.getByTestId("ws-address-input");
    expect(input).toHaveAttribute("inputmode", "url");
    expect(input).toHaveAttribute("autocapitalize", "none");
    expect(input).toHaveAttribute("spellcheck", "false");
  });
});
