import { beforeEach, describe, expect, it } from "vitest";

import type {
  ConversationOpenResult,
  DesktopEvent,
  DesktopEventName,
  HostEvent,
  MemoryWirePayload,
  PairOption,
  PowerStatusPayload,
  ToolRun,
} from "../contracts/protocol";
import { MOCK_PAIR_OPTIONS, createMockScenario, message } from "../mocks/scenarios";
import { presentAppShell } from "../presenters/presenters";
import { createActionController } from "../services/actions";
import { MockDesktopBackend } from "../services/mockDesktopBackend";
import { desktopStore, selectComposerTarget, selectWindowMode } from "./desktopStore";

/** 清空跨用例状态后按 single-project 水合；连接代次由各用例的快照或事件建立。 */
function resetStore() {
  desktopStore.setState(desktopStore.getInitialState(), true);
  desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
  desktopStore.setState({ streamId: null });
}

function event(name: DesktopEventName, payload: object, sequence: number): DesktopEvent {
  return { kind: "event", event: name, sequence, payload: payload as Record<string, unknown> };
}

/** Rust 宿主合成的连接事件与错误通道事件，不带序号。 */
function hostEvent(name: HostEvent["event"], payload: Record<string, unknown>): HostEvent {
  return { kind: "event", event: name, payload };
}

const singleProjectSnapshot = () => createMockScenario("single-project").snapshot;

/** 指定连接代次里 conv-1 的一条助手消息。 */
function assistantMessage(
  sequence: number,
  messageId: string,
  streamId: string,
  text = `消息 ${sequence}`,
): DesktopEvent {
  return {
    ...event(
      "message.created",
      { message: message(messageId, "conv-1", "assistant", "assistant.natural_language", text) },
      sequence,
    ),
    stream_id: streamId,
  };
}

function snapshotEvent(sequence: number, streamId: string): DesktopEvent {
  return {
    ...event("state.snapshot", { ...singleProjectSnapshot(), stream_id: streamId, sequence }, sequence),
    stream_id: streamId,
  };
}

/** Rust publish_disconnected 随 connection.status 一起发出的断连通知。 */
const disconnectNotice = {
  code: "backend_disconnected",
  message: "Python Sidecar 已断开，正在重连…",
  severity: "recoverable",
  source: "sidecar",
};

/** 目录里的一个角色卡绑定项（辅助断言快照 pairs）。 */
const CARD_OPTION: PairOption = {
  binding_id: "card-bind-card-saved-002",
  pair_id: "phainon_ancient_machine",
  character_card_id: "card-saved-002",
  source: "card",
  character: {
    id: "card-saved-002",
    name: "卡芙卡",
    voice_id: "",
    avatar_ref: null,
    avatar_version: null,
    missing: false,
  },
  assistant: { ...MOCK_PAIR_OPTIONS[0].assistant },
  theme: { ...MOCK_PAIR_OPTIONS[0].theme },
};

describe("搭档目录与目录版本", () => {
  beforeEach(resetStore);

  it("card.updated / pair.updated 只推进待重取计数，不改目录内容与目录版本", () => {
    const before = desktopStore.getState();
    const pairsBefore = before.pairs;
    const versionBefore = before.catalogVersion;
    expect(pairsBefore.length).toBeGreaterThan(0);

    desktopStore.getState().applyEvents([
      event("card.updated", { card_id: "card-saved-002", catalog_version: versionBefore + 1 }, 1),
      event("pair.updated", { catalog_version: versionBefore + 2 }, 2),
    ]);

    const state = desktopStore.getState();
    expect(state.catalogRevision).toBe(before.catalogRevision + 2);
    expect(state.pairs).toBe(pairsBefore);
    expect(state.catalogVersion).toBe(versionBefore);
  });

  it("pair.list 响应推进目录与版本，旧版本或同版本响应被丢弃", () => {
    const initialVersion = desktopStore.getState().catalogVersion;
    const fresh = [...MOCK_PAIR_OPTIONS, CARD_OPTION];

    desktopStore.getState().applyPairCatalog({ pairs: fresh, catalog_version: initialVersion + 1 });
    expect(desktopStore.getState().pairs).toEqual(fresh);
    expect(desktopStore.getState().catalogVersion).toBe(initialVersion + 1);

    // 乱序迟到的旧响应与同版本响应都不能覆盖已存的较新目录。
    desktopStore.getState().applyPairCatalog({
      pairs: MOCK_PAIR_OPTIONS,
      catalog_version: initialVersion,
    });
    desktopStore.getState().applyPairCatalog({
      pairs: MOCK_PAIR_OPTIONS,
      catalog_version: initialVersion + 1,
    });
    expect(desktopStore.getState().pairs).toEqual(fresh);
    expect(desktopStore.getState().catalogVersion).toBe(initialVersion + 1);
  });

  it("快照水合写入权威 pairs 与 catalog_version", () => {
    const pairs = [...MOCK_PAIR_OPTIONS, CARD_OPTION];
    desktopStore.getState().hydrate({
      ...createMockScenario("single-project").snapshot,
      pairs,
      catalog_version: 9,
    });

    const state = desktopStore.getState();
    expect(state.pairs).toEqual(pairs);
    expect(state.catalogVersion).toBe(9);
  });
});

