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
import { useConversationScroll, type ConversationAnchor } from "./useConversationScroll";

export interface ConversationItemState {
  isExpanded: (key: string, defaultValue?: boolean) => boolean;
  setExpanded: (key: string, expanded: boolean) => void;
}

interface ConversationListProps<T> {
  conversationId: string;
  /** 传入时按 listId 与会话保存时间线快照（测量缓存、滚动位置、跟随与展开状态），
      切回该会话时恢复；同一会话的多条时间线（角色区与工作台）用不同 listId。 */
  listId?: string;
  active?: boolean;
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

/** 离开会话时保存的时间线状态，切回时恢复行高、滚动位置、跟随状态与展开状态。 */
interface TimelineSnapshot {
  measurements: VirtualItem[];
  scrollTop: number;
  viewport: Rect;
  following: boolean;
  anchor: ConversationAnchor | null;
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
  active = true,
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
  const {
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
  } = useConversationScroll({ following: restored?.following ?? true, anchor: restored?.anchor ?? null });
  const contentRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef(active);
  activeRef.current = active;
  const wasActiveRef = useRef(active);
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
        if (activeRef.current) reconcileLayout();
      }),
  });
  virtualizer.shouldAdjustScrollPositionOnItemSizeChange = () => false;
  const totalSize = virtualizer.getTotalSize();
  const virtualItems = virtualizer.getVirtualItems();

  useLayoutEffect(() => {
    const wasActive = wasActiveRef.current;
    wasActiveRef.current = active;
    if (!active) return;
    if (!wasActive && contentRef.current) {
      // 重新展开时只更新已挂载行的高度，其余行继续使用会话测量缓存。
      const measurements = Array.from(
        contentRef.current.querySelectorAll<HTMLElement>("[data-timeline-key]"),
        (row) => ({ index: Number(row.dataset.index), height: row.offsetHeight }),
      );
      for (const { index, height } of measurements) virtualizer.resizeItem(index, height);
    }
    if (items.length > 0) reconcileLayout();
  }, [active, items, totalSize, following, reconcileLayout, virtualizer]);

  useLayoutEffect(() => {
    const content = contentRef.current;
    const ResizeObserverClass = content?.ownerDocument.defaultView?.ResizeObserver;
    if (!active || !content || !ResizeObserverClass) return;
    let frame = 0;
    const observer = new ResizeObserverClass(() => {
      if (!activeRef.current) return;
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        if (activeRef.current) reconcileLayout();
      });
    });
    observer.observe(content);
    return () => {
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [active, reconcileLayout]);

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
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchCancel}
        onPointerDown={onPointerDown}
        onKeyDown={onKeyDown}
        tabIndex={tabIndex}
        data-following-latest={following}
        data-testid={scrollTestId}
      >
        <div className={contentClassName} ref={contentRef}>
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
