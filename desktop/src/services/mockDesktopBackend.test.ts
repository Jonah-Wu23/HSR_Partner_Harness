import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopCommand, DesktopCommandMethod } from "../contracts/protocol";
import {
  APPROVAL_ALREADY_RESOLVED,
  CARD_AVATAR_UNSUPPORTED,
  CARD_EXPORT_FAILED,
  CARD_IMPORT_FAILED,
  CARD_READ_ONLY,
  VOICE_AUDIO_SEQ_GAP,
  VOICE_NOT_CONFIGURED,
} from "../contracts/protocol";
import { createActionController } from "./actions";
import { MockDesktopBackend } from "./mockDesktopBackend";
import { desktopStore } from "../stores/desktopStore";

function cmd(method: DesktopCommandMethod, params: Record<string, unknown> = {}): DesktopCommand {
  return { kind: "request", id: `test-${method}`, method, params };
}

describe("MockDesktopBackend project and conversation flow", () => {
  beforeEach(() => {
    desktopStore.getState().setStatus("booting");
    desktopStore.getState().setComposerDraft("");
  });

  it("keeps project and chat selection in the same snapshot contract", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await controller.actions.createConversation(undefined, "新的协作聊天");
    const stateAfterCreate = desktopStore.getState();
    const createdConversationId = stateAfterCreate.currentConversationId;
    expect(stateAfterCreate.conversationsById[createdConversationId]?.title).toBe("新的协作聊天");

    await controller.actions.selectConversation("conv-1");
    expect(desktopStore.getState().currentConversationId).toBe("conv-1");
    expect(desktopStore.getState().projectsById["project-1"].conversations).toHaveLength(2);
  });

  it("routes mock streaming messages to the selected conversation", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      await controller.actions.submitMessage("继续看看", "character");
      const state = desktopStore.getState();
      const messageIds = state.messageIdsByConversation["conv-1"] ?? [];
      expect(messageIds).toHaveLength(4);
      expect(state.messagesById[messageIds.at(-1) ?? ""]?.source).toBe("character");
      expect(state.messagesById[messageIds.at(-1) ?? ""]?.streaming).toBe(false);
    } finally {
      unsubscribe();
    }
  });

  it("createProject 取消文件夹时返回 false，带路径创建时返回 true", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await expect(controller.actions.createProject()).resolves.toBe(false);
    await expect(controller.actions.createProject("C:/Projects/observatory")).resolves.toBe(true);
  });

  it("uses the selected folder name for new projects and auto-names the first chat", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      await controller.actions.createProject("C:/Projects/observatory");
      const stateAfterProject = desktopStore.getState();
      expect(stateAfterProject.projectsById[stateAfterProject.currentProjectId]?.name).toBe(
        "observatory",
      );

      await controller.actions.createConversation(undefined);
      const conversationId = desktopStore.getState().currentConversationId;
      expect(desktopStore.getState().conversationsById[conversationId]?.title).toBe("新聊天");
      await controller.actions.submitMessage("整理实验记录", "character");
      expect(desktopStore.getState().conversationsById[conversationId]?.title).toBe("关于整理实验记录");
    } finally {
      unsubscribe();
    }
  });

  it("reconnect 模拟断线-恢复并驱动连接状态机", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      expect(desktopStore.getState().status).toBe("ready");

      await controller.actions.reconnect();
      // 断线-恢复事件驱动 store：connected 进入 booting 并标记需要重新 bootstrap
      expect(desktopStore.getState().status).toBe("booting");
      expect(desktopStore.getState().needsBootstrap).toBe(true);

      // 与 AppController 的恢复流程一致：重新 bootstrap 后回到 ready
      await controller.loadBootstrap();
      expect(desktopStore.getState().status).toBe("ready");
    } finally {
      unsubscribe();
    }
  });

  it("archives a project even when it is the only project", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await controller.actions.archiveProject("project-1");

    const state = desktopStore.getState();
    expect(state.currentProjectId).toBe("");
    expect(state.currentConversationId).toBe("");
    expect(state.projectsById).toEqual({});
  });

  it("opens another chat through conversation.open without global selection", async () => {
    const backend = new MockDesktopBackend("multi-pair");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    expect(desktopStore.getState().currentConversationId).toBe("conv-firefly");
    await controller.actions.openConversationTab("conv-phainon");

    const state = desktopStore.getState();
    // conversation.open 只打开并聚焦本窗口标签，不改 Sidecar 全局当前聊天。
    expect(state.currentConversationId).toBe("conv-firefly");
    expect(state.activeConversationId).toBe("conv-phainon");
    expect(state.openConversationIds).toContain("conv-firefly");
    expect(state.openConversationIds).toContain("conv-phainon");
    expect(backend.recordedRequests.at(-1)?.method).toBe("conversation.open");
    expect(backend.recordedRequests.at(-1)?.params).toMatchObject({
      conversation_id: "conv-phainon",
    });
    expect(backend.recordedRequests.some((item) => item.method === "conversation.select")).toBe(
      false,
    );

    // 已打开的标签再次聚焦也要取权威快照，不能只切本地 ID。
    await controller.actions.openConversationTab("conv-firefly");
    expect(backend.recordedRequests.at(-1)?.method).toBe("conversation.open");
    expect(backend.recordedRequests.at(-1)?.params).toMatchObject({
      conversation_id: "conv-firefly",
    });
  });

  it("cancels only the matching conversation task in the mock protocol", async () => {
    const backend = new MockDesktopBackend("collaboration-running");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      await controller.actions.cancelTask();

      const request = backend.recordedRequests.at(-1);
      expect(request?.method).toBe("task.cancel");
      expect(request?.params).toEqual({
        conversation_id: "conv-1",
        task_id: "mock-task-1",
      });
      expect(desktopStore.getState().activeTask).toBeNull();
    } finally {
      unsubscribe();
    }
  });
});

