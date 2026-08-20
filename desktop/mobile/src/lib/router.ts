import { useSyncExternalStore } from "react";

/** V0.3.3 手机端 hash 路由：# list / # pair / # chat/:id。 */

export type MobileRoute =
  | { name: "list" }
  | { name: "pair" }
  | { name: "chat"; conversationId: string };

export function parseHash(hash: string): MobileRoute {
  const segments = hash.replace(/^#/, "").split("/").filter(Boolean);
  if (segments[0] === "pair") return { name: "pair" };
  if (segments[0] === "chat" && segments[1]) {
    return { name: "chat", conversationId: decodeURIComponent(segments[1]) };
  }
  return { name: "list" };
}

export function routeToHash(route: MobileRoute): string {
  switch (route.name) {
    case "pair":
      return "#/pair";
    case "chat":
      return `#/chat/${encodeURIComponent(route.conversationId)}`;
    default:
      return "#/list";
  }
}

let currentRoute: MobileRoute = parseHash(
  typeof window !== "undefined" ? window.location.hash : "",
);
const listeners = new Set<() => void>();

function emitChange(): void {
  listeners.forEach((listener) => listener());
}

export function navigate(route: MobileRoute): void {
  const hash = routeToHash(route);
  if (typeof window !== "undefined" && window.location.hash !== hash) {
    // hash 赋值触发 hashchange，由监听器统一更新 currentRoute。
    window.location.hash = hash;
    return;
  }
  currentRoute = route;
  emitChange();
}

if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => {
    currentRoute = parseHash(window.location.hash);
    emitChange();
  });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** getSnapshot 必须返回稳定引用，否则 useSyncExternalStore 会无限重渲染。 */
function getSnapshot(): MobileRoute {
  return currentRoute;
}

export function useRoute(): MobileRoute {
  return useSyncExternalStore(subscribe, getSnapshot);
}