describe("desktopStore 事件投影", () => {
  beforeEach(resetStore);

  it("流式消息与工具记录归属到各自来源的聊天", () => {
    const events: DesktopEvent[] = [
      {
        kind: "event",
        event: "message.delta",
        sequence: 1,
        payload: {
          message_id: "stream-other",
          conversation_id: "other-conversation",
          source: "assistant",
          kind: "assistant.natural_language",
          delta: "来自另一聊天",
          timeline_order: 1,
        },
      },
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 2,
        payload: {
          tool_run: {
            tool_call_id: "tool-1",
            conversation_id: "other-conversation",
            task_id: "task-1",
            engine_turn_id: "turn-1",
            sequence: 1,
            status: "running",
            title: "读取文件",
            summary: "进行中",
            details: "",
            timeline_order: 2,
          } satisfies ToolRun,
        },
      },
    ];
    desktopStore.getState().applyEvents(events);

    const state = desktopStore.getState();
    expect(state.messageIdsByConversation["other-conversation"]).toEqual(["stream-other"]);
    expect(state.toolIdsByConversation["other-conversation"]).toEqual([
      "other-conversation\u0000tool-1",
    ]);
    expect(state.messageIdsByConversation["conv-1"]).toEqual(["message-1", "message-2"]);
  });

  it("聊天模式下发送对象固定为角色，协作模式沿用用户选择", () => {
    const conversation = desktopStore.getState().conversationsById["conv-1"];
    const modeChanged = (sequence: number, lastMode: "chat" | "collaboration") =>
      event("conversation.changed", { conversation: { ...conversation, last_mode: lastMode } }, sequence);

    desktopStore.getState().applyEvents([modeChanged(1, "collaboration")]);
    desktopStore.getState().setComposerTarget("assistant");
    expect(selectComposerTarget(desktopStore.getState())).toBe("assistant");

    desktopStore.getState().applyEvents([modeChanged(2, "chat")]);
    expect(selectWindowMode(desktopStore.getState())).toBe("chat");
    expect(selectComposerTarget(desktopStore.getState())).toBe("character");
  });

  it("两个会话复用同一 tool_call_id 时按会话分别保存", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 1,
        payload: {
          tool_run: {
            tool_call_id: "tool-dup",
            conversation_id: "conv-1",
            task_id: "task-1",
            engine_turn_id: "turn-1",
            sequence: 1,
            status: "running",
            title: "A 会话工具",
            summary: "",
            details: "",
            timeline_order: 1,
          } satisfies ToolRun,
        },
      },
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 2,
        payload: {
          tool_run: {
            tool_call_id: "tool-dup",
            conversation_id: "conv-2",
            task_id: "task-2",
            engine_turn_id: "turn-2",
            sequence: 1,
            status: "denied",
            title: "B 会话工具",
            summary: "沙箱拦截",
            details: "沙箱拦截",
            timeline_order: 1,
          } satisfies ToolRun,
        },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.toolRunsById["conv-1\u0000tool-dup"]?.conversation_id).toBe("conv-1");
    expect(state.toolRunsById["conv-2\u0000tool-dup"]?.conversation_id).toBe("conv-2");
    expect(state.toolRunsById["tool-dup"]).toBeUndefined();
  });

  it.each([
    [
      "角色 reasoning 通道",
      "speech:conv-1:user-1",
      [
        {
          source: "character",
          kind: "character.speech",
          channel: "reasoning",
          delta: "先看看",
          started: true,
          reasoning_streaming: true,
        },
        { source: "character", kind: "character.speech", delta: "你好。" },
      ],
      { text: "你好。", payload: { reasoning: "先看看", reasoning_streaming: true } },
    ],
    [
      "助手 assistant.reasoning 分片",
      "assistant:conv-1:task-1",
      [
        {
          source: "assistant",
          kind: "assistant.reasoning",
          channel: "summary",
          delta: "先检查项目。",
          reasoning_streaming: true,
        },
        {
          source: "assistant",
          kind: "assistant.natural_language",
          delta: "项目已检查。",
          reasoning_streaming: false,
        },
      ],
      { text: "项目已检查。", payload: { reasoning: "先检查项目。", reasoning_streaming: false } },
    ],
  ])("%s的思考与正文合并到同一条流式消息", (_name, messageId, deltas, expected) => {
    desktopStore.getState().applyEvents(
      deltas.map((delta, index) =>
        event(
          "message.delta",
          { message_id: messageId, conversation_id: "conv-1", timeline_order: 10, ...delta },
          index + 1,
        ),
      ),
    );

    const state = desktopStore.getState();
    expect(state.messageIdsByConversation["conv-1"]?.filter((id) => id === messageId)).toHaveLength(1);
    expect(state.messagesById[messageId]).toMatchObject({ ...expected, streaming: true });
  });

  it("message.created 用最终记录替换同 id 的流式消息，不重复追加", () => {
    const messageId = "speech:conv-1:user-1";
    const final = {
      ...message(messageId, "conv-1", "character", "character.speech", "你好。"),
      payload: { reasoning: "先看看" },
    };
    desktopStore.getState().applyEvents([
      event(
        "message.delta",
        {
          message_id: messageId,
          conversation_id: "conv-1",
          source: "character",
          kind: "character.speech",
          delta: "你好。",
          timeline_order: final.timeline_order,
        },
        1,
      ),
      event("message.created", { message: final }, 2),
    ]);

    const state = desktopStore.getState();
    expect(state.messageIdsByConversation["conv-1"]?.filter((id) => id === messageId)).toHaveLength(1);
    expect(state.messagesById[messageId]).toEqual(final);
  });

  it("error.reported 进 Toast 队列：同 code 与 message 去重，最多保留 5 条", () => {
    const reported = (code: string, message: string) =>
      hostEvent("error.reported", { code, message, severity: "recoverable", source: "sidecar" });
    desktopStore.getState().applyEvents([
      reported("backend_disconnected", "Python Sidecar 已断开，正在重连…"),
      reported("backend_disconnected", "Python Sidecar 已断开，正在重连…"),
      reported("voice.tts", "语音合成失败：服务无响应"),
      reported("dialogue.deepseek", "请求超时"),
    ]);
    let state = desktopStore.getState();
    // 非 fatal 错误同样写入 error 字段
    expect(state.toasts).toHaveLength(3);
    expect(state.toasts[0].kind).toBe("warning");
    expect(state.error).toBe("请求超时");

    // 超过 5 条只保留最新 5 条（最早的 Sidecar 断开被挤出）
    desktopStore.getState().applyEvents([
      reported("a", "错误五"),
      reported("b", "错误六"),
      reported("c", "错误七"),
    ]);
    state = desktopStore.getState();
    expect(state.toasts).toHaveLength(5);
    expect(state.toasts.map((toast) => toast.text)).toEqual([
      "语音合成失败：服务无响应",
      "请求超时",
      "错误五",
      "错误六",
      "错误七",
    ]);

    // dismissToast 移除指定 Toast
    desktopStore.getState().dismissToast("c:错误七");
    expect(desktopStore.getState().toasts.map((toast) => toast.text)).toEqual([
      "语音合成失败：服务无响应",
      "请求超时",
      "错误五",
      "错误六",
    ]);
  });

  it("error.reported 的 info 级别以 info 通知进 Toast，不影响连接状态", () => {
    desktopStore
      .getState()
      .applyEvents([
        hostEvent("error.reported", { code: "voice.asr", message: "麦克风不可用", severity: "info" }),
      ]);
    const state = desktopStore.getState();
    expect(state.toasts).toMatchObject([{ kind: "info", text: "麦克风不可用" }]);
    expect(state.status).toBe("ready");
  });

  it.each([
    [
      "Sidecar 启动失败（severity=fatal）",
      event(
        "error.reported",
        {
          code: "startup_error",
          message: "启动失败：数据库被占用",
          severity: "fatal",
          fatal: true,
          source: "sidecar",
        },
        0,
      ),
      "启动失败：数据库被占用",
    ],
    [
      "宿主报告的非法输出（不带 severity 与序号）",
      hostEvent("error.reported", {
        code: "invalid_sidecar_json",
        message: "Sidecar 输出不是合法 JSON",
      }),
      "Sidecar 输出不是合法 JSON",
    ],
  ])("首次引导期间，%s整屏接管，不进 Toast，也不触发重新同步", (_name, reported, message) => {
    // 启动失败时还没有快照：错误到达时窗口仍处于首次引导。
    desktopStore.setState(desktopStore.getInitialState(), true);
    desktopStore.getState().applyEvents([reported]);

    const state = desktopStore.getState();
    expect(state.status).toBe("error");
    expect(state.error).toBe(message);
    expect(state.toasts).toEqual([]);
    expect(state.needsBootstrap).toBe(false);
  });

  it("Sidecar 编号的 error.reported 推进序号，下一条事件照常应用，不触发重新同步", () => {
    const failure = "远程服务启动失败（端口 8765）：地址已在使用";
    desktopStore.getState().hydrate({ ...singleProjectSnapshot(), stream_id: "s1", sequence: 2 });
    desktopStore.getState().applyEvents([
      {
        ...event(
          "error.reported",
          { code: "serve_start_failed", message: failure, severity: "error", fatal: false, source: "sidecar" },
          3,
        ),
        stream_id: "s1",
      },
      assistantMessage(4, "after-error", "s1"),
    ]);

    const state = desktopStore.getState();
    expect(state).toMatchObject({ needsBootstrap: false, resyncing: false, lastSequence: 4 });
    expect(state.messagesById["after-error"]?.text).toBe("消息 4");
    expect(state.toasts.map((toast) => toast.text)).toEqual([failure]);
  });

  it("account.changed 水合当前账号与账号列表", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "account.changed",
        sequence: 1,
        payload: {
          account: {
            account_id: "alice-1",
            username: "alice",
            display_name: "爱丽丝",
            avatar: "",
            last_login_at: null,
            onboarding_complete: false,
            theme: "dark",
          },
          accounts: [
            {
              account_id: "default-local",
              username: "default",
              display_name: "默认账号",
              avatar: "",
              last_login_at: null,
              onboarding_complete: false,
              theme: "dark",
              is_last_login: false,
            },
            {
              account_id: "alice-1",
              username: "alice",
              display_name: "爱丽丝",
              avatar: "",
              last_login_at: null,
              onboarding_complete: false,
              theme: "dark",
              is_last_login: true,
            },
          ],
        },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.currentAccountId).toBe("alice-1");
    expect(state.currentAccount?.username).toBe("alice");
    expect(state.accounts).toHaveLength(2);
    expect(state.accounts.find((item) => item.is_last_login)?.account_id).toBe("alice-1");
  });

  it("state.snapshot 水合后按快照序号继续应用后续事件", () => {
    const pending = createMockScenario("onboarding-pending").snapshot;
    desktopStore.getState().hydrate({ ...pending, sequence: 0 });
    const pendingAccount = pending.current_account!;
    const completedAccount = { ...pendingAccount, onboarding_complete: true };

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "account.changed",
        sequence: 1,
        payload: { account: pendingAccount, accounts: pending.accounts },
      },
      {
        kind: "event",
        event: "state.snapshot",
        sequence: 2,
        payload: { ...pending, sequence: 2 },
      },
      {
        kind: "event",
        event: "account.changed",
        sequence: 3,
        payload: {
          account: completedAccount,
          accounts: pending.accounts.map((item) =>
            item.account_id === completedAccount.account_id
              ? { ...item, onboarding_complete: true }
              : item,
          ),
        },
      },
    ]);

    expect(desktopStore.getState().currentAccount?.onboarding_complete).toBe(true);
    expect(desktopStore.getState().lastSequence).toBe(3);
    expect(desktopStore.getState().needsBootstrap).toBe(false);
  });

  it("project.changed 只带项目字段时沿用已知的会话列表", () => {
    const { conversations, ...projectFields } = desktopStore.getState().projectsById["project-1"];
    expect(conversations.length).toBeGreaterThan(0);

    // project.update_settings 广播的 project.changed 不带 conversations。
    desktopStore.getState().applyEvents([
      event(
        "project.changed",
        { project: { ...projectFields, name: "改名后的项目", approval_mode: "review", reasoning_effort: "max" } },
        1,
      ),
    ]);

    const state = desktopStore.getState();
    expect(state.projectsById["project-1"]).toMatchObject({
      name: "改名后的项目",
      approval_mode: "review",
      reasoning_effort: "max",
      conversations,
    });
    expect(
      presentAppShell(state).navigation?.projects[0].conversations.map((item) => item.conversation_id),
    ).toEqual(conversations.map((item) => item.conversation_id));
  });

  it("conversation.changed 同步更新侧栏项目内的会话标题", () => {
    const projectId = "project-1";
    const conversation = desktopStore.getState().conversationsById["conv-1"];
    desktopStore.getState().applyEvents([
      event("conversation.changed", { conversation: { ...conversation, title: "正在整理项目介绍" } }, 1),
    ]);
    const state = desktopStore.getState();
    // 侧栏按 projectsById[].conversations 渲染
    expect(state.projectsById[projectId].conversations[0].title).toBe("正在整理项目介绍");
    expect(presentAppShell(state).navigation?.projects[0].conversations[0].title).toBe(
      "正在整理项目介绍",
    );
  });

  it("审批按钮锁定到 approval.resolved 到达，终态移出待审批队列", () => {
    desktopStore.getState().applyEvents([
      event(
        "approval.requested",
        {
          approval_id: "approval-1",
          conversation_id: "conv-1",
          task_id: "task-1",
          operation: {
            tool_kind: "shell",
            command: "pytest -q",
            paths: [],
            patch_file_count: null,
            summary: "运行测试",
          },
          reason: "需要审批",
        },
        1,
      ),
    ]);
    desktopStore.getState().setApprovalResolving("approval-1", true);
    expect(presentAppShell(desktopStore.getState()).approval.pending[0].resolving).toBe(true);

    // 手机端先应答，桌面收到的终态来自另一端。
    desktopStore.getState().applyEvents([
      event(
        "approval.resolved",
        {
          approval_id: "approval-1",
          conversation_id: "conv-1",
          task_id: "task-1",
          decision: "allow",
          resolved_by: "remote",
          actor: "user",
          request_reason: "需要审批",
          resolution_reason: null,
          resolved_at: "2026-08-13T00:00:00+00:00",
          error_code: null,
        },
        2,
      ),
    ]);
    expect(presentAppShell(desktopStore.getState()).approval.pending).toEqual([]);
    expect(desktopStore.getState().approvalResolvingById).toEqual({});
  });

  it("全局快照只替换当前聊天，保留本窗口其他已打开聊天的记录与搭档", () => {
    const scenario = createMockScenario("multi-pair");
    const baseSequence = scenario.snapshot.sequence;
    desktopStore.getState().hydrate(scenario.snapshot);
    desktopStore.getState().openConversationTab("conv-phainon");
    desktopStore.getState().applyEvents([
      event(
        "message.created",
        {
          message: message(
            "cached-phainon-message",
            "conv-phainon",
            "character",
            "character.speech",
            "应保留的白厄聊天记录",
          ),
        },
        baseSequence + 1,
      ),
    ]);

    // Sidecar 的全局快照仍指向流萤，但本窗口正聚焦白厄标签。
    desktopStore.getState().hydrate({
      ...scenario.snapshot,
      messages: scenario.snapshot.messages.filter(
        (item) => item.conversation_id === scenario.snapshot.current_conversation_id,
      ),
      tool_runs: scenario.snapshot.tool_runs.filter(
        (run) => run.conversation_id === scenario.snapshot.current_conversation_id,
      ),
      turns: scenario.snapshot.turns.filter(
        (turn) => turn.conversation_id === scenario.snapshot.current_conversation_id,
      ),
      queue_items: scenario.snapshot.queue_items.filter(
        (item) => item.conversation_id === scenario.snapshot.current_conversation_id,
      ),
      sequence: baseSequence + 2,
    });
    const state = desktopStore.getState();
    expect(state.messageIdsByConversation["conv-phainon"]).toContain(
      "cached-phainon-message",
    );
    expect(state.messagesById["cached-phainon-message"]?.text).toBe(
      "应保留的白厄聊天记录",
    );
    expect(state.activeConversationId).toBe("conv-phainon");
    expect(state.pair?.pair_id).toBe("phainon_ancient_machine");
  });

  it("新连接代次先暂存业务事件，快照水合后按序重放", () => {
    desktopStore.getState().hydrate({ ...singleProjectSnapshot(), stream_id: "old-stream", sequence: 2 });
    desktopStore.getState().applyEvents([
      {
        ...hostEvent("connection.status", { status: "connected", stream_id: "new-stream" }),
        stream_id: "new-stream",
      },
      assistantMessage(3, "stream-msg-3", "new-stream"),
      assistantMessage(4, "stream-msg-4", "new-stream"),
    ]);
    let state = desktopStore.getState();
    expect(state.streamId).toBe("new-stream");
    expect(state.needsBootstrap).toBe(true);
    expect(state.messagesById["stream-msg-3"]).toBeUndefined();

    desktopStore.getState().applyEvents([snapshotEvent(2, "new-stream")]);
    state = desktopStore.getState();
    expect(state.status).toBe("ready");
    expect(state.needsBootstrap).toBe(false);
    expect(state.messagesById["stream-msg-3"]?.text).toBe("消息 3");
    expect(state.messagesById["stream-msg-4"]?.text).toBe("消息 4");
  });

  it("旧连接代次的快照不覆盖新代次状态", () => {
    desktopStore.getState().hydrate({ ...singleProjectSnapshot(), stream_id: "new-stream", sequence: 2 });
    desktopStore.getState().applyEvents([snapshotEvent(5, "old-stream")]);
    const state = desktopStore.getState();
    expect(state.streamId).toBe("new-stream");
    expect(state.status).toBe("ready");
    expect(state.lastSequence).toBe(2);
  });

  it("同代次重复序号的事件直接丢弃", () => {
    desktopStore.getState().hydrate({ ...singleProjectSnapshot(), stream_id: "s1", sequence: 2 });
    desktopStore.getState().applyEvents([
      assistantMessage(3, "dup-msg", "s1", "第一次"),
      assistantMessage(3, "dup-msg", "s1", "重复"),
    ]);
    expect(desktopStore.getState().messagesById["dup-msg"]?.text).toBe("第一次");
    expect(desktopStore.getState().lastSequence).toBe(3);
  });

  it("序号缺口时界面保持可用并重新同步，快照核对后重放暂存事件", () => {
    desktopStore.getState().hydrate({ ...singleProjectSnapshot(), stream_id: "s1", sequence: 2 });
    desktopStore.getState().applyEvents([assistantMessage(4, "gap-msg-4", "s1")]);
    let state = desktopStore.getState();
    expect(state).toMatchObject({
      status: "ready",
      needsBootstrap: true,
      resyncing: true,
      lastSequence: 2,
    });
    expect(state.messagesById["gap-msg-4"]).toBeUndefined();

    desktopStore.getState().applyEvents([assistantMessage(5, "gap-msg-5", "s1")]);
    expect(desktopStore.getState().eventBuffer.map((item) => item.sequence)).toEqual([4, 5]);

    desktopStore.getState().applyEvents([snapshotEvent(3, "s1")]);
    state = desktopStore.getState();
    expect(state.needsBootstrap).toBe(false);
    expect(state.resyncing).toBe(false);
    expect(state.messagesById["gap-msg-4"]?.text).toBe("消息 4");
    expect(state.messagesById["gap-msg-5"]?.text).toBe("消息 5");
  });

  it("message.status_changed 携带完整消息时先于 message.created 到达也能落库", () => {
    const early = {
      ...message("early-status", "conv-1", "user", "user.text", "状态先到"),
      status: "received" as const,
    };
    desktopStore.getState().applyEvents([event("message.status_changed", { message: early }, 1)]);
    const state = desktopStore.getState();
    expect(state.messagesById["early-status"]).toEqual(early);
    expect(state.messageIdsByConversation["conv-1"]).toContain("early-status");
  });

  it("message.status_changed 缺少必要字段时重新同步快照，不静默丢弃", () => {
    desktopStore
      .getState()
      .applyEvents([event("message.status_changed", { message: { message_id: "incomplete" } }, 1)]);
    const state = desktopStore.getState();
    expect(state.needsBootstrap).toBe(true);
    expect(state.messagesById["incomplete"]).toBeUndefined();
  });

  it("state.snapshot 水合保留 Toast 与配置缓存", () => {
    desktopStore.getState().pushToast({
      id: "keep:toast",
      kind: "error",
      text: "保留我",
      hasDetails: true,
    });
    desktopStore.getState().setConfigSnapshot({ engine: "deepseek" });
    desktopStore.getState().hydrate({
      ...createMockScenario("single-project").snapshot,
      sequence: 5,
    });
    const state = desktopStore.getState();
    expect(state.toasts).toHaveLength(1);
    expect(state.toasts[0]?.text).toBe("保留我");
    expect(state.configSnapshot).toEqual({ engine: "deepseek" });
  });

  it("一个会话的活动任务不让本窗口的另一会话显示忙碌", () => {
    const base = singleProjectSnapshot();
    const project = base.projects[0];
    const otherConversation = {
      ...project.conversations[0],
      conversation_id: "conv-b",
      title: "B 会话",
    };
    desktopStore.getState().hydrate({
      ...base,
      projects: [{ ...project, conversations: [otherConversation] }],
      current_conversation_id: "conv-b",
      current_conversation: otherConversation,
      sequence: 3,
    });
    const task = {
      project_id: "project-1",
      conversation_id: "conv-1",
      task_id: "task-a",
      engine_turn_id: null,
    };
    desktopStore.getState().applyEvents([
      event(
        "task.busy_changed",
        { conversation_id: "conv-1", busy: true, active_task: task, active_tasks: [task] },
        4,
      ),
    ]);
    expect(desktopStore.getState().busy).toBe(false);
    expect(desktopStore.getState().activeTask).toBeNull();
    expect(desktopStore.getState().activeTasksByConversation["conv-1"]).toEqual(task);
  });

  it("conversation.open 装载后重放请求期间到达的新消息，同序号的重复事件只应用一次", () => {
    const base = singleProjectSnapshot();
    const conversation = base.current_conversation;
    const live = message(
      "live-message",
      conversation.conversation_id,
      "character",
      "character.speech",
      "请求期间的新消息",
    );
    const duplicate = message(
      "duplicate-ignored",
      conversation.conversation_id,
      "character",
      "character.speech",
      "同序号重复",
    );
    desktopStore.setState({ lastSequence: 30 });
    desktopStore.getState().hydrateConversationView(
      {
        conversation,
        project: base.current_project,
        pair: base.pair,
        messages: [],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
        sequence: 10,
        stream_id: "stream-current",
      },
      [
        { ...event("message.created", { message: live }, 11), stream_id: "stream-current" },
        { ...event("message.created", { message: duplicate }, 11), stream_id: "stream-current" },
      ],
    );

    expect(desktopStore.getState().lastSequence).toBe(30);
    expect(desktopStore.getState().messagesById["duplicate-ignored"]).toBeUndefined();
    expect(desktopStore.getState().messagesById["live-message"]).toEqual(live);
  });

  it("conversation.open 结果已包含的 message.delta 经常驻订阅到达时不重复追加", () => {
    const base = singleProjectSnapshot();
    const conversation = base.current_conversation;
    desktopStore.setState({ lastSequence: 10, streamId: "stream-current" });
    const delta = (sequence: number, text: string): DesktopEvent => ({
      kind: "event",
      event: "message.delta",
      stream_id: "stream-current",
      sequence,
      payload: {
        message_id: "streaming",
        conversation_id: conversation.conversation_id,
        source: "character",
        kind: "character.speech",
        delta: text,
        timeline_order: 1,
      },
    });
    desktopStore.getState().hydrateConversationView(
      {
        conversation,
        project: base.current_project,
        pair: base.pair,
        messages: [
          {
            message_id: "streaming",
            conversation_id: conversation.conversation_id,
            pair_id: conversation.pair_id,
            engine_turn_id: null,
            source: "character",
            kind: "character.speech",
            text: "你好",
            payload: {},
            tts_eligible: true,
            created_at: "2026-08-22T00:00:00Z",
            timeline_order: 1,
            streaming: true,
          },
        ],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
        sequence: 12,
        stream_id: "stream-current",
      },
      [delta(12, "好")],
    );
    // 序号 11、12 已包含在装载结果里，13 是之后的新分片
    desktopStore.getState().applyEvents([delta(11, "你"), delta(12, "好"), delta(13, "呀")]);

    const state = desktopStore.getState();
    expect(state.messagesById["streaming"]?.text).toBe("你好呀");
    expect(state.lastSequence).toBe(13);
    expect(state.needsBootstrap).toBe(false);
  });

  it("切换账号清空上一账号的聊天、审批、角色卡与配对状态", async () => {
    const backend = new MockDesktopBackend("approval-request");
    const { actions, loadBootstrap } = createActionController(backend);
    const unsubscribe = backend.subscribe((item) => desktopStore.getState().applyEvents([item]));
    try {
      await loadBootstrap();
      await actions.openCharacterLibrary();
      await actions.openCharacterCreate("card-saved-002");
      await actions.issuePairingCode();
      await actions.listRemoteDevices();
      backend.emit("serve.started", { host: "192.168.1.2", port: 8765, mode: "lan", tls: false });
      const before = desktopStore.getState();
      expect(Object.keys(before.messagesById).length).toBeGreaterThan(0);
      expect(before.approvals).toHaveLength(1);
      expect(before.voice.supported).toBe(true);
      expect(before.characterLibrary.loaded).toBe(true);
      expect(before.characterCreate.cardId).toBe("card-saved-002");
      expect(before.remotePairing.code).not.toBeNull();
      expect(before.remotePairing.devices.length).toBeGreaterThan(0);
      expect(before.remotePairing.serveAddress).not.toBeNull();

      // 退出登录回到默认账号，Sidecar 广播 account.changed。
      await backend.request({ kind: "request", id: "logout", method: "account.logout", params: {} });

      const state = desktopStore.getState();
      expect(state.currentAccountId).toBe("default-local");
      expect(state.accountGeneration).toBe(before.accountGeneration + 1);
      expect(state.messagesById).toEqual({});
      expect(state.approvals).toEqual([]);
      expect(state.pair).toBeNull();
      expect(state.pairs).toEqual([]);
      expect(state.voice.supported).toBe(false);
      expect(state.mainView).toBe("chat");
      expect(state.characterLibrary).toEqual({
        cards: [],
        loading: false,
        error: null,
        loaded: false,
      });
      expect(state.characterCreate).toMatchObject({ cardId: null, card: null });
      expect(state.remotePairing).toMatchObject({
        code: null,
        devices: [],
        serveAddress: null,
      });
    } finally {
      unsubscribe();
    }
  });

  it("切换账号后忽略旧账号迟到的音色进度事件", () => {
    const current = desktopStore.getState().currentAccount!;
    const accountB = { ...current, account_id: "account-b", username: "b", display_name: "账号 B" };
    const provisionChanged = (sequence: number, accountId: string, state: string, voiceId: string | null) =>
      event(
        "voice.provision_changed",
        {
          account_id: accountId,
          speaker_id: "phainon",
          state,
          completed: state === "completed" ? 1 : 0,
          total: 6,
          error: null,
          voice_id: voiceId,
        },
        sequence,
      );
    desktopStore.getState().applyEvents([
      event(
        "account.changed",
        { account: accountB, accounts: [{ ...accountB, is_last_login: true }] },
        1,
      ),
      provisionChanged(2, "demo-account", "completed", "voice-old"),
    ]);
    expect(desktopStore.getState().configSnapshot).toBeNull();

    desktopStore.getState().applyEvents([provisionChanged(3, "account-b", "creating", "voice-phainon")]);
    expect(desktopStore.getState().configSnapshot?.voice).toMatchObject({
      speakers: [{ speaker_id: "phainon", state: "creating", voice_id: "voice-phainon" }],
    });
  });

  it("voice.card_provision_changed 同步角色库中该卡的音色状态", async () => {
    const backend = new MockDesktopBackend("single-project");
    await createActionController(backend).actions.listCards();
    const cardState = (cardId: string) =>
      desktopStore.getState().characterLibrary.cards.find((card) => card.cardId === cardId)?.voiceState;
    expect(cardState("card-draft-001")).toBe("voice_unconfigured");

    desktopStore.getState().applyEvents([
      event(
        "voice.card_provision_changed",
        { card_id: "card-draft-001", state: "voice_ready", voice_id: "voice-abc", error: null },
        1,
      ),
    ]);

    expect(cardState("card-draft-001")).toBe("voice_ready");
  });

  it("voice.card_provision_changed 不改写创作页载入的整卡 JSON", async () => {
    const backend = new MockDesktopBackend("single-project");
    const { actions } = createActionController(backend);
    await actions.openCharacterCreate("card-saved-002");
    const loaded = (await actions.cardGet("card-saved-002")).card;
    expect(desktopStore.getState().characterCreate.card).toEqual(loaded);

    desktopStore.getState().applyEvents([
      event(
        "voice.card_provision_changed",
        { card_id: "card-saved-002", state: "voice_ready", voice_id: "voice-abc", error: null },
        1,
      ),
    ]);

    expect(desktopStore.getState().characterCreate.card).toEqual(loaded);
  });
});

