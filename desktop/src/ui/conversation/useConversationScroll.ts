import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type TouchEvent, type WheelEvent } from "react";

export interface ConversationAnchor {
  key: string;
  index: number;
  top: number;
}

type ScrollDirection = "up" | "down";

/** 将用户滚动与布局调整、自动跟随产生的位置写入分开处理。 */
export function useConversationScroll(initialState?: { following: boolean; anchor: ConversationAnchor | null }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const followingRef = useRef(initialState?.following ?? true);
  const [following, setFollowingState] = useState(followingRef.current);
  const anchorRef = useRef<ConversationAnchor | null>(initialState?.anchor ?? null);
  const programmaticTargetsRef = useRef<number[]>([]);
  const inputDirectionRef = useRef<ScrollDirection | null>(null);
  const pointerActiveRef = useRef(false);
  const touchActiveRef = useRef(false);
  const touchMomentumRef = useRef(false);
  const touchYRef = useRef<number | null>(null);
  const touchDirectionRef = useRef<ScrollDirection | null>(null);
  const inputTimerRef = useRef<number | null>(null);

  const setFollowing = useCallback((next: boolean) => {
    followingRef.current = next;
    setFollowingState((current) => current === next ? current : next);
  }, []);

  const captureAnchor = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const viewportTop = node.getBoundingClientRect().top;
    for (const row of node.querySelectorAll<HTMLElement>("[data-timeline-key]")) {
      const rect = row.getBoundingClientRect();
      if (rect.bottom > viewportTop) {
        anchorRef.current = {
          key: row.dataset.timelineKey ?? "",
          index: Number(row.dataset.index),
          top: rect.top - viewportTop,
        };
        return;
      }
    }
  }, []);

  const scrollToPosition = useCallback((top: number) => {
    const node = scrollRef.current;
    if (!node) return;
    const target = Math.max(0, Math.min(top, node.scrollHeight - node.clientHeight));
    if (Math.abs(node.scrollTop - target) <= 0.5) return;
    programmaticTargetsRef.current.push(target);
    if (programmaticTargetsRef.current.length > 8) programmaticTargetsRef.current.shift();
    node.scrollTop = target;
  }, []);

  const scrollToBottom = useCallback(() => {
    const node = scrollRef.current;
    if (node) scrollToPosition(node.scrollHeight);
  }, [scrollToPosition]);

  const restoreAnchor = useCallback(() => {
    const node = scrollRef.current;
    const anchor = anchorRef.current;
    if (!node || !anchor) return;
    const row = Array.from(node.querySelectorAll<HTMLElement>("[data-timeline-key]"))
      .find((candidate) => candidate.dataset.timelineKey === anchor.key);
    if (!row) return;
    const offset = row.getBoundingClientRect().top - node.getBoundingClientRect().top;
    if (Math.abs(offset - anchor.top) > 0.5) scrollToPosition(node.scrollTop + offset - anchor.top);
    captureAnchor();
  }, [captureAnchor, scrollToPosition]);

  const reconcileLayout = useCallback(() => {
    if (followingRef.current) scrollToBottom();
    else restoreAnchor();
  }, [restoreAnchor, scrollToBottom]);

  const clearInputTimer = useCallback(() => {
    if (inputTimerRef.current !== null) window.clearTimeout(inputTimerRef.current);
    inputTimerRef.current = null;
  }, []);

  const markInput = useCallback((direction: ScrollDirection) => {
    inputDirectionRef.current = direction;
    clearInputTimer();
    inputTimerRef.current = window.setTimeout(() => {
      inputDirectionRef.current = null;
      touchMomentumRef.current = false;
    }, 250);
  }, [clearInputTimer]);

  const onScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const currentTop = node.scrollTop;
    const targets = programmaticTargetsRef.current;
    const targetIndex = targets.findIndex((target) => Math.abs(target - currentTop) <= 1);
    if (targetIndex >= 0) {
      targets.splice(0, targetIndex + 1);
      return;
    }
    const direction = inputDirectionRef.current;
    const activeDrag = pointerActiveRef.current || touchActiveRef.current || touchMomentumRef.current;
    if (!direction && !activeDrag) return;
    const distance = node.scrollHeight - node.clientHeight - currentTop;
    if (distance <= 2) {
      if (direction === "down" || activeDrag) setFollowing(true);
    } else if (direction === "up" || activeDrag) {
      setFollowing(false);
    }
    if (distance > 2 && !followingRef.current) captureAnchor();
    if (touchMomentumRef.current && touchDirectionRef.current) markInput(touchDirectionRef.current);
  }, [captureAnchor, markInput, setFollowing]);

  const onWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    const innerScroller = (event.target as HTMLElement).closest<HTMLElement>("[data-internal-scroll]");
    if (innerScroller && innerScroller.scrollHeight > innerScroller.clientHeight) {
      const atTop = innerScroller.scrollTop <= 0 && event.deltaY < 0;
      const atBottom = innerScroller.scrollTop + innerScroller.clientHeight >= innerScroller.scrollHeight - 1 && event.deltaY > 0;
      if (!atTop && !atBottom) return;
    }
    if (event.deltaY === 0) return;
    const direction = event.deltaY > 0 ? "down" : "up";
    markInput(direction);
    const node = scrollRef.current;
    if (!innerScroller && direction === "up" && node && node.scrollHeight - node.clientHeight > 2) {
      setFollowing(false);
      captureAnchor();
    }
    if (!innerScroller && direction === "down" && node && node.scrollHeight - node.clientHeight - node.scrollTop <= 2) {
      setFollowing(true);
    }
  }, [captureAnchor, markInput, setFollowing]);

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) pointerActiveRef.current = true;
  }, []);

  const onTouchStart = useCallback((event: TouchEvent<HTMLDivElement>) => {
    const innerScroller = (event.target as HTMLElement).closest<HTMLElement>("[data-internal-scroll]");
    if (innerScroller && innerScroller.scrollHeight > innerScroller.clientHeight) return;
    touchActiveRef.current = true;
    touchMomentumRef.current = false;
    touchYRef.current = event.touches[0]?.clientY ?? null;
    touchDirectionRef.current = null;
  }, []);

  const onTouchMove = useCallback((event: TouchEvent<HTMLDivElement>) => {
    if (!touchActiveRef.current) return;
    const nextY = event.touches[0]?.clientY;
    const previousY = touchYRef.current;
    if (nextY !== undefined && previousY !== null && nextY !== previousY) {
      touchDirectionRef.current = nextY < previousY ? "down" : "up";
      markInput(touchDirectionRef.current);
      const node = scrollRef.current;
      if (touchDirectionRef.current === "up" && node && node.scrollHeight - node.clientHeight > 2) {
        setFollowing(false);
        captureAnchor();
      }
    }
    touchYRef.current = nextY ?? null;
  }, [captureAnchor, markInput, setFollowing]);

  const onTouchEnd = useCallback(() => {
    touchMomentumRef.current = touchActiveRef.current && touchDirectionRef.current !== null;
    touchActiveRef.current = false;
    touchYRef.current = null;
    if (touchMomentumRef.current && touchDirectionRef.current) markInput(touchDirectionRef.current);
  }, [markInput]);

  const onTouchCancel = useCallback(() => {
    touchActiveRef.current = false;
    touchMomentumRef.current = false;
    touchYRef.current = null;
    touchDirectionRef.current = null;
    inputDirectionRef.current = null;
    clearInputTimer();
  }, [clearInputTimer]);

  const onKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const direction: ScrollDirection | null = event.key === "ArrowUp" || event.key === "PageUp" || event.key === "Home" || (event.key === " " && event.shiftKey)
      ? "up"
      : event.key === "ArrowDown" || event.key === "PageDown" || event.key === "End" || event.key === " "
        ? "down"
        : null;
    if (!direction) return;
    markInput(direction);
    const node = scrollRef.current;
    if (direction === "up" && node && node.scrollHeight - node.clientHeight > 2) {
      setFollowing(false);
      captureAnchor();
    }
    if (direction === "down" && node && node.scrollHeight - node.clientHeight - node.scrollTop <= 2) {
      setFollowing(true);
    }
  }, [captureAnchor, markInput, setFollowing]);

  const jumpToLatest = useCallback(() => {
    setFollowing(true);
    scrollToBottom();
  }, [scrollToBottom, setFollowing]);

  useEffect(() => {
    const endPointer = () => { pointerActiveRef.current = false; };
    window.addEventListener("pointerup", endPointer);
    window.addEventListener("pointercancel", endPointer);
    return () => {
      window.removeEventListener("pointerup", endPointer);
      window.removeEventListener("pointercancel", endPointer);
      clearInputTimer();
    };
  }, [clearInputTimer]);

  return {
    scrollRef,
    following,
    followingRef,
    anchorRef,
    reconcileLayout,
    jumpToLatest,
    onScroll,
    onWheel,
    onPointerDown,
    onTouchStart,
    onTouchMove,
    onTouchEnd,
    onTouchCancel,
    onKeyDown,
  };
}
