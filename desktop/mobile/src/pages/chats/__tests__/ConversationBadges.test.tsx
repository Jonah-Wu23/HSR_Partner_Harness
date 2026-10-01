import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ConversationBadgeRow } from "../ConversationBadges";
import {
  deriveConversationBadges,
  type ConversationBadgeSource,
  type ConversationBadges,
} from "../useConversationBadges";
import type { PendingApproval, QueueItem } from "@shared/contracts/protocol";

describe("ConversationBadgeRow 组件", () => {
  afterEach(() => {
    cleanup();
  });

  it("没有运行中任务、待审批与排队项时不渲染", () => {
    const badges: ConversationBadges = { running: false, pendingApprovals: 0, queued: 0 };
    const { container } = render(<ConversationBadgeRow conversationId="c1" badges={badges} />);
    expect(container.firstChild).toBeNull();
  });

  it.each([
    { badges: { running: true, pendingApprovals: 0, queued: 0 }, testId: "badge-running-c1", text: "运行中" },
    { badges: { running: false, pendingApprovals: 3, queued: 0 }, testId: "badge-approvals-c1", text: "待审批 3" },
    { badges: { running: false, pendingApprovals: 0, queued: 2 }, testId: "badge-queued-c1", text: "排队 2" },
  ])("$testId 显示「$text」", ({ badges, testId, text }) => {
    render(<ConversationBadgeRow conversationId="c1" badges={badges} />);
    expect(screen.getByTestId(testId)).toHaveTextContent(text);
  });
});

describe("deriveConversationBadges 数据派生", () => {
  function approval(approvalId: string, conversationId: string): PendingApproval {
    return {
      approval_id: approvalId,
      conversation_id: conversationId,
      task_id: "t1",
      operation: { tool_kind: "shell", command: "npm test", paths: [], patch_file_count: null, summary: "运行测试" },
      reason: "需要执行命令",
    };
  }

  function queueItem(queueItemId: string, conversationId: string, status: QueueItem["status"]): QueueItem {
    return {
      queue_item_id: queueItemId,
      account_id: "acc-1",
      conversation_id: conversationId,
      target: "character",
      text: "稍后再聊",
      intent: "followup",
      position: 0,
      status,
      error: status === "failed" ? "派发失败：会话不存在" : null,
      created_at: "2026-08-20T10:00:00Z",
      source_message_id: null,
      origin: "remote",
      remote_device_key: "dev-1",
      remote_device_name: "我的手机",
    };
  }

  const source: ConversationBadgeSource = {
    activeTasks: [{ project_id: "p1", task_id: "t1", conversation_id: "c1", engine_turn_id: "e1" }],
    approvals: [approval("a1", "c1"), approval("a2", "c1"), approval("a3", "c2")],
    // store 只保留当前聊天的待派发与派发失败项；派发失败不计入排队数。
    queueItems: [queueItem("q1", "c1", "queued"), queueItem("q2", "c1", "failed")],
  };

  it.each([
    { conversationId: "c1", expected: { running: true, pendingApprovals: 2, queued: 1 } },
    { conversationId: "c2", expected: { running: false, pendingApprovals: 1, queued: 0 } },
    { conversationId: "c3", expected: { running: false, pendingApprovals: 0, queued: 0 } },
  ])("$conversationId 只统计属于自己的任务、审批与待派发项", ({ conversationId, expected }) => {
    expect(deriveConversationBadges(conversationId, source)).toEqual(expected);
  });
});
