import "@testing-library/jest-dom/vitest";
import { installConversationListLayout } from "./conversationListLayout";

installConversationListLayout({ width: 800, height: 600 }, { width: 760, height: 80 });
