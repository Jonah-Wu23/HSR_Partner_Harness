import { useEffect } from "react";
import { getStoredToken } from "./lib/wsClient";
import { navigate, useRoute } from "./lib/router";
import { useMobileStore } from "./lib/mobileStore";
import { startNotificationEngine } from "./lib/notificationEngine";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { PairPage } from "./pages/pair/PairPage";
import { ChatListPage } from "./pages/chats/ChatListPage";
import { ChatPage } from "./pages/chat/ChatPage";

export function App() {
  const route = useRoute();
  const connection = useMobileStore((state) => state.connection);
  const start = useMobileStore((state) => state.start);
  // deviceName 与 localStorage token 同写同清（pair/disconnect），用它驱动
  // 守卫重渲染；直接 render 期读 localStorage 不会在配对成功后刷新。
  const deviceName = useMobileStore((state) => state.deviceName);
  const hasToken = deviceName !== null && getStoredToken() !== null;

  useEffect(() => {
    start();
  }, [start]);

  // L13 本地通知引擎：Android 壳内启动（内部幂等，非壳环境直接空操作）。
  useEffect(() => startNotificationEngine(), []);

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
