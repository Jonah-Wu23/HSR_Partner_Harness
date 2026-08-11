import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Menu } from "../primitives/Menu";

function renderMenu(onSelect = vi.fn()) {
  render(
    <div>
      <button type="button">外部按钮</button>
      <Menu
        ariaLabel="测试菜单"
        trigger={() => <button type="button">打开菜单</button>}
        items={[
          { id: "a", label: "选项甲" },
          { id: "b", label: "选项乙" },
          { id: "c", label: "选项丙", danger: true },
        ]}
        onSelect={onSelect}
      />
    </div>,
  );
  return onSelect;
}

describe("Menu 键盘与弹层行为", () => {
  afterEach(cleanup);

  it("点击触发器展开，再点击收起", async () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: "打开菜单" }));
    expect(await screen.findByRole("menu")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "打开菜单" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("展开后首项聚焦，箭头键循环导航，Enter 激活", async () => {
    const onSelect = renderMenu();
    fireEvent.click(screen.getByRole("button", { name: "打开菜单" }));
    const menu = await screen.findByRole("menu");

    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "选项甲" })),
    );

    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "选项乙" }));

    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "选项甲" }));

    // 循环：从首项再向上到末项
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "选项丙" }));

    fireEvent.keyDown(document.activeElement as Element, { key: "Enter" });
    fireEvent.click(screen.getByRole("menuitem", { name: "选项丙" }));
    expect(onSelect).toHaveBeenCalledWith("c");
  });

  it("Esc 关闭弹层并把焦点还给触发器", async () => {
    renderMenu();
    const trigger = screen.getByRole("button", { name: "打开菜单" });
    fireEvent.click(trigger);
    const menu = await screen.findByRole("menu");

    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it("点击弹层外部关闭", async () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: "打开菜单" }));
    expect(await screen.findByRole("menu")).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "外部按钮" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("危险项带危险样式类，禁用项不可点击", async () => {
    const onSelect = vi.fn();
    render(
      <Menu
        ariaLabel="测试菜单"
        trigger={() => <button type="button">打开菜单</button>}
        items={[
          { id: "x", label: "危险操作", danger: true },
          { id: "y", label: "禁用操作", disabled: true },
        ]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "打开菜单" }));
    expect(await screen.findByRole("menu")).toBeInTheDocument();

    expect(screen.getByRole("menuitem", { name: "危险操作" })).toHaveClass("menu-item-danger");
    const disabledItem = screen.getByRole("menuitem", { name: "禁用操作" });
    expect(disabledItem).toBeDisabled();
    fireEvent.click(disabledItem);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
