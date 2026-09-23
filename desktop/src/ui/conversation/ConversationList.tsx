import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";

export interface ConversationItemState {
  isExpanded: (key: string, defaultValue?: boolean) => boolean;
  setExpanded: (key: string, expanded: boolean) => void;
}

interface ConversationListProps<T> {
  conversationId: string;
  items: readonly T[];
  getItemKey: (item: T) => string;
  estimateSize: number;
  overscan?: number;
  scrollClassName: string;
  contentClassName: string;
  rowClassName: string;
  scrollTestId?: string;
  emptyContent?: ReactNode;
  tabIndex?: number;
  renderItem: (item: T, state: ConversationItemState) => ReactNode;
  renderJumpButton?: (jumpToLatest: () => void) => ReactNode;
}

interface Anchor {
  key: string;
  top: number;
}

/** Shared dynamic-height timeline for desktop and mobile chat. */
export function ConversationList<T>({
  conversationId,
  items,
  getItemKey,
  estimateSize,
  overscan = 6,
  scrollClassName,
  contentClassName,
  rowClassName,
  scrollTestId,
  emptyContent,
  tabIndex = 0,
  renderItem,
  renderJumpButton,
}: ConversationListProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  const [pinned, setPinned] = useState(true);
  const userScrollUntilRef = useRef(0);
  const anchorRef = useRef<Anchor | null>(null);
  const previousConversationRef = useRef(conversationId);
  const previousWidthRef = useRef(0);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});

  const itemKeys = useMemo(
    () => items.map((item) => `${conversationId}:${getItemKey(item)}`),
    [conversationId, getItemKey, items],
  );
  const itemKeysSignature = JSON.stringify(itemKeys);
  const itemKeysRef = useRef(itemKeys);
  itemKeysRef.current = itemKeys;
  const getVirtualizerItemKey = useCallback(
    (index: number) => itemKeysRef.current[index] ?? `${conversationId}:${index}`,
    [conversationId, itemKeysSignature],
  );

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    initialRect: { width: 1, height: estimateSize },
    overscan,
    getItemKey: getVirtualizerItemKey,
    rangeExtractor: (range) => items.length <= 40
      ? Array.from({ length: items.length }, (_, index) => index)
      : defaultRangeExtractor(range),
  });
  virtualizer.shouldAdjustScrollPositionOnItemSizeChange = () => false;
  const totalSize = virtualizer.getTotalSize();
  const virtualItems = virtualizer.getVirtualItems();

  const setFollowLatest = useCallback((next: boolean) => {
    pinnedRef.current = next;
    setPinned((current) => current === next ? current : next);
  }, []);

  const captureAnchor = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const viewportTop = node.getBoundingClientRect().top;
    const rows = node.querySelectorAll<HTMLElement>("[data-timeline-key]");
    for (const row of rows) {
      const rect = row.getBoundingClientRect();
      if (rect.bottom > viewportTop) {
        anchorRef.current = { key: row.dataset.timelineKey ?? "", top: rect.top - viewportTop };
        return;
      }
    }
  }, []);

  const updateViewport = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const next = { width: node.clientWidth, height: node.clientHeight };
    setViewport((current) =>
      current.width === next.width && current.height === next.height ? current : next,
    );
  }, []);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    updateViewport();
    const ResizeObserverClass = node.ownerDocument.defaultView?.ResizeObserver;
    if (!ResizeObserverClass) return;
    const observer = new ResizeObserverClass(updateViewport);
    observer.observe(node);
    return () => observer.disconnect();
  }, [updateViewport]);

  const measureVisibleRows = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.querySelectorAll<HTMLElement>("[data-index]").forEach((row) => {
      virtualizer.measureElement(row);
    });
  }, [virtualizer]);

  useLayoutEffect(() => {
    if (previousConversationRef.current !== conversationId) {
      previousConversationRef.current = conversationId;
      anchorRef.current = null;
      userScrollUntilRef.current = 0;
      setFollowLatest(true);
      virtualizer.measure();
      measureVisibleRows();
    }
    if (viewport.width > 0 && previousWidthRef.current > 0 && previousWidthRef.current !== viewport.width) {
      virtualizer.measure();
      measureVisibleRows();
    }
    if (viewport.width > 0) previousWidthRef.current = viewport.width;

    const node = scrollRef.current;
    if (!node || items.length === 0) return;
    if (pinnedRef.current) {
      node.scrollTop = node.scrollHeight;
      virtualizer.calculateRange();
    } else if (anchorRef.current) {
      const row = Array.from(node.querySelectorAll<HTMLElement>("[data-timeline-key]")).find(
        (candidate) => candidate.dataset.timelineKey === anchorRef.current?.key,
      );
      if (row) {
        const offset = row.getBoundingClientRect().top - node.getBoundingClientRect().top;
        if (Math.abs(offset - anchorRef.current.top) > 0.5) {
          node.scrollTop += offset - anchorRef.current.top;
        }
      }
      captureAnchor();
    }
  }, [
    captureAnchor,
    conversationId,
    items,
    measureVisibleRows,
    pinned,
    setFollowLatest,
    totalSize,
    viewport.height,
    viewport.width,
    virtualizer,
  ]);

  const markUserScroll = useCallback((duration = 500) => {
    userScrollUntilRef.current = Date.now() + duration;
  }, []);

  const onScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    captureAnchor();
    if (Date.now() > userScrollUntilRef.current) return;
    const distanceFromBottom = node.scrollHeight - node.clientHeight - node.scrollTop;
    setFollowLatest(distanceFromBottom <= 2);
  }, [captureAnchor, setFollowLatest]);

  const onWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    const innerScroller = (event.target as HTMLElement).closest<HTMLElement>("[data-internal-scroll]");
    if (innerScroller && innerScroller.scrollHeight > innerScroller.clientHeight) {
      const atTop = innerScroller.scrollTop <= 0 && event.deltaY < 0;
      const atBottom = innerScroller.scrollTop + innerScroller.clientHeight >= innerScroller.scrollHeight - 1 && event.deltaY > 0;
      if (!atTop && !atBottom) return;
    }
    markUserScroll(500);
  }, [markUserScroll]);

  const jumpToLatest = useCallback(() => {
    setFollowLatest(true);
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
    virtualizer.scrollToIndex(items.length - 1, { align: "end" });
  }, [items.length, setFollowLatest, virtualizer]);

  const itemState = useMemo<ConversationItemState>(() => ({
    isExpanded: (key, defaultValue = false) => expandedItems[`${conversationId}:${key}`] ?? defaultValue,
    setExpanded: (key, expanded) => {
      const fullKey = `${conversationId}:${key}`;
      setExpandedItems((current) => current[fullKey] === expanded ? current : { ...current, [fullKey]: expanded });
    },
  }), [conversationId, expandedItems]);

  const firstVirtualItem = virtualItems[0];
  const lastVirtualItem = virtualItems[virtualItems.length - 1];

  return (
    <div className="conversation-list-shell">
      <div
        className={scrollClassName}
        ref={scrollRef}
        onScroll={onScroll}
        onWheel={onWheel}
        onTouchMove={() => markUserScroll(1500)}
        onPointerDown={(event) => {
          if (event.target === event.currentTarget) markUserScroll(1000);
        }}
        onKeyDown={(event) => {
          if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) {
            markUserScroll(500);
          }
        }}
        tabIndex={tabIndex}
        data-following-latest={pinned}
        data-testid={scrollTestId}
      >
        <div className={contentClassName}>
          {items.length === 0 ? emptyContent : null}
          {items.length > 0 && firstVirtualItem ? (
            <div className="conversation-list-spacer" style={{ height: `${firstVirtualItem.start}px` }} aria-hidden="true" />
          ) : null}
          {virtualItems.map((virtualItem) => {
            const item = items[virtualItem.index];
            if (!item) return null;
            return (
              <div
                key={virtualItem.key}
                ref={virtualizer.measureElement}
                data-index={virtualItem.index}
                data-timeline-key={itemKeys[virtualItem.index]}
                className={rowClassName}
              >
                {renderItem(item, itemState)}
              </div>
            );
          })}
          {items.length > 0 && lastVirtualItem ? (
            <div
              className="conversation-list-spacer"
              style={{ height: `${Math.max(0, totalSize - lastVirtualItem.end)}px` }}
              aria-hidden="true"
            />
          ) : null}
        </div>
      </div>
      {!pinned && items.length > 0
        ? (
          <div className="conversation-list-jump-overlay">
            {renderJumpButton?.(jumpToLatest) ?? (
              <button type="button" className="conversation-jump-latest" onClick={jumpToLatest}>
                回到最新
              </button>
            )}
          </div>
        )
        : null}
    </div>
  );
}