describe("电源状态", () => {
  beforeEach(resetStore);

  /** Windows 上远程服务开启、AC 睡眠超时低于阈值时 power.get_status 的结果。 */
  function powerPayload(overrides: Partial<PowerStatusPayload> = {}): PowerStatusPayload {
    return {
      supported: true,
      platform: "win32",
      plan_name: "平衡",
      ac_sleep_timeout_seconds: 600,
      dc_sleep_timeout_seconds: 0,
      remote_serve_enabled: true,
      threshold_seconds: 900,
      at_risk: true,
      reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
      checked_at: "2026-09-02T10:00:00+08:00",
      warnings: [],
      ...overrides,
    };
  }

  const queryFailure = "读取电源状态失败：PowerGetActiveScheme 失败（错误码 5）：拒绝访问。";

  it.each([
    [
      "power.status_changed 事件",
      () => desktopStore.getState().applyEvents([event("power.status_changed", powerPayload(), 1)]),
    ],
    ["power.get_status 查询结果", () => desktopStore.getState().setPowerStatus(powerPayload())],
  ])("%s写入电源状态并清除上一次查询错误", (_source, receive) => {
    desktopStore.getState().setPowerError(queryFailure);
    receive();

    const state = desktopStore.getState();
    expect(state.powerStatus).toEqual(powerPayload());
    expect(state.powerError).toBeNull();
  });

  it("风险期内再次查询到风险时保留用户的关闭标记", () => {
    desktopStore.getState().setPowerStatus(powerPayload());
    desktopStore.getState().dismissPowerPrompt();

    // 打开设置页时 PowerStatusSection 挂载并重新查询，风险仍在
    desktopStore.getState().setPowerStatus(powerPayload({ checked_at: "2026-09-02T10:01:00+08:00" }));
    expect(desktopStore.getState().powerPromptDismissed).toBe(true);
  });

  it("查询失败如实记录原文，保留最近一次成功读取的状态", () => {
    desktopStore.getState().setPowerStatus(powerPayload());
    desktopStore.getState().setPowerError(queryFailure);

    const state = desktopStore.getState();
    expect(state.powerError).toBe(queryFailure);
    expect(state.powerStatus).toEqual(powerPayload());
  });
});

