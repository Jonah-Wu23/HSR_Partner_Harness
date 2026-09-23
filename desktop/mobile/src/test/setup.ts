import "@testing-library/jest-dom/vitest";

const layoutTestWindow = window as typeof window & { __conversationListLayoutMock?: boolean };
if (!layoutTestWindow.__conversationListLayoutMock) {
  layoutTestWindow.__conversationListLayoutMock = true;
  const getBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function () {
    const rect = getBoundingClientRect.call(this);
    if (this.classList.contains("mobile-chat-scroll")) {
      return new DOMRect(rect.x, rect.y, 390, 640);
    }
    if (this.classList.contains("mobile-virtual-row")) {
      return new DOMRect(rect.x, rect.y, 366, 80);
    }
    return rect;
  };
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get() {
      if (this.classList.contains("mobile-chat-scroll")) return 390;
      if (this.classList.contains("mobile-virtual-row")) return 366;
      return 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      if (this.classList.contains("mobile-chat-scroll")) return 640;
      if (this.classList.contains("mobile-virtual-row")) return 80;
      return 0;
    },
  });
}
