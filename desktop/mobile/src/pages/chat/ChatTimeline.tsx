import { memo, useCallback } from "react";
import type { ActiveTask, Message, QueueItem, ToolRun } from "@shared/contracts/protocol";
import { ConversationList, type ConversationItemState } from "@shared/ui/conversation/ConversationList";
import { DelegationCard, type DelegationStatus } from "../../components/cards/DelegationCard";
import { ToolCard } from "../../components/cards/ToolCard";
import { useMobileStore, selectConversationCharacterIdentity } from "../../lib/mobileStore";
import { MessageBubble } from "./MessageBubble";
import { QueueItemRow } from "./QueueItemRow";
import { useChatTimeline, type TimelineItem } from "./useChatTimeline";
import { usePlaybackError, usePlaybackMessageId, usePlayingMessageId } from "./usePlaybackStatus";

/** 委派卡状态，与桌面 presenters.presentDelegation 同语义：
活动任务匹配或 processing 为 running，failed / cancelled 同名，其余为 completed。 */
function delegationStatusOf(
  message: Message,
  activeTask: ActiveTask | null,
): DelegationStatus {
  if (activeTask?.task_id && activeTask.task_id === message.delegation_id) {
    return "running";
  }
  if (message.status === "processing") return "running";
  if (message.status === "failed") return "failed";
  if (message.status === "cancelled") return "cancelled";
  return "completed";
}

/** origin=character_delegation 的 user 消息渲染为「来自 <角色名> 的委派」卡片，与桌面 presenters 判定一致。 */
function isDelegationMessage(message: Message): boolean {
  return (
    message.source === "user" &&
    message.origin === "character_delegation" &&
    Boolean(message.delegation_id)
  );
}

const timelineItemKey = (item: TimelineItem): string => item.id;

/** 工具卡的展开状态记在列表里，行滚出窗口再回来时保持。 */
const TimelineToolCard = memo(function TimelineToolCard({
  run,
  itemState,
}: {
  run: ToolRun;
  itemState: ConversationItemState;
}) {
  const key = `tool:${run.tool_call_id}`;
  return (
    <ToolCard
      run={run}
      expanded={itemState.isExpanded(key)}
      onExpandedChange={(expanded) => itemState.setExpanded(key, expanded)}
    />
  );
});

/** 排队行；命令失败由行内展示。 */
const TimelineQueueItem = memo(function TimelineQueueItem({ queueItem }: { queueItem: QueueItem }) {
  const withdrawQueueItem = useMobileStore((state) => state.withdrawQueueItem);
  const editQueueItem = useMobileStore((state) => state.editQueueItem);
  const prioritizeQueueItem = useMobileStore((state) => state.prioritizeQueueItem);
  const queueItemId = queueItem.queue_item_id;
  return (
    <QueueItemRow
      queueItem={queueItem}
      onWithdraw={() => withdrawQueueItem(queueItemId)}
      onPrioritize={() => prioritizeQueueItem(queueItemId)}
      onEdit={(text) => editQueueItem(queueItemId, text)}
    />
  );
});

function TimelineSkeleton() {
  return (
    <div className="mobile-chat-skeleton" role="status" aria-label="正在装载聊天记录" data-testid="chat-timeline-skeleton">
      <div className="mobile-chat-skeleton-bubble" />
      <div className="mobile-chat-skeleton-bubble is-user" />
      <div className="mobile-chat-skeleton-bubble" />
    </div>
  );
}

export interface ChatTimelineProps {
  conversationId: string;
}

/**
 * 聊天时间线：消息与工具卡混合列表。只订阅当前聊天的消息、工具记录、排队项与朗读状态，
 * 流式回复只重新渲染这里和变化的那一行，输入区、语音栏与审批卡不受影响。
 * 装载结果到达前展示缓存时间线或骨架；装载失败时页面顶部的错误条提供重试。
 */
export const ChatTimeline = memo(function ChatTimeline({ conversationId }: ChatTimelineProps) {
  const items = useChatTimeline(conversationId);
  const loading = useMobileStore(
    (state) => state.activeConversationId !== conversationId || state.timelineLoading,
  );
  const openFailed = useMobileStore((state) => state.openError?.conversationId === conversationId);
  // 角色名按正在查看的会话取：会话 character_identity 优先（卡会话显示卡名），
  // 旧会话没有该字段时维持从搭档回退；助手名仍用搭档的助手侧。
  const characterName = useMobileStore(
    (state) =>
      selectConversationCharacterIdentity(state, conversationId)?.name ||
      state.pair?.character?.name,
  );
  const assistantName = useMobileStore((state) => state.pair?.assistant?.name);
  const activeTask = useMobileStore((state) => state.activeTask);
  const stopVoicePlayback = useMobileStore((state) => state.stopVoicePlayback);
  const playingMessageId = usePlayingMessageId();
  const playbackMessageId = usePlaybackMessageId();
  const playbackError = usePlaybackError();

  const stopPlayback = useCallback(
    (messageId: string) => {
      // 停止失败已写入 playback.error，由页级播放错误条展示。
      stopVoicePlayback(messageId).catch((err: unknown) => {
        console.error("停止朗读失败", messageId, err);
      });
    },
    [stopVoicePlayback],
  );

  // 依赖在流式期间不变，renderItem 保持同一引用，未变化的行整行跳过。
  const renderItem = useCallback((item: TimelineItem, itemState: ConversationItemState) => {
    if (item.kind === "tool_run") {
      return <TimelineToolCard run={item.toolRun} itemState={itemState} />;
    }
    if (item.kind === "queue_item") {
      return <TimelineQueueItem queueItem={item.queueItem} />;
    }
    const message = item.message;
    if (isDelegationMessage(message)) {
      return (
        <DelegationCard
          delegationId={message.delegation_id ?? ""}
          fromName={characterName || "角色"}
          summary={message.text}
          status={delegationStatusOf(message, activeTask)}
        />
      );
    }
    return (
      <MessageBubble
        message={message}
        characterName={characterName}
        assistantName={assistantName}
        itemState={itemState}
        playingMessageId={playingMessageId}
        playbackError={message.message_id === playbackMessageId ? playbackError : null}
        onStopPlayback={stopPlayback}
      />
    );
  }, [
    activeTask,
    assistantName,
    characterName,
    playbackError,
    playbackMessageId,
    playingMessageId,
    stopPlayback,
  ]);

  return (
    <ConversationList
      conversationId={conversationId}
      items={items}
      getItemKey={timelineItemKey}
      estimateSize={80}
      overscan={6}
      scrollClassName="mobile-chat-scroll"
      contentClassName="mobile-virtual-container"
      rowClassName="mobile-virtual-row"
      scrollTestId="chat-scroll"
      tabIndex={-1}
      emptyContent={
        openFailed ? null : loading ? (
          <TimelineSkeleton />
        ) : (
          <div className="mobile-chat-empty">
            <p>暂无消息</p>
            <p className="hint">给角色发消息，或切换到协作模式后把任务交给助手。</p>
          </div>
        )
      }
      renderItem={renderItem}
      renderJumpButton={(jump) => (
        <button
          type="button"
          className="mobile-jump-latest"
          onClick={jump}
          aria-label="滚动回到最新消息"
        >
          <span>回到最新</span>
        </button>
      )}
    />
  );
});
