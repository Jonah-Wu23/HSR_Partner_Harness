import { beforeEach, describe, expect, it } from "vitest";

import type { ConversationRecord, DesktopEvent, DesktopSnapshot, Message } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { presentAppShell, selectConversationCharacterIdentity } from "./presenters";
import { desktopStore } from "../stores/desktopStore";

/** 以指定场景水合 store，返回当前 ViewModel。 */
function presentScenario(name: "single-project" | "gate-default" | "onboarding-pending") {
  desktopStore.getState().hydrate(createMockScenario(name).snapshot);
  return presentAppShell(desktopStore.getState());
}

describe("AppShell 视图模型投影", () => {
  beforeEach(() => {
    desktopStore.setState(desktopStore.getInitialState(), true);
    desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
  });

  it("queueItems：未撤回项按 position 排序，摘要单行截断，position 从 1 开始", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "queue.changed",
        sequence: 1,
        payload: {
          conversation_id: "conv-1",
          items: [
            {
              queue_item_id: "q-1",
              account_id: "",
              conversation_id: "conv-1",
              target: "assistant",
              text: "帮我跑一遍全部测试并整理失败原因，然后给出后续修复建议",
              intent: "followup",
              position: 0,
              status: "queued",
              created_at: "2026-08-11T00:00:00+00:00",
              source_message_id: null,
            },
            {
              queue_item_id: "q-2",
              account_id: "",
              conversation_id: "conv-1",
              target: "character",
              text: "继续",
              intent: "followup",
              position: 1,
              status: "queued",
              created_at: "2026-08-11T00:00:00+00:00",
              source_message_id: null,
            },
            {
              queue_item_id: "q-3",
              account_id: "",
              conversation_id: "conv-1",
              target: "character",
              text: "这条已撤回",
              intent: "steer",
              position: 2,
              status: "withdrawn",
              created_at: "2026-08-11T00:00:00+00:00",
              source_message_id: null,
            },
          ],
        },
      },
    ]);
    const { queueItems } = presentAppShell(desktopStore.getState());
    expect(queueItems).toHaveLength(2);
    expect(queueItems[0]).toMatchObject({
      queueItemId: "q-1",
      target: "assistant",
      summary: "帮我跑一遍全部测试并整理失败原因，然后给出后续修…", // 超 24 字截断加省略号
      position: 1,
      // 会话没有活动任务时排队项等待派发
      waitingFor: "等待派发",
      intent: "followup",
    });
    expect(queueItems[1]).toMatchObject({ queueItemId: "q-2", summary: "继续", position: 2 });
  });

  it("queueItems：waitingFor 区分执行中、等待当前回复与队列顺序", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "task.busy_changed",
        sequence: 1,
        payload: {
          busy: true,
          active_tasks: [
            {
              project_id: "p1",
              conversation_id: "conv-1",
              task_id: "task-1",
              engine_turn_id: null,
            },
          ],
        },
      },
      {
        kind: "event",
        event: "queue.changed",
        sequence: 2,
        payload: {
          conversation_id: "conv-1",
          items: [
            {
              queue_item_id: "q-run",
              account_id: "",
              conversation_id: "conv-1",
              target: "character",
              text: "正在执行",
              intent: "followup",
              position: 0,
              status: "processing",
              created_at: "2026-08-11T00:00:00+00:00",
              source_message_id: null,
            },
            {
              queue_item_id: "q-first",
              account_id: "",
              conversation_id: "conv-1",
              target: "character",
              text: "队首等待",
              intent: "followup",
              position: 1,
              status: "queued",
              created_at: "2026-08-11T00:00:00+00:00",
              source_message_id: null,
            },
            {
              queue_item_id: "q-second",
              account_id: "",
              conversation_id: "conv-1",
              target: "character",
              text: "队尾等待",
              intent: "followup",
              position: 2,
              status: "queued",
              created_at: "2026-08-11T00:00:00+00:00",
              source_message_id: null,
            },
          ],
        },
      },
    ]);
    const { queueItems } = presentAppShell(desktopStore.getState());
    expect(queueItems[0]).toMatchObject({ queueItemId: "q-run", waitingFor: "执行中" });
    // processing 项占据队首，后续 queued 项等待的是“当前回复 + 前面各项”。
    expect(queueItems[1]).toMatchObject({
      queueItemId: "q-first",
      waitingFor: "等待当前回复及前面 1 项",
    });
    expect(queueItems[2]).toMatchObject({
      queueItemId: "q-second",
      waitingFor: "等待当前回复及前面 2 项",
    });
  });

  it("delegation：只有角色委派消息形成委派卡，状态按消息与活动任务展示运行或完成", () => {
    // 场景里只有普通用户消息
    expect(presentAppShell(desktopStore.getState()).workspace?.delegation).toBeNull();

    const event = (sequence: number, payload: Record<string, unknown>): DesktopEvent => ({
      kind: "event",
      event: "message.created",
      sequence,
      payload,
    });
    desktopStore.getState().applyEvents([
      event(1, {
        message: {
          message_id: "delegation-1",
          conversation_id: "conv-1",
          pair_id: "phainon_ancient_machine",
          engine_turn_id: null,
          source: "user",
          kind: "user.text",
          text: "帮我读一下项目结构",
          payload: {},
          tts_eligible: false,
          created_at: "2026-08-11T00:00:00+00:00",
          target: "assistant",
          origin: "character_delegation",
          delegation_id: "task-9",
          status: "done",
        },
      }),
    ]);
    // 无 activeTask → completed
    let vm = presentAppShell(desktopStore.getState());
    expect(vm.workspace?.delegation).toMatchObject({
      delegationId: "task-9",
      fromName: "白厄",
      summary: "帮我读一下项目结构",
      status: "completed",
    });

    // 有 activeTask → running
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "task.busy_changed",
        sequence: 2,
        payload: {
          busy: true,
          active_task: {
            project_id: "project-1",
            conversation_id: "conv-1",
            task_id: "task-9",
            engine_turn_id: null,
          },
          active_tasks: [
            {
              project_id: "project-1",
              conversation_id: "conv-1",
              task_id: "task-9",
              engine_turn_id: null,
            },
          ],
        },
      },
    ]);
    vm = presentAppShell(desktopStore.getState());
    expect(vm.workspace?.delegation?.status).toBe("running");
  });

  it("delegation：委派消息失败时委派卡显示失败", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "message.created",
        sequence: 1,
        payload: {
          message: {
            message_id: "delegation-failed",
            conversation_id: "conv-1",
            pair_id: "phainon_ancient_machine",
            engine_turn_id: null,
            source: "user",
            kind: "user.text",
            text: "帮我检查项目",
            payload: { error: "古代机械未返回最终回复" },
            tts_eligible: false,
            created_at: "2026-08-11T00:00:00+00:00",
            target: "assistant",
            origin: "character_delegation",
            delegation_id: "task-failed",
            status: "processing",
          },
        },
      },
      {
        kind: "event",
        event: "message.status_changed",
        sequence: 2,
        payload: {
          message: {
            message_id: "delegation-failed",
            conversation_id: "conv-1",
            pair_id: "phainon_ancient_machine",
            engine_turn_id: null,
            source: "user",
            kind: "user.text",
            text: "帮我检查项目",
            payload: { error: "古代机械未返回最终回复" },
            tts_eligible: false,
            created_at: "2026-08-11T00:00:00+00:00",
            target: "assistant",
            origin: "character_delegation",
            delegation_id: "task-failed",
            status: "failed",
          },
        },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).workspace?.delegation?.status).toBe("failed");
  });

  it("双空间归属：user+target=assistant 与 assistant/tool 归工作台，其余归角色区", () => {
    const event = (sequence: number, payload: Record<string, unknown>): DesktopEvent => ({
      kind: "event",
      event: "message.created",
      sequence,
      payload,
    });
    const message = (id: string, source: string, target: string | null): Record<string, unknown> => ({
      message_id: id,
      conversation_id: "conv-1",
      pair_id: "phainon_ancient_machine",
      engine_turn_id: null,
      source,
      kind:
        source === "user"
          ? "user.text"
          : source === "character"
            ? "character.speech"
            : "assistant.natural_language",
      text: `内容 ${id}`,
      payload: {},
      tts_eligible: false,
      created_at: "2026-08-11T00:00:00+00:00",
      target,
      origin: "user",
      delegation_id: null,
    });
    desktopStore.getState().applyEvents([
      event(1, { message: message("m-user-chat", "user", "character") }),
      event(2, { message: message("m-user-work", "user", "assistant") }),
      event(3, { message: message("m-character", "character", null) }),
      event(4, { message: message("m-system", "system", null) }),
      event(5, { message: message("m-assistant", "assistant", null) }),
      event(6, { message: message("m-tool", "tool", null) }),
    ]);
    const vm = presentAppShell(desktopStore.getState());
    const characterIds = vm.workspace!.character.messages.map((item) => item.message_id);
    const assistantIds = vm.workspace!.assistant.messages.map((item) => item.message_id);
    // 角色区：user+target=character、character、system
    expect(characterIds).toEqual(
      expect.arrayContaining(["m-user-chat", "m-character", "m-system"]),
    );
    // 工作台：user+target=assistant、assistant、tool
    expect(assistantIds).toEqual(
      expect.arrayContaining(["m-user-work", "m-assistant", "m-tool"]),
    );
    // 两条过滤规则互斥：任何消息不得同时出现在两个空间
    expect(characterIds.filter((id) => assistantIds.includes(id))).toEqual([]);
  });

  it.each([
    [
      "playing",
      2,
      null,
      { status: "playing", speaker: "character", speakerName: "白厄", queuedCount: 2 },
    ],
    ["synthesizing", 3, null, { status: "synthesizing", queuedCount: 3 }],
    [
      "failed",
      0,
      "语音合成失败：服务无响应",
      { status: "failed", errorText: "语音合成失败：服务无响应" },
    ],
    ["idle", 0, null, null],
  ])("voiceMiniPlayer：tts=%s 时的播放条", (tts, speechQueueLength, error, expected) => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "voice.state_changed",
        sequence: 1,
        payload: { voice: { tts, speech_queue_len: speechQueueLength, error } },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).voiceMiniPlayer).toEqual(
      expected === null ? null : expect.objectContaining(expected),
    );
  });

  it.each([
    ["gate-default", true, false],
    ["single-project", false, false],
    ["onboarding-pending", false, true],
  ] as const)("%s 场景下显示账号门=%s、首次引导=%s", (scenario, gate, onboarding) => {
    const vm = presentScenario(scenario);
    expect(vm.accountGate !== null).toBe(gate);
    expect(vm.onboarding).toBe(onboarding);
  });

  it("accountGate：默认账号进账号门时列出全部账号并标出上次登录", () => {
    const accounts = presentScenario("gate-default").accountGate?.accounts ?? [];
    expect(accounts).toHaveLength(2);
    expect(accounts.find((item) => item.isLastLogin)?.accountId).toBe("default-local");
  });

  it("onboarding：account.changed 带回引导完成后关闭首次引导", () => {
    presentScenario("onboarding-pending");
    const account = desktopStore.getState().currentAccount!;
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "account.changed",
        sequence: 1,
        payload: {
          account: { ...account, onboarding_complete: true },
          accounts: desktopStore
            .getState()
            .accounts.map((item) =>
              item.account_id === account.account_id ? { ...item, onboarding_complete: true } : item,
            ),
        },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).onboarding).toBe(false);
  });

  it("settings：configSnapshot 映射四页视图；无快照给默认空值", () => {
    const vm = presentAppShell(desktopStore.getState());
    // 无 configSnapshot：默认空值 + 初值 idle
    expect(vm.settings.model).toEqual({
      provider: "",
      model: "",
      baseUrl: "",
      apiKeyMasked: "",
      reasoningEffort: "auto",
      // 后端没上报 provider_supported 时不算不可用，也不编造不可用文案
      providerSupported: true,
      providerUnavailable: null,
    });
    expect(vm.settings.modelTest).toEqual({ state: "idle" });
    expect(vm.settings.voicePreview).toEqual({ state: "idle" });

    desktopStore.getState().setConfigSnapshot({
      engine: "deepseek",
      dialogue: {
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
        api_key_masked: "sk-d…1234",
        reasoning_effort: "medium",
        provider_supported: true,
        provider_unavailable: null,
      },
      voice: {
        enabled: "true",
        assistant_voice_enabled: "false",
        base_url: "https://dashscope.aliyuncs.com/api/v1",
        api_key_masked: "sk-v…5678",
        asr_model: "qwen-audio-3.0-asr-flash-streaming",
        tts_model: "qwen-audio-3.0-tts-flash",
        character_voice: "longxiaoyu",
        character_voice_name: "白厄",
        assistant_voice: "longxiaoyu",
        assistant_voice_name: "神秘的古代机械",
        vad_enabled: "true",
      },
    });
    const mapped = presentAppShell(desktopStore.getState());
    expect(mapped.settings.model).toMatchObject({
      provider: "deepseek",
      model: "deepseek-chat",
      apiKeyMasked: "sk-d…1234",
      reasoningEffort: "medium",
      providerSupported: true,
      providerUnavailable: null,
    });
    expect(mapped.settings.voice).toMatchObject({
      enabled: true,
      assistantVoiceEnabled: false,
      characterVoiceId: "longxiaoyu",
      characterVoiceName: "白厄",
      assistantVoiceId: "longxiaoyu",
      assistantVoiceName: "神秘的古代机械",
      vadEnabled: true,
    });
    expect(mapped.settings.account.displayName).toBe("演示账号");
  });

  it("settings：历史 openai_oauth 按后端 provider_supported/provider_unavailable 投影", () => {
    desktopStore.getState().setConfigSnapshot({
      dialogue: {
        provider: "openai_oauth",
        model: "gpt-5.6-sol",
        base_url: "https://api.openai.com/v1",
        api_key_masked: "",
        reasoning_effort: "auto",
        provider_supported: false,
        provider_unavailable: {
          code: "provider_unavailable",
          message: "该供应商不可用，请重新选择 DeepSeek 或 OpenAI 兼容 API。",
        },
      },
    });
    expect(presentAppShell(desktopStore.getState()).settings.model).toMatchObject({
      provider: "openai_oauth",
      providerSupported: false,
      providerUnavailable: {
        code: "provider_unavailable",
        message: "该供应商不可用，请重新选择 DeepSeek 或 OpenAI 兼容 API。",
      },
    });

    // 后端未给文案时不编造替代文案，也不改变不可用判定
    desktopStore.getState().setConfigSnapshot({
      dialogue: { provider: "openai_oauth", provider_supported: false, provider_unavailable: null },
    });
    expect(presentAppShell(desktopStore.getState()).settings.model).toMatchObject({
      providerSupported: false,
      providerUnavailable: null,
    });
  });

  it("多搭档：搭档目录完整，当前搭档与设置页音色跟随本窗口激活标签", () => {
    desktopStore.getState().hydrate(createMockScenario("multi-pair").snapshot);
    const vm = presentAppShell(desktopStore.getState());

    expect(vm.navigation?.pairs.map((p) => p.pair_id)).toEqual([
      "phainon_ancient_machine",
      "firefly_sam",
      "march7_fourth_mirror",
    ]);
    // Sidecar 全局当前聊天是流萤会话
    expect(vm.currentPairId).toBe("firefly_sam");
    expect(vm.settings.voice).toMatchObject({
      characterVoiceName: "流萤",
      assistantVoiceName: "萨姆",
      characterVoiceId: "demo-firefly",
      assistantVoiceId: "demo-sam",
    });

    // 本窗口切到其他标签，全局指针仍停在流萤
    for (const [conversationId, pairId, characterVoiceName, assistantVoiceName] of [
      ["conv-march7", "march7_fourth_mirror", "三月七", "第四面镜"],
      ["conv-phainon", "phainon_ancient_machine", "白厄", "神秘的古代机械"],
    ]) {
      desktopStore.getState().openConversationTab(conversationId);
      const tabVm = presentAppShell(desktopStore.getState());
      expect(desktopStore.getState().currentConversationId).toBe("conv-firefly");
      expect(tabVm.currentPairId).toBe(pairId);
      expect(tabVm.settings.voice).toMatchObject({ characterVoiceName, assistantVoiceName });
    }
  });

  it("工作台条目按 timeline_order 混排助手分段与工具卡", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "message.created",
        sequence: 1,
        payload: {
          message: {
            message_id: "assistant:conv-1:task-1:0",
            conversation_id: "conv-1",
            pair_id: "phainon_ancient_machine",
            engine_turn_id: "turn-1",
            source: "assistant",
            kind: "assistant.natural_language",
            text: "我先查看 src 目录。",
            payload: {},
            tts_eligible: true,
            created_at: "2026-08-11T00:00:00+00:00",
            task_id: "task-1",
            timeline_order: 7,
          },
        },
      },
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 2,
        payload: {
          tool_run: {
            tool_call_id: "tool-a",
            conversation_id: "conv-1",
            task_id: "task-1",
            engine_turn_id: "turn-1",
            sequence: 3,
            status: "succeeded",
            title: "list src",
            summary: "",
            details: "",
            timeline_order: 8,
          },
        },
      },
      {
        kind: "event",
        event: "message.created",
        sequence: 3,
        payload: {
          message: {
            message_id: "assistant:conv-1:task-1:1",
            conversation_id: "conv-1",
            pair_id: "phainon_ancient_machine",
            engine_turn_id: "turn-1",
            source: "assistant",
            kind: "assistant.natural_language",
            text: "src 分为核心与适配层。",
            payload: {},
            tts_eligible: true,
            created_at: "2026-08-11T00:00:01+00:00",
            task_id: "task-1",
            timeline_order: 9,
          },
        },
      },
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 4,
        payload: {
          tool_run: {
            tool_call_id: "tool-b",
            conversation_id: "conv-1",
            task_id: "task-1",
            engine_turn_id: "turn-1",
            sequence: 5,
            status: "succeeded",
            title: "list tests",
            summary: "",
            details: "",
            timeline_order: 10,
          },
        },
      },
      {
        kind: "event",
        event: "message.created",
        sequence: 5,
        payload: {
          message: {
            message_id: "assistant:conv-1:task-1:2",
            conversation_id: "conv-1",
            pair_id: "phainon_ancient_machine",
            engine_turn_id: "turn-1",
            source: "assistant",
            kind: "assistant.natural_language",
            text: "测试分三层。",
            payload: {},
            tts_eligible: true,
            created_at: "2026-08-11T00:00:02+00:00",
            task_id: "task-1",
            timeline_order: 11,
          },
        },
      },
    ]);
    const vm = presentAppShell(desktopStore.getState());
    const items = vm.workspace?.assistant.items ?? [];
    const orderedKeys = items
      .filter((item) => item.order !== null)
      .map((item) =>
        item.kind === "message" ? item.message.message_id : item.run.tool_call_id,
      );
    expect(orderedKeys).toEqual([
      "assistant:conv-1:task-1:0",
      "tool-a",
      "assistant:conv-1:task-1:1",
      "tool-b",
      "assistant:conv-1:task-1:2",
    ]);
  });
});

