import { useEffect, useRef, useState } from "react";
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
    }
  };

  return (
    <div ref={rootRef} className="menu-root" onKeyDown={onKeyDown}>
      <span onClick={() => setOpen((value) => !value)}>{trigger({ open })}</span>
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
