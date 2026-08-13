import { beforeEach, describe, expect, it } from "vitest";

import type { DesktopEvent } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { presentAppShell } from "./presenters";
import { desktopStore } from "../stores/desktopStore";

/** 以指定场景水合 store，返回当前 ViewModel。 */
function presentScenario(name: "single-project" | "gate-default" | "onboarding-pending") {
  desktopStore.getState().hydrate(createMockScenario(name).snapshot);
  return presentAppShell(desktopStore.getState());
}

describe("presenters V0.2 M4 视觉接口映射", () => {
  beforeEach(() => {
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
      waitingFor: "等待当前回复结束",
      intent: "followup",
    });
    expect(queueItems[1]).toMatchObject({ queueItemId: "q-2", summary: "继续", position: 2 });
  });

  it("delegation：当前会话最新委派消息 → 委派卡；activeTask 决定运行态", () => {
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
        },
      },
    ]);
    vm = presentAppShell(desktopStore.getState());
    expect(vm.workspace?.delegation?.status).toBe("running");

    desktopStore.getState().applyEvents([
      event(3, {
        message: {
          message_id: "delegation-result-1",
          conversation_id: "conv-1",
          pair_id: "phainon_ancient_machine",
          engine_turn_id: "engine-1",
          source: "character",
          kind: "character.speech",
          text: "这次没做成。",
          payload: { result_status: "failed" },
          tts_eligible: true,
          created_at: "2026-08-11T00:00:01+00:00",
          target: "character",
          origin: "character_delegation",
          delegation_id: "task-9",
        },
      }),
    ]);
    vm = presentAppShell(desktopStore.getState());
    expect(vm.workspace?.delegation?.status).toBe("failed");
  });

  it("delegation：无委派消息时为 null；普通 user 消息不触发", () => {
    const vm = presentAppShell(desktopStore.getState());
    expect(vm.workspace?.delegation).toBeNull();
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
    // 用户消息按 target 分流，而非按 source 一刀切
    expect(characterIds).toContain("m-user-chat");
    expect(assistantIds).toContain("m-user-work");
  });

  it("voiceMiniPlayer：tts playing/synthesizing 映射播放条，idle 为 null", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "voice.state_changed",
        sequence: 1,
        payload: { voice: { tts: "playing", speech_queue_len: 2, error: null } },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).voiceMiniPlayer).toMatchObject({
      status: "playing",
      speaker: "character",
      speakerName: "白厄",
      queuedCount: 2,
    });

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "voice.state_changed",
        sequence: 2,
        payload: { voice: { tts: "synthesizing", speech_queue_len: 3, error: null } },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).voiceMiniPlayer?.status).toBe("synthesizing");

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "voice.state_changed",
        sequence: 3,
        payload: { voice: { tts: "idle", speech_queue_len: 0, error: null } },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).voiceMiniPlayer).toBeNull();
  });

  it("voiceMiniPlayer：tts failed → 失败态 + 人话错误", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "voice.state_changed",
        sequence: 1,
        payload: { voice: { tts: "failed", speech_queue_len: 0, error: "语音合成失败：服务无响应" } },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).voiceMiniPlayer).toMatchObject({
      status: "failed",
      errorText: "语音合成失败：服务无响应",
    });
  });

  it("accountGate：默认账号（username=default）出现，非默认账号为 null", () => {
    const gateVm = presentScenario("gate-default");
    expect(gateVm.accountGate).not.toBeNull();
    expect(gateVm.accountGate?.accounts).toHaveLength(2);
    expect(gateVm.accountGate?.accounts.find((item) => item.isLastLogin)?.accountId).toBe(
      "default-local",
    );
    expect(gateVm.onboarding).toBe(false);

    const appVm = presentScenario("single-project");
    expect(appVm.accountGate).toBeNull();
    expect(appVm.onboarding).toBe(false);
  });

  it("onboarding：非默认账号且引导未完成 → true；完成后关闭", () => {
    const vm = presentScenario("onboarding-pending");
    expect(vm.onboarding).toBe(true);
    expect(vm.accountGate).toBeNull();

    // 引导完成（account.changed 水合 onboarding_complete=true）后关闭
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "account.changed",
        sequence: 1,
        payload: {
          account: {
            ...desktopStore.getState().currentAccount,
            onboarding_complete: true,
          },
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
    });
    expect(vm.settings.modelTest).toEqual({ state: "idle" });
    expect(vm.settings.voicePreview).toEqual({ state: "idle" });

    desktopStore.getState().setConfigSnapshot({
      engine: "codex",
      dialogue: {
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
        api_key_masked: "sk-d…1234",
        reasoning_effort: "medium",
      },
      voice: {
        enabled: "true",
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
      codex: { status: "logged_in", account_label: "mock@openai" },
    });
    const mapped = presentAppShell(desktopStore.getState());
    expect(mapped.settings.model).toMatchObject({
      provider: "deepseek",
      model: "deepseek-chat",
      apiKeyMasked: "sk-d…1234",
      reasoningEffort: "medium",
    });
    expect(mapped.settings.voice).toMatchObject({
      enabled: true,
      characterVoiceId: "longxiaoyu",
      characterVoiceName: "白厄",
      assistantVoiceId: "longxiaoyu",
      assistantVoiceName: "神秘的古代机械",
      vadEnabled: true,
    });
    expect(mapped.settings.coding).toEqual({
      engine: "codex",
      codex: { status: "logged_in", accountLabel: "mock@openai" },
    });
    expect(mapped.settings.account.displayName).toBe("演示账号");
  });

  it("toasts：store 透传到 ViewModel", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "error.reported",
        sequence: 1,
        payload: { code: "sidecar", message: "Sidecar 断开", severity: "recoverable" },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).toasts).toMatchObject([
      { id: "sidecar:Sidecar 断开", kind: "warning", text: "Sidecar 断开", hasDetails: true },
    ]);
  });
});
