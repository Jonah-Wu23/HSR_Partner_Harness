interface Size {
  width: number;
  height: number;
}

/**
 * jsdom 不做布局，ConversationList 的滚动容器与行尺寸恒为 0，虚拟器算不出可见行。
 * 按组件自己渲染的 data 属性识别元素（滚动容器带 data-following-latest，行带 data-timeline-key），
 * 给它们补上固定尺寸；其他元素保持 jsdom 原值。
 */
export function installConversationListLayout(viewport: Size, row: Size): void {
  const sizeOf = (element: HTMLElement): Size | null => {
    if (element.hasAttribute("data-following-latest")) return viewport;
    if (element.hasAttribute("data-timeline-key")) return row;
    return null;
  };
  const getBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function () {
    const rect = getBoundingClientRect.call(this);
    const size = sizeOf(this);
    return size ? new DOMRect(rect.x, rect.y, size.width, size.height) : rect;
  };
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get() {
      return sizeOf(this)?.width ?? 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      return sizeOf(this)?.height ?? 0;
    },
  });
}
