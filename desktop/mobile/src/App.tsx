import { useEffect } from "react";
import { getStoredToken } from "./lib/wsClient";
import { navigate, useRoute } from "./lib/router";
import { useMobileStore } from "./lib/mobileStore";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { PairPage } from "./pages/pair/PairPage";
import { ChatListPage } from "./pages/chats/ChatListPage";
import { ChatPage } from "./pages/chat/ChatPage";

export function App() {
  const route = useRoute();
  const connection = useMobileStore((state) => state.connection);
  const start = useMobileStore((state) => state.start);
  const hasToken = getStoredToken() !== null;

  useEffect(() => {
    start();
  }, [start]);

  // 路由守卫：未配对一律落到配对页；已配对访问配对页则回列表。
  useEffect(() => {
    if (!hasToken && route.name !== "pair") navigate({ name: "pair" });
    if (hasToken && route.name === "pair") navigate({ name: "list" });
  }, [hasToken, route.name]);

  return (
    <div className="app-shell">
      <ConnectionBanner connection={connection} />
      {route.name === "pair" ? (
        <PairPage />
      ) : route.name === "chat" ? (
        <ChatPage conversationId={route.conversationId} />
      ) : (
        <ChatListPage />
      )}
    </div>
  );
}