describe("MockDesktopBackend V0.3.5 角色卡/语音/审批 mock", () => {
  it("pickFile / saveFile 返回 options 中配置的默认值", async () => {
    const backend = new MockDesktopBackend("single-project", {
      pickFileResult: "C:/Cards/import.json",
      saveFileResult: "C:/Cards/export.json",
    });
    expect(await backend.pickFile()).toBe("C:/Cards/import.json");
    expect(await backend.saveFile()).toBe("C:/Cards/export.json");
  });

  it("card.peek_import_json 返回白厄样例预览；非法路径抛出 CARD_IMPORT_FAILED", async () => {
    const backend = new MockDesktopBackend("single-project");
    const result = await backend.request(cmd("card.peek_import_json", { path: "C:/bai.json" }));
    expect(result).toMatchObject({
      preview: {
        name: "白厄（3.4前）",
        spec_version: "3.0",
        greeting_count: 6,
        world_book_entries: 20,
      },
    });

    await expect(
      backend.request(cmd("card.peek_import_json", { path: "C:/invalid.json" })),
    ).rejects.toMatchObject({ code: CARD_IMPORT_FAILED });
  });

  it("card.set_avatar 对不支持的图片格式抛出 CARD_AVATAR_UNSUPPORTED", async () => {
    const backend = new MockDesktopBackend("single-project");
    await expect(
      backend.request(cmd("card.set_avatar", { card_id: "card-draft-001", path: "avatar.gif" })),
    ).rejects.toMatchObject({ code: CARD_AVATAR_UNSUPPORTED });
  });

  it("voice.card_create 未配置语音 Key 时抛出 VOICE_NOT_CONFIGURED", async () => {
    const backend = new MockDesktopBackend("single-project", { voiceConfigured: false });
    await expect(
      backend.request(cmd("voice.card_create", { card_id: "card-draft-001", mode: "design" })),
    ).rejects.toMatchObject({ code: VOICE_NOT_CONFIGURED });
  });

  it("voice.card_create clone 模式成功后 emit voice.card_provision_changed", async () => {
    const backend = new MockDesktopBackend("single-project");
    const events: Array<{ event: string; payload: Record<string, unknown> }> = [];
    const unsubscribe = backend.subscribe((evt) =>
      events.push({ event: evt.event, payload: evt.payload }),
    );
    try {
      await backend.request(cmd("voice.card_bind_reference", { card_id: "card-draft-001", path: "ref.wav" }));
      const result = await backend.request(
        cmd("voice.card_create", { card_id: "card-draft-001", mode: "clone" }),
      );
      expect(result).toMatchObject({ card_id: "card-draft-001", state: "voice_ready" });
      expect((result as { voice_id?: string }).voice_id).toBeTruthy();

      await vi.waitFor(() => {
        expect(
          events.some(
            (e) => e.event === "voice.card_provision_changed" && e.payload.state === "voice_ready",
          ),
        ).toBe(true);
      });
      const changed = events.find(
        (e) => e.event === "voice.card_provision_changed" && e.payload.state === "voice_ready",
      );
      expect(changed?.payload).toMatchObject({
        card_id: "card-draft-001",
        state: "voice_ready",
      });
    } finally {
      unsubscribe();
    }
  });

  it("voice.mobile_audio_chunk 检测到 seq 缺口时抛出 VOICE_AUDIO_SEQ_GAP", async () => {
    const backend = new MockDesktopBackend("single-project");
    const start = await backend.request<{ session_id: string }>(
      cmd("voice.mobile_ptt_start", { conversation_id: "conv-1" }),
    );
    await backend.request(
      cmd("voice.mobile_audio_chunk", { session_id: start.session_id, seq: 0, data: "ZAA=" }),
    );
    await expect(
      backend.request(
        cmd("voice.mobile_audio_chunk", { session_id: start.session_id, seq: 2, data: "ZAA=" }),
      ),
    ).rejects.toMatchObject({ code: VOICE_AUDIO_SEQ_GAP });
  });

  it("approval.resolve 重复决议抛出 APPROVAL_ALREADY_RESOLVED", async () => {
    const backend = new MockDesktopBackend("single-project");
    await backend.request(cmd("approval.resolve", { approval_id: "app-1", decision: "approve" }));
    await expect(
      backend.request(cmd("approval.resolve", { approval_id: "app-1", decision: "reject" })),
    ).rejects.toMatchObject({ code: APPROVAL_ALREADY_RESOLVED });
  });
});

