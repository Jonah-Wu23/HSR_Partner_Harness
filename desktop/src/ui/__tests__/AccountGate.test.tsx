import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountGate } from "../gate/AccountGate";
import type { AccountListItem } from "../gate/types";
import { desktopStore } from "../../stores/desktopStore";

afterEach(cleanup);

const accounts: AccountListItem[] = [
  { accountId: "default-local", displayName: "默认账号", avatarUrl: null, isLastLogin: true },
  { accountId: "demo-account", displayName: "演示账号", avatarUrl: null, isLastLogin: false },
];

function renderGate(overrides: {
  error?: string | null;
  busy?: boolean;
  onLogin?: (accountId: string, password: string) => void;
  onRegister?: (displayName: string, password: string) => void;
  onClearError?: () => void;
} = {}) {
  const onLogin = overrides.onLogin ?? vi.fn();
  const onRegister = overrides.onRegister ?? vi.fn();
  render(
    <AccountGate
      accounts={accounts}
      error={overrides.error ?? null}
      busy={overrides.busy ?? false}
      onLogin={onLogin}
      onRegister={onRegister}
      onClearError={overrides.onClearError}
    />,
  );
  return { onLogin, onRegister };
}

describe("AccountGate（V039-S4-005 / V039-S4-006）", () => {
  it("V039-S4-005：空密码不再禁用「进入」，输入原样交给后端判定", () => {
    const { onLogin } = renderGate();

    // 默认账号（种子时 password_hash 为空）只能以空密码登录，前端不得拦下这次提交
    const submit = screen.getByRole("button", { name: "进入" });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(onLogin).toHaveBeenCalledWith("default-local", "");
  });

  it("V039-S4-005：有密码的账号不绕过校验——组件只转发，不本地放行、不合成成功", () => {
    const { onLogin } = renderGate();

    fireEvent.click(screen.getByRole("radio", { name: /演示账号/ }));
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "demo-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));

    // 组件不做任何本地密码判定：后端拒绝时错误由父级就地回显（见 AppShell 用例）
    expect(onLogin).toHaveBeenCalledWith("demo-account", "demo-pass");
  });

  it("V039-S4-006：切到注册表单时请求清理上一轮登录错误", () => {
    const onClearError = vi.fn();
    renderGate({ error: "密码错误", onClearError });

    expect(screen.getByRole("alert")).toHaveTextContent("密码错误");
    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));

    expect(onClearError).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "注册新账号" })).toBeInTheDocument();
  });

  it("V039-S4-006：返回登录同样清理注册表单的错误", () => {
    const onClearError = vi.fn();
    renderGate({ error: "名字已被使用", onClearError });

    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));
    fireEvent.click(screen.getByRole("button", { name: "返回登录" }));

    expect(onClearError).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("heading", { name: "欢迎回来" })).toBeInTheDocument();
  });


  it("V039-S4-002：Sidecar 自报演示模式时账号门上也标注", () => {
    desktopStore.setState({ backendInfo: { pid: 1, demo: true, modeSource: "flag" } });
    try {
      renderGate();
      expect(screen.getByTestId("demo-mode-badge")).toHaveTextContent(
        "演示模式：未调用真实模型",
      );
    } finally {
      desktopStore.setState({ backendInfo: null });
    }
  });

  it("busy 期间不允许重复提交", () => {
    const { onLogin } = renderGate({ busy: true });
    expect(screen.getByRole("button", { name: "正在进入…" })).toBeDisabled();
    expect(onLogin).not.toHaveBeenCalled();
  });
});
