import "@testing-library/jest-dom/vitest";
import { installConversationListLayout } from "@shared/test/conversationListLayout";

// jsdom 的 CSS 命名空间没有 supports；按不支持任何特性处理，组件走脚本测量路径。
if (typeof CSS.supports !== "function") {
  Object.defineProperty(CSS, "supports", { value: () => false, configurable: true });
}

installConversationListLayout({ width: 390, height: 640 }, { width: 366, height: 80 });
