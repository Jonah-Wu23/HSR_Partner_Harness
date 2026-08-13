import { cloneElement, isValidElement, useEffect, useRef, useState } from "react";
import { CheckIcon } from "../../assets/icons/icons";

export interface MenuItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
}

interface MenuProps {
  trigger: (props: { open: boolean }) => React.ReactNode;
  items: MenuItem[];
  onSelect: (id: string) => void;
  ariaLabel: string;
  align?: "left" | "right";
  selectedId?: string;
  dropUp?: boolean;
}

/** 轻量上下文菜单：click-outside / Esc 关闭，方向键导航，Enter 激活。 */
export function Menu({ trigger, items, onSelect, ariaLabel, align = "right", selectedId, dropUp = false }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setActiveIndex(0);
      requestAnimationFrame(() => itemRefs.current[0]?.focus());
    }
  }, [open]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      setOpen(false);
      rootRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = (activeIndex + 1) % items.length;
      setActiveIndex(next);
      itemRefs.current[next]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const next = (activeIndex - 1 + items.length) % items.length;
      setActiveIndex(next);
      itemRefs.current[next]?.focus();
    } else if (event.key === "Enter") {
      // 激活当前聚焦项（禁用项不激活）；与点击行为一致。
      // 仅响应菜单项内的 Enter——焦点在触发器时按钮自身回车开合，
      // 不得冒泡到这里误激活首项。
      const target = event.target as HTMLElement;
      if (!target.closest('[role="menuitem"]')) return;
      const item = items[activeIndex];
      if (item && !item.disabled) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        onSelect(item.id);
      }
    }
  };

  const rendered = trigger({ open });
  const enhanced = isValidElement(rendered)
    ? cloneElement(rendered as React.ReactElement<Record<string, unknown>>, {
        onClick: (event: React.MouseEvent) => {
          (rendered.props as { onClick?: (e: React.MouseEvent) => void }).onClick?.(event);
          setOpen((value) => !value);
        },
        "aria-haspopup": "menu",
        "aria-expanded": open,
      })
    : rendered;

  return (
    <div ref={rootRef} className="menu-root" onKeyDown={onKeyDown}>
      {enhanced}
      {open ? (
        <div
          role="menu"
          aria-label={ariaLabel}
          className={`menu-popup${align === "left" ? " menu-popup-left" : ""}${dropUp ? " menu-popup-up" : ""}`}
        >
          {items.map((item, index) => (
            <button
              key={item.id}
              ref={(node) => {
                itemRefs.current[index] = node;
              }}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              className={`menu-item${item.danger ? " menu-item-danger" : ""}${item.id === selectedId ? " is-selected" : ""}`}
              onClick={() => {
                setOpen(false);
                onSelect(item.id);
              }}
            >
              {item.icon}
              <span>{item.label}</span>
              {item.id === selectedId ? <CheckIcon className="menu-item-check" /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
