import {
  memo,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import {
  defaultRangeExtractor,
  observeElementRect,
  useVirtualizer,
  type Range,
  type Rect,
  type VirtualItem,
} from "@tanstack/react-virtual";

export interface ConversationItemState {
  isExpanded: (key: string, defaultValue?: boolean) => boolean;
  setExpanded: (key: string, expanded: boolean) => void;
}

interface ConversationListProps<T> {
  conversationId: string;
  /** 传入时按 listId 与会话保存时间线快照（测量缓存、滚动位置、跟随与展开状态），
      切回该会话时恢复；同一会话的多条时间线（角色区与工作台）用不同 listId。 */
  listId?: string;
  items: readonly T[];
  /** 返回条目在本会话内唯一的 key；可以每次渲染传新函数。 */
  getItemKey: (item: T) => string;
  estimateSize: number;
  overscan?: number;
  scrollClassName: string;
  contentClassName: string;
  rowClassName: string;
  scrollTestId?: string;
  emptyContent?: ReactNode;
  tabIndex?: number;
  /** 传稳定引用时，未变化的行在流式更新中跳过渲染。 */
  renderItem: (item: T, state: ConversationItemState) => ReactNode;
  renderJumpButton: (jumpToLatest: () => void) => ReactNode;
}

interface Anchor {
  key: string;
  index: number;
  top: number;
}

/** 离开会话时保存的时间线状态，切回时恢复行高、滚动位置、跟随状态与展开状态。 */
interface TimelineSnapshot {
  measurements: VirtualItem[];
  scrollTop: number;
  viewport: Rect;
  following: boolean;
  anchor: Anchor | null;
  expanded: Record<string, boolean>;
}

/** 最近离开的时间线快照，超出上限时淘汰最久未用的一条。 */
const snapshots = new Map<string, TimelineSnapshot>();
const SNAPSHOT_LIMIT = 40;

function saveSnapshot(key: string, snapshot: TimelineSnapshot): void {
  snapshots.delete(key);
  snapshots.set(key, snapshot);
  if (snapshots.size > SNAPSHOT_LIMIT) snapshots.delete(snapshots.keys().next().value!);
}

/** 不超过 40 行时全部挂载，超过后只挂载视口附近的行。 */
function extractRange(range: Range): number[] {
  return range.count <= 40
    ? Array.from({ length: range.count }, (_, index) => index)
    : defaultRangeExtractor(range);
}

const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]);
/** 向上翻阅的按键，按下即停止跟随最新消息。 */
const UPWARD_KEYS = new Set(["ArrowUp", "PageUp", "Home"]);

function distanceFromBottom(node: HTMLElement): number {
  return node.scrollHeight - node.clientHeight - node.scrollTop;
}

interface TimelineRowProps<T> {
  item: T;
  index: number;
  itemKey: string;
  className: string;
  measure: (node: HTMLDivElement | null) => void;
  renderItem: (item: T, state: ConversationItemState) => ReactNode;
  itemState: ConversationItemState;
}

/** 时间线的一行：item 引用不变的行在流式更新时跳过渲染，行高交给虚拟器的 ResizeObserver。 */
const TimelineRow = memo(function TimelineRow<T>({
  item,
  index,
  itemKey,
  className,
  measure,
  renderItem,
  itemState,
}: TimelineRowProps<T>) {
  return (
    <div ref={measure} data-index={index} data-timeline-key={itemKey} className={className}>
      {renderItem(item, itemState)}
    </div>
  );
}) as <T>(props: TimelineRowProps<T>) => ReactElement;

/**
 * 桌面端与移动端聊天共用的动态行高时间线。每个会话单独挂载一份；带 listId 时离开会话保存
 * 测量缓存、滚动位置、跟随状态与展开状态，切回时据此恢复，不清空也不重新测量已知行高。
 */
export function ConversationList<T>(props: ConversationListProps<T>) {
  const timelineKey = `${props.listId ?? ""}\u0000${props.conversationId}`;
  return (
    <ConversationTimeline
      key={timelineKey}
      snapshotKey={props.listId === undefined ? null : timelineKey}
      {...props}
    />
  );
}

