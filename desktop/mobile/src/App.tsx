import { useEffect } from "react";
import { getStoredToken } from "./lib/wsClient";
import { navigate, useRoute } from "./lib/router";
import { useMobileStore } from "./lib/mobileStore";
import { PairPage } from "./pages/pair/PairPage";
import { ChatListPage } from "./pages/chats/ChatListPage";
import { ChatPage } from "./pages/chat/ChatPage";

const CONNECTION_LABEL: Record<string, string> = {
  disconnected: "未连接",
  connecting: "连接中…",
  connected: "已连接",
  reconnecting: "连接中断，重连中…",
  unreachable: "无法到达桌面端，请确认 Sidecar 已以 --serve 运行",
  auth_failed: "配对已失效，请重新配对",
};

function ConnectionBanner(props: { connection: string }) {
  if (props.connection === "connected") return null;
  const tone =
    props.connection === "unreachable" || props.connection === "auth_failed"
      ? "is-down"
      : "is-warn";
  return (
    <div className={`conn-banner ${tone}`} role="status">
      {CONNECTION_LABEL[props.connection] ?? props.connection}
    </div>
  );
}

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