describe("MockDesktopBackend V0.3.7 PNG 导入导出/电源状态 mock", () => {
  it("card.peek_import 按扩展名分派 JSON/PNG 预览，card.peek_import_json 别名同行为", async () => {
    const backend = new MockDesktopBackend("single-project");
    await expect(
      backend.request(cmd("card.peek_import", { path: "C:/Cards/bai.json" })),
    ).resolves.toMatchObject({
      preview: {
        name: "白厄（3.4前）",
        spec_version: "3.0",
        format: "json",
        avatar_available: false,
        avatar_width: null,
        avatar_height: null,
        greeting_count: 6,
        world_book_entries: 20,
      },
    });
    await expect(
      backend.request(cmd("card.peek_import", { path: "C:/Cards/bai.PNG" })),
    ).resolves.toMatchObject({
      preview: {
        name: "白厄（3.4前）",
        format: "png",
        avatar_available: true,
        avatar_width: 512,
        avatar_height: 512,
      },
    });
    await expect(
      backend.request(cmd("card.peek_import_json", { path: "C:/Cards/bai.json" })),
    ).resolves.toMatchObject({ preview: { format: "json", avatar_available: false } });
  });

  it("card.peek_import 对损坏文件路径抛出 CARD_IMPORT_FAILED", async () => {
    const backend = new MockDesktopBackend("single-project");
    await expect(
      backend.request(cmd("card.peek_import", { path: "C:/invalid.png" })),
    ).rejects.toMatchObject({ code: CARD_IMPORT_FAILED });
  });

  it("card.import_png 返回 card_id/name/state/report 并把 PNG 字节置为头像", async () => {
    const backend = new MockDesktopBackend("single-project");
    const result = await backend.request<{ card_id: string; name: string; state: string }>(
      cmd("card.import_png", { path: "C:/Cards/bai.png" }),
    );
    expect(result.state).toBe("imported");
    expect(result.name).toBe("白厄（3.4前）");
    expect(result.card_id).toBeTruthy();

    const list = await backend.request<{
      cards: Array<{ card_id: string; has_avatar: boolean; source: string }>;
    }>(cmd("card.list"));
    expect(
      list.cards.find((card) => card.card_id === result.card_id),
    ).toMatchObject({ has_avatar: true, source: "imported_png" });

    const detail = await backend.request<{ avatar: { mime_type: string } | null }>(
      cmd("card.get", { card_id: result.card_id }),
    );
    expect(detail.avatar).toMatchObject({ mime_type: "image/png" });
  });

  it("card.import_png as_duplicate=true 名称追加（副本）；损坏路径抛出 CARD_IMPORT_FAILED", async () => {
    const backend = new MockDesktopBackend("single-project");
    const result = await backend.request<{ name: string }>(
      cmd("card.import_png", { path: "C:/Cards/bai.png", as_duplicate: true }),
    );
    expect(result.name).toBe("白厄（3.4前）（副本）");
    await expect(
      backend.request(cmd("card.import_png", { path: "C:/missing.png" })),
    ).rejects.toMatchObject({ code: CARD_IMPORT_FAILED });
  });

  it("card.export_png 对无头像卡抛出 CARD_EXPORT_FAILED 并引导设置头像", async () => {
    const backend = new MockDesktopBackend("single-project");
    await expect(
      backend.request(
        cmd("card.export_png", { card_id: "card-draft-001", path: "C:/Export/bai.png" }),
      ),
    ).rejects.toMatchObject({
      code: CARD_EXPORT_FAILED,
      message: "卡未设置头像，请先设置头像后再导出 PNG",
    });
  });

  it("card.export_png 内置卡抛出 CARD_READ_ONLY，有头像卡返回冻结 §1.3 结果", async () => {
    const backend = new MockDesktopBackend("single-project");
    await expect(
      backend.request(
        cmd("card.export_png", { card_id: "builtin:phainon", path: "C:/Export/builtin.png" }),
      ),
    ).rejects.toMatchObject({ code: CARD_READ_ONLY });

    const result = await backend.request<Record<string, unknown>>(
      cmd("card.export_png", { card_id: "card-saved-002", path: "C:/Export/kafka.png" }),
    );
    expect(result).toMatchObject({
      exported: true,
      path: "C:/Export/kafka.png",
      name: "卡芙卡",
      spec_version: "3.0",
      greeting_count: 6,
      world_book_entries: 20,
      extensions: ["hsr"],
    });
  });

  it("power.get_status 返回冻结 §1.5 的 Windows 成功形状", async () => {
    const backend = new MockDesktopBackend("single-project");
    const result = await backend.request<Record<string, unknown>>(cmd("power.get_status"));
    expect(result).toMatchObject({
      supported: true,
      platform: "windows",
      plan_name: "平衡",
      ac_sleep_timeout_seconds: 1800,
      dc_sleep_timeout_seconds: 1200,
      remote_serve_enabled: false,
      threshold_seconds: 900,
      at_risk: false,
      reason: "AC/DC 睡眠超时均不低于阈值",
    });
    expect(typeof result.checked_at).toBe("string");
  });

  it("emitPowerStatusChanged 发出 power.status_changed 并更新 mock 最近状态", async () => {
    const backend = new MockDesktopBackend("single-project");
    const events: Array<{ event: string; payload: Record<string, unknown> }> = [];
    const unsubscribe = backend.subscribe((event) =>
      events.push({ event: event.event, payload: event.payload }),
    );
    try {
      const payload = {
        supported: true,
        platform: "windows",
        plan_name: "平衡",
        ac_sleep_timeout_seconds: 600,
        dc_sleep_timeout_seconds: null,
        remote_serve_enabled: true,
        threshold_seconds: 900,
        at_risk: true,
        reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
        checked_at: new Date().toISOString(),
      };
      backend.emitPowerStatusChanged(payload);
      const changed = events.find((event) => event.event === "power.status_changed");
      expect(changed?.payload).toEqual(payload);
      expect(backend.lastPowerStatus).toEqual(payload);
    } finally {
      unsubscribe();
    }
  });
});