function ConversationTimeline<T>({
  snapshotKey,
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
}: ConversationListProps<T> & { snapshotKey: string | null }) {
  const [restored] = useState(() => (snapshotKey === null ? null : snapshots.get(snapshotKey) ?? null));
  const scrollRef = useRef<HTMLDivElement>(null);
  const followingRef = useRef(restored?.following ?? true);
  const [following, setFollowing] = useState(followingRef.current);
  const userScrollUntilRef = useRef(0);
  const touchingRef = useRef(false);
  const anchorRef = useRef<Anchor | null>(restored?.anchor ?? null);
  const [expandedItems, setExpandedItems] = useState(restored?.expanded ?? {});
  const expandedRef = useRef(expandedItems);

  // key 列表只在条目增删或换序时换新数组；流式更新正文时沿用旧数组，
  // 虚拟器的 getItemKey 保持同一引用，测量缓存不重建。
  const keysRef = useRef<string[]>([]);
  const itemKeys = useMemo(() => {
    const keys = items.map(getItemKey);
    const previous = keysRef.current;
    if (keys.length !== previous.length || keys.some((key, index) => key !== previous[index])) {
      keysRef.current = keys;
    }
    return keysRef.current;
  }, [items, getItemKey]);
  const getVirtualKey = useCallback((index: number) => itemKeys[index], [itemKeys]);

  const setFollowLatest = useCallback((next: boolean) => {
    followingRef.current = next;
    setFollowing(next);
  }, []);

  /** 记下视口顶部第一行作为阅读锚点，只读布局。 */
  const captureAnchor = useCallback(() => {
    const node = scrollRef.current!;
    const viewportTop = node.getBoundingClientRect().top;
    for (const row of node.querySelectorAll<HTMLElement>("[data-timeline-key]")) {
      const rect = row.getBoundingClientRect();
      if (rect.bottom > viewportTop) {
        anchorRef.current = {
          key: row.dataset.timelineKey!,
          index: Number(row.dataset.index),
          top: rect.top - viewportTop,
        };
        return;
      }
    }
  }, []);

  /** 跟随最新时贴底，否则把阅读锚点放回原来的视口位置。先读完布局再写一次 scrollTop。
      手指按在列表上时不写 scrollTop，避免和拖动抢位置。 */
  const keepPosition = useCallback(() => {
    if (touchingRef.current) return;
    const node = scrollRef.current!;
    if (followingRef.current) {
      node.scrollTop = node.scrollHeight;
      return;
    }
    const anchor = anchorRef.current;
    if (!anchor) return;
    const row = Array.from(node.querySelectorAll<HTMLElement>("[data-timeline-key]")).find(
      (candidate) => candidate.dataset.timelineKey === anchor.key,
    );
    if (!row) {
      captureAnchor();
      return;
    }
    anchor.index = Number(row.dataset.index);
    const drift = row.getBoundingClientRect().top - node.getBoundingClientRect().top - anchor.top;
    if (Math.abs(drift) > 0.5) node.scrollTop += drift;
  }, [captureAnchor]);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    initialRect: restored?.viewport ?? { width: 1, height: estimateSize },
    // 跟随最新时从末尾开始计算可见范围，首帧就渲染最后几行。
    initialOffset: restored?.following === false ? restored.scrollTop : Number.MAX_SAFE_INTEGER,
    initialMeasurementsCache: restored?.measurements,
    overscan,
    getItemKey: getVirtualKey,
    rangeExtractor: extractRange,
    // 复用虚拟器对滚动容器的 ResizeObserver：拖动分隔条、窗口改宽或输入区长高时，
    // 在同一帧里保持贴底或阅读锚点；各行高度变化由 measureElement 的观察者逐行上报。
    observeElementRect: (instance, onRect) =>
      observeElementRect(instance, (rect) => {
        onRect(rect);
        keepPosition();
      }),
  });
  virtualizer.shouldAdjustScrollPositionOnItemSizeChange = (item) => {
    const anchorIndex = anchorRef.current?.index;
    return !followingRef.current && anchorIndex !== undefined && item.index < anchorIndex;
  };
  const totalSize = virtualizer.getTotalSize();
  const virtualItems = virtualizer.getVirtualItems();

  useLayoutEffect(() => {
    if (items.length > 0) keepPosition();
  }, [items, totalSize, following, keepPosition]);

  useLayoutEffect(() => {
    expandedRef.current = expandedItems;
  }, [expandedItems]);

  // 卸载（切换会话）时保存快照；读取虚拟器已记录的偏移与视口，不触发布局。
  useLayoutEffect(
    () => () => {
      if (snapshotKey === null) return;
      saveSnapshot(snapshotKey, {
        measurements: virtualizer.takeSnapshot(),
        scrollTop: virtualizer.scrollOffset ?? 0,
        viewport: virtualizer.scrollRect ?? { width: 1, height: estimateSize },
        following: followingRef.current,
        anchor: anchorRef.current,
        expanded: expandedRef.current,
      });
    },
    [estimateSize, snapshotKey, virtualizer],
  );

  const markUserScroll = (duration: number) => {
    userScrollUntilRef.current = Date.now() + duration;
  };

  /** 用户开始向上翻阅：内容可滚动时立即停止跟随，不等滚动事件，流式更新不会再把视口拉回底部。 */
  const leaveFollow = () => {
    const node = scrollRef.current!;
    if (!followingRef.current || node.scrollHeight <= node.clientHeight) return;
    captureAnchor();
    setFollowLatest(false);
  };

  /** 手势结束时已在底部则恢复跟随。 */
  const followIfAtBottom = (node: HTMLElement) => {
    if (distanceFromBottom(node) <= 2) setFollowLatest(true);
  };

  // 触摸开始即暂停贴底与锚点写入，拖动产生的滚动事件按离底距离决定是否继续跟随；
  // 松手后补一次位置（只点按没有拖动时回到底部）。
  const onTouchStart = () => {
    touchingRef.current = true;
    markUserScroll(1500);
  };

  const onTouchEnd = () => {
    touchingRef.current = false;
    markUserScroll(1500);
    keepPosition();
  };

  const onScroll = () => {
    captureAnchor();
    if (Date.now() > userScrollUntilRef.current) return;
    setFollowLatest(distanceFromBottom(scrollRef.current!) <= 2);
  };

  const onWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    const innerScroller = (event.target as HTMLElement).closest<HTMLElement>("[data-internal-scroll]");
    if (innerScroller && innerScroller.scrollHeight > innerScroller.clientHeight) {
      const atTop = innerScroller.scrollTop <= 0 && event.deltaY < 0;
      const atBottom =
        innerScroller.scrollTop + innerScroller.clientHeight >= innerScroller.scrollHeight - 1 &&
        event.deltaY > 0;
      if (!atTop && !atBottom) return;
    }
    markUserScroll(500);
    if (event.deltaY < 0) leaveFollow();
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    // 按在滚动容器本身（滚动条或内边距）上：按住期间的滚动都算用户滚动，松开时在底部则恢复跟随。
    if (event.target !== event.currentTarget) return;
    const node = event.currentTarget;
    userScrollUntilRef.current = Number.POSITIVE_INFINITY;
    leaveFollow();
    const release = () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
      markUserScroll(500);
      followIfAtBottom(node);
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!SCROLL_KEYS.has(event.key)) return;
    markUserScroll(500);
    if (UPWARD_KEYS.has(event.key) || (event.key === " " && event.shiftKey)) leaveFollow();
  };

  const jumpToLatest = () => {
    setFollowLatest(true);
    const node = scrollRef.current!;
    node.scrollTop = node.scrollHeight;
    virtualizer.scrollToIndex(items.length - 1, { align: "end" });
  };

  // 展开状态变化时换新对象，可见行随之重渲染；其余时候保持同一引用，memo 行可以跳过。
  const itemState = useMemo<ConversationItemState>(() => ({
    isExpanded: (key, defaultValue = false) => expandedItems[key] ?? defaultValue,
    setExpanded: (key, expanded) => {
      setExpandedItems((current) => current[key] === expanded ? current : { ...current, [key]: expanded });
    },
  }), [expandedItems]);

  const firstVirtualItem = virtualItems[0];
  const lastVirtualItem = virtualItems[virtualItems.length - 1];

  return (
    <div className="conversation-list-shell">
      <div
        className={scrollClassName}
        ref={scrollRef}
        onScroll={onScroll}
        onWheel={onWheel}
        onTouchStart={onTouchStart}
        onTouchMove={() => markUserScroll(1500)}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchEnd}
        onPointerDown={onPointerDown}
        onKeyDown={onKeyDown}
        tabIndex={tabIndex}
        data-following-latest={following}
        data-testid={scrollTestId}
      >
        <div className={contentClassName}>
          {items.length === 0 ? emptyContent : null}
          {/* 视口高度为 0 时虚拟器不给出可见行，此时不渲染占位。 */}
          {firstVirtualItem && lastVirtualItem ? (
            <>
              <div
                className="conversation-list-spacer"
                style={{ height: `${firstVirtualItem.start}px` }}
                aria-hidden="true"
              />
              {virtualItems.map((virtualItem) => (
                <TimelineRow
                  key={virtualItem.key}
                  item={items[virtualItem.index]}
                  index={virtualItem.index}
                  itemKey={itemKeys[virtualItem.index]}
                  className={rowClassName}
                  measure={virtualizer.measureElement}
                  renderItem={renderItem}
                  itemState={itemState}
                />
              ))}
              <div
                className="conversation-list-spacer"
                style={{ height: `${totalSize - lastVirtualItem.end}px` }}
                aria-hidden="true"
              />
            </>
          ) : null}
        </div>
      </div>
      {!following && items.length > 0 ? (
        <div className="conversation-list-jump-overlay">{renderJumpButton(jumpToLatest)}</div>
      ) : null}
    </div>
  );
}
