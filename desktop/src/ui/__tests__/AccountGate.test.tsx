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

describe("AccountGate", () => {
  it("注册表单校验两次密码一致后才提交", () => {
    const { onRegister } = renderGate();

    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "新伙伴" } });
    fireEvent.change(screen.getByLabelText(/密码（至少 6 位）/), { target: { value: "abcdef" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "abcdeg" } });
    expect(screen.getByRole("alert")).toHaveTextContent("两次输入的密码不一致");
    expect(screen.getByRole("button", { name: "注册并进入" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "abcdef" } });
    fireEvent.click(screen.getByRole("button", { name: "注册并进入" }));
    expect(onRegister).toHaveBeenCalledWith("新伙伴", "abcdef");
  });

  it("登录与注册表单互切时都请求清理上一轮错误", () => {
    const onClearError = vi.fn();
    renderGate({ error: "密码错误", onClearError });

    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));
    expect(screen.getByRole("heading", { name: "注册新账号" })).toBeInTheDocument();
    expect(onClearError).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "返回登录" }));
    expect(screen.getByRole("heading", { name: "欢迎回来" })).toBeInTheDocument();
    expect(onClearError).toHaveBeenCalledTimes(2);
  });

  it("Sidecar 自报演示模式时账号门上也标注", () => {
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
    const submit = screen.getByRole("button", { name: "正在进入…" });
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(onLogin).not.toHaveBeenCalled();
  });
});