describe("摘要、记忆与聊天装载", () => {
  beforeEach(resetStore);

  /** summary.* 事件载荷（core.summary.summary_event_payload）；失败记录额外带 error_code 与 error。 */
  function summaryPayload(overrides: Record<string, unknown> = {}) {
    return {
      summary_id: "s1",
      conversation_id: "conv-1",
      status: "running",
      account_id: "demo-account",
      project_id: "project-1",
      pair_id: "phainon_ancient_machine",
      character_ref: "builtin:phainon",
      assistant_identity: "ancient_machine",
      covers_from_message_id: "message-1",
      covers_to_message_id: "message-2",
      covers_message_count: 2,
      provider: null,
      model: null,
      created_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-01T00:00:00+00:00",
      ...overrides,
    };
  }

  const failedSummary = summaryPayload({
    status: "failed",
    error_code: "summary_timeout",
    error: "provider timeout",
  });

  /** 服务端 _memory_payload：扁平五分量，按会话广播时带 conversation_id。 */
  function memoryPayload(overrides: Partial<MemoryWirePayload> = {}): MemoryWirePayload {
    return {
      memory_id: "mem-1",
      account_id: "acc-1",
      project_id: "project-1",
      pair_id: "phainon_ancient_machine",
      character_ref: "builtin:phainon",
      assistant_identity: "ancient_machine",
      content: { text: "用户喜欢安静的训练场" },
      status: "active",
      updated_at: "2026-01-01T00:00:00+00:00",
      conversation_id: "conv-1",
      ...overrides,
    };
  }

  const summaries = () => desktopStore.getState().summariesByConversation["conv-1"];

  it("摘要失败保留原始错误与覆盖区间，并留下重新生成目标", () => {
    desktopStore.getState().applyEvents([event("summary.started", summaryPayload(), 1)]);
    expect(summaries()).toMatchObject([{ summary_id: "s1", status: "running" }]);

    desktopStore.getState().applyEvents([event("summary.failed", failedSummary, 2)]);

    expect(summaries()).toMatchObject([
      {
        status: "failed",
        error_code: "summary_timeout",
        error: "provider timeout",
        covers_to_message_id: "message-2",
        content: null,
      },
    ]);
    expect(desktopStore.getState().summaryRegenerateTarget).toEqual({
      summary_id: "s1",
      conversation_id: "conv-1",
    });
  });

  it("重新生成完成后按 summary_id 覆盖失败记录并清除重新生成目标", () => {
    desktopStore.getState().applyEvents([
      event("summary.failed", failedSummary, 1),
      // summary.regenerate 广播的 summary.started 载荷是重新生成前的失败记录。
      event("summary.started", failedSummary, 2),
      event(
        "summary.completed",
        summaryPayload({ status: "completed", provider: "deepseek", model: "deepseek-chat" }),
        3,
      ),
    ]);

    expect(summaries()).toMatchObject([
      { summary_id: "s1", status: "completed", model: "deepseek-chat", error_code: null, error: null },
    ]);
    expect(desktopStore.getState().summaryRegenerateTarget).toBeNull();
  });

  it("memory.updated 按扁平载荷落库，作用域解码为嵌套 scope 并按会话归档", () => {
    desktopStore.getState().applyEvents([
      event("memory.updated", memoryPayload(), 1),
      event("memory.updated", memoryPayload({ memory_id: "mem-2", content: { text: "第二条" } }), 2),
    ]);

    const state = desktopStore.getState();
    expect(state.memories.map((item) => item.memory_id)).toEqual(["mem-1", "mem-2"]);
    expect(state.memoriesByConversation["conv-1"]).toEqual(state.memories);
    expect(state.memories[1].content).toEqual({ text: "第二条" });
    expect(state.memories[0].scope).toEqual({
      account_id: "acc-1",
      project_id: "project-1",
      pair_id: "phainon_ancient_machine",
      character_ref: "builtin:phainon",
      assistant_identity: "ancient_machine",
    });
  });

  it("memory.deleted 用服务端下发的删除记录覆盖同一条记忆", () => {
    desktopStore.getState().applyEvents([
      event("memory.updated", memoryPayload(), 1),
      event("memory.deleted", memoryPayload({ status: "deleted" }), 2),
    ]);

    const state = desktopStore.getState();
    expect(state.memories).toMatchObject([{ memory_id: "mem-1", status: "deleted" }]);
    expect(state.memoriesByConversation["conv-1"]).toEqual(state.memories);
  });

  it("聊天绑定的角色卡已删除时，服务端提示进 Toast 队列", () => {
    desktopStore.getState().applyEvents([
      event(
        "conversation.card_missing",
        {
          conversation_id: "conv-1",
          card_id: "card-x",
          message: "该聊天绑定的角色卡已被删除，本轮起回退为内置角色",
        },
        1,
      ),
    ]);
    const toast = desktopStore.getState().toasts.at(-1);
    expect(toast?.kind).toBe("warning");
    expect(toast?.id).toContain("card-x");
    expect(toast?.text).toBe("该聊天绑定的角色卡已被删除，本轮起回退为内置角色");
  });

  it("conversation.open 结果写入本会话的活动任务，聚焦后本窗口显示忙碌", () => {
    const snapshot = singleProjectSnapshot();
    const conversation = snapshot.current_conversation;
    const result: ConversationOpenResult = {
      conversation,
      project: snapshot.current_project,
      pair: snapshot.pair,
      messages: snapshot.messages,
      tool_runs: snapshot.tool_runs,
      turns: snapshot.turns,
      queue_items: [],
      active_task: {
        project_id: "project-1",
        conversation_id: conversation.conversation_id,
        task_id: "task-1",
        engine_turn_id: null,
      },
      sequence: 5,
      stream_id: snapshot.stream_id,
    };
    desktopStore.getState().hydrateConversationView(result);

    const state = desktopStore.getState();
    expect(state.activeTasksByConversation[conversation.conversation_id]?.task_id).toBe("task-1");
    expect(state.activeConversationId).toBe(conversation.conversation_id);
    expect(state.busy).toBe(true);
  });
});

