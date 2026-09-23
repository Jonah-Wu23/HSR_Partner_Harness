import "@testing-library/jest-dom/vitest";

const layoutTestWindow = window as typeof window & { __conversationListLayoutMock?: boolean };
if (!layoutTestWindow.__conversationListLayoutMock) {
  layoutTestWindow.__conversationListLayoutMock = true;
  const getBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function () {
    const rect = getBoundingClientRect.call(this);
    if (this.classList.contains("message-scroll")) {
      return new DOMRect(rect.x, rect.y, 800, 600);
    }
    if (this.classList.contains("message-virtual-row")) {
      return new DOMRect(rect.x, rect.y, 760, 80);
    }
    return rect;
  };
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get() {
      if (this.classList.contains("message-scroll")) return 800;
      if (this.classList.contains("message-virtual-row")) return 760;
      return 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      if (this.classList.contains("message-scroll")) return 600;
      if (this.classList.contains("message-virtual-row")) return 80;
      return 0;
    },
  });
}
