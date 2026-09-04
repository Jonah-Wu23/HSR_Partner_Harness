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
// 当前历史条目是否由应用内 navigate 压栈产生：
// 决定返回时走 history.back（回退既有条目）还是 replace（不新增历史）。
let pushedByApp = false;

function emitChange(): void {
  listeners.forEach((listener) => listener());
}

export function navigate(route: MobileRoute): void {
  const hash = routeToHash(route);
  if (typeof window !== "undefined" && window.location.hash !== hash) {
    // hash 赋值触发 hashchange，由监听器统一更新 currentRoute。
    pushedByApp = true;
    window.location.hash = hash;
    return;
  }
  currentRoute = route;
  emitChange();
}

/**
 * 返回式导航：当前条目由应用内压栈产生时走 history.back，回退到既有条目，
 * 不再压新历史（修复「列表 → 聊天 → 列表」每次进出都累积一条记录，
 * 导致 WebView 返回键要在假栈里反复后退的问题）。
 * 没有应用内历史时（如刷新/深链直接落在聊天页）以 replace 语义替换为 fallback，
 * 同样不新增条目；此时 WebView 返回键按原生语义退出。
 */
export function navigateBack(fallback: MobileRoute): void {
  if (typeof window === "undefined") return;
  const canGoBack = pushedByApp && window.history.length > 1;
  pushedByApp = false;
  if (canGoBack) {
    // history.back 经 hashchange 由监听器统一更新 currentRoute。
    window.history.back();
    return;
  }
  const hash = routeToHash(fallback);
  if (window.location.hash !== hash) {
    window.history.replaceState(null, "", hash);
  }
  currentRoute = fallback;
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