describe("本地服务连接与远程接入地址", () => {
  beforeEach(resetStore);

  it("本地服务断开时连接记为断开，保留已加载内容并提示断连原因", () => {
    desktopStore.getState().applyEvents([
      hostEvent("connection.status", { status: "disconnected" }),
      hostEvent("error.reported", disconnectNotice),
    ]);

    const state = desktopStore.getState();
    expect(state).toMatchObject({
      status: "disconnected",
      needsBootstrap: false,
      error: disconnectNotice.message,
    });
    expect(state.toasts).toMatchObject([{ kind: "warning", text: disconnectNotice.message }]);
    // 已加载内容保留，界面不整屏接管
    expect(state.conversationsById["conv-1"]).toBeDefined();
    expect(state.messagesById["message-1"]).toBeDefined();
  });

  it("连接恢复后进入重新引导，并撤回「正在重连…」通知", () => {
    desktopStore.getState().applyEvents([
      hostEvent("connection.status", { status: "disconnected" }),
      hostEvent("error.reported", disconnectNotice),
      hostEvent("connection.status", { status: "connected" }),
    ]);

    const state = desktopStore.getState();
    expect(state).toMatchObject({ status: "booting", needsBootstrap: true, error: null });
    expect(state.toasts).toEqual([]);
  });

  it("连接恢复只撤回断连通知，其他错误继续留在队列里", () => {
    desktopStore.getState().applyEvents([
      hostEvent("connection.status", { status: "disconnected" }),
      hostEvent("error.reported", disconnectNotice),
      hostEvent("error.reported", {
        code: "voice.tts",
        message: "语音合成失败：服务无响应",
        severity: "recoverable",
      }),
      hostEvent("connection.status", { status: "connected" }),
    ]);

    const state = desktopStore.getState();
    expect(state.toasts.map((toast) => toast.text)).toEqual(["语音合成失败：服务无响应"]);
    expect(state.error).toBe("语音合成失败：服务无响应");
  });

  it.each([
    [
      "局域网地址",
      { host: "192.168.1.42", port: 8765, mode: "lan", tls: false },
      {
        serveAddress: { host: "192.168.1.42", port: 8765, mode: "lan", tls: false },
        servePort: 8765,
        serveUnavailableReason: null,
        serveFailure: null,
      },
    ],
    [
      "已监听但没有局域网地址（host=null）",
      { host: null, port: 8765, mode: "lan", tls: false, reason: "no_lan_address" },
      { serveAddress: null, servePort: 8765, serveUnavailableReason: "no_lan_address", serveFailure: null },
    ],
    [
      "缺少 port 的违规报文",
      { host: "192.168.1.99" },
      {
        serveAddress: null,
        serveUnavailableReason: null,
        serveFailure: "远程服务地址报文不符合协议：缺少 port",
      },
    ],
  ])("serve.started 上报%s时整体替换上一次的接入地址", (_name, payload, expected) => {
    desktopStore.getState().applyEvents([
      event("serve.started", { host: "10.0.0.2", port: 9000, mode: "lan", tls: false }, 1),
      event("serve.started", payload, 2),
    ]);

    expect(desktopStore.getState().remotePairing).toMatchObject(expected);
  });

  it("远程服务启动失败的报文进远程设备页，重启本地服务后成功的 serve.started 清除它", () => {
    const failure = "远程服务启动失败（端口 8765）：[WinError 10048] 地址已在使用";
    desktopStore.getState().applyEvents([
      {
        ...event(
          "error.reported",
          { code: "serve_start_failed", message: failure, severity: "error", fatal: false, source: "sidecar" },
          1,
        ),
        stream_id: "stream-1",
      },
    ]);
    expect(desktopStore.getState().remotePairing.serveFailure).toBe(failure);

    // 重启本地服务：新连接代次引导完成后，新进程上报监听成功。
    desktopStore.getState().applyEvents([
      {
        ...hostEvent("connection.status", { status: "connected", stream_id: "stream-2" }),
        stream_id: "stream-2",
      },
    ]);
    desktopStore.getState().hydrate({ ...singleProjectSnapshot(), stream_id: "stream-2", sequence: 3 });
    desktopStore.getState().applyEvents([
      {
        ...event("serve.started", { host: "192.168.1.7", port: 8765, mode: "lan", tls: false }, 4),
        stream_id: "stream-2",
      },
    ]);
    expect(desktopStore.getState().remotePairing).toMatchObject({
      serveFailure: null,
      serveAddress: { host: "192.168.1.7", port: 8765 },
      serveUnavailableReason: null,
    });
  });

  it("backend.ready 记录 Sidecar 自报的运行模式并进入新连接的引导", () => {
    desktopStore
      .getState()
      .applyEvents([event("backend.ready", { pid: 4321, demo: true, mode_source: "explicit_demo" }, 1)]);

    const state = desktopStore.getState();
    expect(state.backendInfo).toEqual({ pid: 4321, demo: true, modeSource: "explicit_demo" });
    expect(state.status).toBe("booting");
    expect(state.needsBootstrap).toBe(true);
  });
});