describe("会话角色身份选择器与展示位", () => {
  /** 绑定角色卡的会话；identityOverrides 用于构造已删除卡（missing）等边界。 */
  function cardConversation(
    conversationId: string,
    cardId: string,
    name: string,
    identityOverrides: Partial<NonNullable<ConversationRecord["character_identity"]>> = {},
  ): ConversationRecord {
    return {
      conversation_id: conversationId,
      project_id: "project-1",
      pair_id: "phainon_ancient_machine",
      title: `${name}的聊天`,
      last_mode: "collaboration",
      archived: false,
      created_at: "2026-08-11T00:00:00+00:00",
      updated_at: "2026-08-11T00:00:00+00:00",
      character_card_id: cardId,
      binding_id: `card-bind-${cardId}`,
      character_identity: {
        name,
        avatar_ref: `card-avatar:${cardId}`,
        avatar_version: "v1",
        missing: false,
        source: "card",
        ...identityOverrides,
      },
    };
  }

  function snapshotWith(
    conversations: ConversationRecord[],
    messages: Message[] = [],
  ): DesktopSnapshot {
    const base = createMockScenario("single-project").snapshot;
    const project = base.projects[0];
    return {
      ...base,
      projects: [{ ...project, conversations }],
      messages,
      current_conversation_id: conversations[0]?.conversation_id ?? "",
      current_conversation: conversations[0] ?? base.current_conversation,
    };
  }

  function delegationMessage(conversationId: string, text: string): Message {
    return {
      message_id: `delegation-${conversationId}`,
      conversation_id: conversationId,
      pair_id: "phainon_ancient_machine",
      engine_turn_id: null,
      source: "user",
      kind: "user.text",
      text,
      payload: {},
      tts_eligible: false,
      created_at: "2026-08-11T00:00:00+00:00",
      target: "assistant",
      origin: "character_delegation",
      delegation_id: `task-${conversationId}`,
      status: "done",
      timeline_order: 1,
    };
  }

  it("选择器按会话取身份，两张卡各自解析，不读全局当前搭档", () => {
    desktopStore
      .getState()
      .hydrate(
        snapshotWith([
          cardConversation("conv-a", "card-a", "卡芙卡"),
          cardConversation("conv-b", "card-b", "银狼"),
        ]),
      );
    const state = desktopStore.getState();

    expect(selectConversationCharacterIdentity(state, "conv-a")).toEqual({
      name: "卡芙卡",
      avatarRef: "card-avatar:card-a",
      avatarVersion: "v1",
      missing: false,
      source: "card",
    });
    expect(selectConversationCharacterIdentity(state, "conv-b")?.name).toBe("银狼");
    // 全局搭档是基础搭档（白厄），不参与卡会话的身份解析。
    expect(state.pair?.character.name).toBe("白厄");
    expect(selectConversationCharacterIdentity(state, "conv-不存在")).toBeNull();
    expect(selectConversationCharacterIdentity(state, null)).toBeNull();
  });

  it("旧会话缺 character_identity 时回退内置搭档；绑定卡已删除时回退内置名并标记 missing", () => {
    const legacy = createMockScenario("single-project").snapshot.projects[0].conversations[0];
    const deletedCard = cardConversation("conv-deleted", "card-deleted", "", {
      name: "",
      avatar_ref: null,
      avatar_version: null,
      missing: true,
    });
    desktopStore.getState().hydrate(snapshotWith([legacy, deletedCard]));
    const state = desktopStore.getState();

    expect(selectConversationCharacterIdentity(state, legacy.conversation_id)).toEqual({
      name: "白厄",
      avatarRef: null,
      avatarVersion: null,
      missing: false,
      source: "builtin",
    });
    expect(selectConversationCharacterIdentity(state, "conv-deleted")).toMatchObject({
      name: "白厄",
      avatarRef: null,
      missing: true,
      source: "card",
    });
  });

  it("两个卡会话切换后委派来源按各自会话身份显示，无串扰", () => {
    desktopStore.getState().hydrate(
      snapshotWith(
        [cardConversation("conv-a", "card-a", "卡芙卡"), cardConversation("conv-b", "card-b", "银狼")],
        [
          delegationMessage("conv-a", "读取项目结构"),
          delegationMessage("conv-b", "整理测试报告"),
        ],
      ),
    );
    expect(presentAppShell(desktopStore.getState()).workspace?.delegation).toMatchObject({
      fromName: "卡芙卡",
      summary: "读取项目结构",
    });

    desktopStore.getState().openConversationTab("conv-b");
    expect(presentAppShell(desktopStore.getState()).workspace?.delegation).toMatchObject({
      fromName: "银狼",
      summary: "整理测试报告",
    });
  });

  it("语音迷你播放条与设置页角色音色名按活动会话身份显示卡名", () => {
    desktopStore
      .getState()
      .hydrate(snapshotWith([cardConversation("conv-a", "card-a", "卡芙卡")]));
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "voice.state_changed",
        sequence: 1,
        payload: { voice: { tts: "playing", speech_queue_len: 2 } },
      },
    ]);
    const vm = presentAppShell(desktopStore.getState());
    expect(vm.voiceMiniPlayer).toMatchObject({
      status: "playing",
      speaker: "character",
      speakerName: "卡芙卡",
    });
    expect(vm.settings.voice.characterVoiceName).toBe("卡芙卡");
  });
});
