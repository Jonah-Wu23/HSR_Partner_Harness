import { beforeEach, describe, expect, it } from "vitest";

import type {
  CardGetResult,
  CardListResult,
  ConversationRecord,
  DesktopCommand,
  DesktopCommandMethod,
  ProjectRecord,
  RemoteListDevicesResult,
} from "../contracts/protocol";
import {
  APPROVAL_ALREADY_RESOLVED,
  CARD_AVATAR_UNSUPPORTED,
  CARD_EXPORT_FAILED,
  CARD_IMPORT_FAILED,
  CARD_PUBLISH_INVALID,
  CARD_READ_ONLY,
  VOICE_AUDIO_SEQ_GAP,
  VOICE_NOT_CONFIGURED,
} from "../contracts/protocol";
import { createActionController } from "./actions";
import { DesktopRequestError } from "./backend";
import { MockDesktopBackend, type MockDesktopBackendOptions } from "./mockDesktopBackend";
import { desktopStore } from "../stores/desktopStore";

function cmd(method: DesktopCommandMethod, params: Record<string, unknown> = {}): DesktopCommand {
  return { kind: "request", id: `test-${method}`, method, params };
}

beforeEach(() => {
  desktopStore.setState(desktopStore.getInitialState(), true);
});

describe("MockDesktopBackend 项目与聊天流程", () => {
  it("新建聊天与切换聊天都按快照更新当前聊天", async () => {
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

  it("提交消息后流式回复落到当前聊天", async () => {
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

  it("新建项目：取消选择文件夹时不发请求，带路径时以文件夹名命名，新聊天初始名为「新聊天」", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await expect(controller.actions.createProject()).resolves.toBe(false);
    expect(backend.recordedRequests.some((item) => item.method === "project.create")).toBe(false);

    await expect(controller.actions.createProject("C:/Projects/observatory")).resolves.toBe(true);
    const afterProject = desktopStore.getState();
    expect(afterProject.projectsById[afterProject.currentProjectId]?.name).toBe("observatory");

    await controller.actions.createConversation(undefined);
    const afterConversation = desktopStore.getState();
    expect(afterConversation.conversationsById[afterConversation.currentConversationId]?.title).toBe(
      "新聊天",
    );
  });

  it("归档唯一的项目后快照里没有当前项目与聊天", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await controller.actions.archiveProject("project-1");

    const state = desktopStore.getState();
    expect(state.currentProjectId).toBe("");
    expect(state.currentConversationId).toBe("");
    expect(state.projectsById).toEqual({});
  });

  it("conversation.open 只打开并聚焦本窗口标签，不改全局当前聊天", async () => {
    const backend = new MockDesktopBackend("multi-pair");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    expect(desktopStore.getState().currentConversationId).toBe("conv-firefly");
    await controller.actions.openConversationTab("conv-phainon");

    const state = desktopStore.getState();
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

  it("task.cancel 携带本窗口聊天与其活动任务，取消后活动任务清空", async () => {
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

  it("任务已在服务端结束时 task.cancel 返回 cancelled=false，界面提示取消未生效", async () => {
    const backend = new MockDesktopBackend("collaboration-running");
    const controller = createActionController(backend);
    await controller.loadBootstrap();
    // 任务已被另一端取消，本窗口还没收到 task.busy_changed
    await backend.request(cmd("task.cancel", { conversation_id: "conv-1", task_id: "mock-task-1" }));

    await controller.actions.cancelTask();

    expect(desktopStore.getState().toasts).toContainEqual(
      expect.objectContaining({
        kind: "warning",
        text: "取消未生效：服务端没有取消任务 mock-task-1",
      }),
    );
  });
});

describe("MockDesktopBackend 会话归属", () => {
  it("conversation.create 按显式 project_id 归属该项目，项目不存在时如实报错", async () => {
    const backend = new MockDesktopBackend("many-projects");
    const result = await backend.request<{
      current_conversation_id: string;
      projects: ProjectRecord[];
    }>(
      cmd("conversation.create", {
        project_id: "project-2",
        title: "窗口 B 的新聊天",
        binding_id: "builtin:firefly_sam",
      }),
    );

    const created = result.projects
      .find((item) => item.project_id === "project-2")
      ?.conversations.find((item) => item.conversation_id === result.current_conversation_id);
    expect(created).toMatchObject({
      project_id: "project-2",
      title: "窗口 B 的新聊天",
      binding_id: "builtin:firefly_sam",
    });
    expect(
      result.projects
        .find((item) => item.project_id === "project-1")
        ?.conversations.some((item) => item.conversation_id === result.current_conversation_id),
    ).toBe(false);

    await expect(
      backend.request(cmd("conversation.create", { project_id: "project-999" })),
    ).rejects.toMatchObject({ code: "project_not_found" });
  });

  it("startConversationWithCard 在窗口标签所属项目创建会话，不用后端全局停留的项目", async () => {
    const backend = new MockDesktopBackend("many-projects");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await controller.actions.openConversationTab("project-2-conversation-1");
    // conversation.open 只改本窗口标签，Sidecar 全局仍停在项目 1。
    expect(desktopStore.getState().activeConversationId).toBe("project-2-conversation-1");
    expect(desktopStore.getState().currentProjectId).toBe("project-1");

    await controller.actions.startConversationWithCard("card-saved-002");

    const state = desktopStore.getState();
    const created = state.conversationsById[state.currentConversationId];
    expect(created).toMatchObject({
      project_id: "project-2",
      binding_id: "card-bind-card-saved-002",
      character_card_id: "card-saved-002",
    });
    expect(
      state.projectsById["project-2"].conversations.some(
        (item) => item.conversation_id === created.conversation_id,
      ),
    ).toBe(true);
    expect(
      state.projectsById["project-1"].conversations.some(
        (item) => item.conversation_id === created.conversation_id,
      ),
    ).toBe(false);
  });

  it("reuse_active 复用窗口项目里的活跃卡会话，不回落到后端全局项目", async () => {
    const backend = new MockDesktopBackend("many-projects");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await controller.actions.openConversationTab("project-2-conversation-1");
    await controller.actions.startConversationWithCard("card-saved-002");
    const cardConversationId = desktopStore.getState().currentConversationId;

    // 后端全局切回项目 1，本窗口标签仍停在项目 2 的卡会话。
    await controller.actions.selectProject("project-1");
    expect(desktopStore.getState().currentProjectId).toBe("project-1");
    expect(desktopStore.getState().activeConversationId).toBe(cardConversationId);

    const before = desktopStore.getState().projectsById["project-2"].conversations.length;
    await controller.actions.startConversationWithCard("card-saved-002", { reuseActive: true });

    const state = desktopStore.getState();
    expect(state.currentConversationId).toBe(cardConversationId);
    expect(state.projectsById["project-2"].conversations).toHaveLength(before);
    expect(
      state.projectsById["project-1"].conversations.some(
        (item) => item.binding_id === "card-bind-card-saved-002",
      ),
    ).toBe(false);
  });
});

/** 建一条绑定 card-saved-002 的会话，返回会话 id 与其初始身份。 */
async function createCardConversation(backend: MockDesktopBackend) {
  const created = await backend.request<{
    current_conversation_id: string;
    projects: ProjectRecord[];
  }>(
    cmd("conversation.create", {
      project_id: "project-1",
      binding_id: "card-bind-card-saved-002",
    }),
  );
  const conversation = created.projects
    .flatMap((item) => item.conversations)
    .find((item) => item.conversation_id === created.current_conversation_id);
  return { conversationId: created.current_conversation_id, identity: conversation?.character_identity };
}

/** 订阅卡变更期间的 conversation.changed，返回收集数组与退订函数。 */
function collectConversationChanges(backend: MockDesktopBackend): {
  changes: ConversationRecord[];
  unsubscribe: () => void;
} {
  const changes: ConversationRecord[] = [];
  const unsubscribe = backend.subscribe((event) => {
    if (event.event === "conversation.changed") {
      changes.push(event.payload.conversation as ConversationRecord);
    }
  });
  return { changes, unsubscribe };
}

describe("MockDesktopBackend 角色卡变更的会话身份广播", () => {
  it("card.update 改名后广播带新名字与新头像版本的 conversation.changed", async () => {
    const backend = new MockDesktopBackend("single-project");
    const { conversationId, identity } = await createCardConversation(backend);
    const { changes, unsubscribe } = collectConversationChanges(backend);
    try {
      const detail = await backend.request<CardGetResult>(
        cmd("card.get", { card_id: "card-saved-002" }),
      );
      await backend.request(
        cmd("card.update", {
          card_id: "card-saved-002",
          card: {
            ...detail.card,
            data: { ...(detail.card.data as Record<string, unknown>), name: "卡芙卡·改" },
          },
        }),
      );

      expect(changes).toHaveLength(1);
      expect(changes[0].conversation_id).toBe(conversationId);
      expect(changes[0].character_identity).toMatchObject({
        name: "卡芙卡·改",
        source: "card",
        missing: false,
      });
      // 改名推进 updated_at，头像版本随之变化，客户端头像缓存据此失效。
      expect(changes[0].character_identity?.avatar_version).not.toBe(identity?.avatar_version);
    } finally {
      unsubscribe();
    }
  });

  it("card.remove_avatar 与 card.set_avatar 后广播头像状态同步的会话身份", async () => {
    const backend = new MockDesktopBackend("single-project");
    const { conversationId } = await createCardConversation(backend);
    const { changes, unsubscribe } = collectConversationChanges(backend);
    try {
      await backend.request(cmd("card.remove_avatar", { card_id: "card-saved-002" }));
      expect(changes.at(-1)?.conversation_id).toBe(conversationId);
      expect(changes.at(-1)?.character_identity).toMatchObject({
        avatar_ref: null,
        avatar_version: null,
      });

      await backend.request(
        cmd("card.set_avatar", { card_id: "card-saved-002", path: "C:/Cards/avatar.png" }),
      );
      expect(changes).toHaveLength(2);
      expect(changes.at(-1)?.character_identity).toMatchObject({
        avatar_ref: "card-avatar:card-saved-002",
        source: "card",
      });
      expect(changes.at(-1)?.character_identity?.avatar_version).not.toBeNull();
    } finally {
      unsubscribe();
    }
  });

  it("卡改名的事件流落到 store：会话索引与项目内会话列表一起换成新身份", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      await controller.actions.createConversation(
        "project-1",
        undefined,
        "card-bind-card-saved-002",
      );
      const conversationId = desktopStore.getState().currentConversationId;
      const beforeVersion =
        desktopStore.getState().conversationsById[conversationId].character_identity?.avatar_version;
      expect(beforeVersion).not.toBeNull();

      const detail = await backend.request<CardGetResult>(
        cmd("card.get", { card_id: "card-saved-002" }),
      );
      await controller.actions.updateCard(
        "card-saved-002",
        {
          ...detail.card,
          data: { ...(detail.card.data as Record<string, unknown>), name: "卡芙卡·改" },
        },
      );

      const state = desktopStore.getState();
      expect(state.conversationsById[conversationId].character_identity).toMatchObject({
        name: "卡芙卡·改",
      });
      const inProject = state.projectsById["project-1"].conversations.find(
        (item) => item.conversation_id === conversationId,
      );
      expect(inProject?.character_identity).toMatchObject({ name: "卡芙卡·改" });
      // 头像版本推进：以它为缓存键的头像组件重新加载。
      expect(
        state.conversationsById[conversationId].character_identity?.avatar_version,
      ).not.toBe(beforeVersion);
    } finally {
      unsubscribe();
    }
  });

  it("已归档的角色卡删除后广播身份 missing，不再返回卡名与头像", async () => {
    const backend = new MockDesktopBackend("single-project");
    const { conversationId } = await createCardConversation(backend);
    await backend.request(cmd("card.archive", { card_id: "card-saved-002" }));
    const { changes, unsubscribe } = collectConversationChanges(backend);
    try {
      await backend.request(cmd("card.delete", { card_id: "card-saved-002", confirm: true }));

      expect(changes).toHaveLength(1);
      expect(changes[0].conversation_id).toBe(conversationId);
      expect(changes[0].character_identity).toEqual({
        name: "",
        avatar_ref: null,
        avatar_version: null,
        missing: true,
        source: "card",
      });
    } finally {
      unsubscribe();
    }
  });
});

describe("MockDesktopBackend 与 Sidecar 一致的拒绝与错误码", () => {
  it.each<[string, MockDesktopBackendOptions, DesktopCommand, string]>([
    ["未实现的命令", {}, cmd("metrics.query"), "unknown_method"],
    ["config.test_connection 不连接真实对话服务", {}, cmd("config.test_connection"), "mock_unsupported"],
    [
      "account.login 密码错误",
      {},
      cmd("account.login", { account_id: "demo-account", password: "wrong" }),
      "wrong_password",
    ],
    [
      "account.register 密码不足 6 位",
      {},
      cmd("account.register", { username: "newbie", password: "123" }),
      "weak_password",
    ],
    [
      "account.register 用户名已存在",
      {},
      cmd("account.register", { username: "demo", password: "123456" }),
      "username_taken",
    ],
    [
      "account.change_password 原密码错误",
      {},
      cmd("account.change_password", { old_password: "wrong", new_password: "new-password" }),
      "wrong_password",
    ],
    [
      "remote.pair 配对码无效",
      {},
      cmd("remote.pair", { code: "000000", device_name: "我的手机" }),
      "pairing_invalid_code",
    ],
    ["remote.tunnel_start 远程服务未监听", {}, cmd("remote.tunnel_start"), "serve_not_started"],
    [
      "card.set_avatar 不支持的图片格式",
      {},
      cmd("card.set_avatar", { card_id: "card-draft-001", path: "avatar.gif" }),
      CARD_AVATAR_UNSUPPORTED,
    ],
    [
      "card.peek_import 无法解析的文件",
      {},
      cmd("card.peek_import", { path: "C:/invalid.png" }),
      CARD_IMPORT_FAILED,
    ],
    [
      "card.import_png 无法解析的文件",
      {},
      cmd("card.import_png", { path: "C:/missing.png" }),
      CARD_IMPORT_FAILED,
    ],
    [
      "card.export_png 卡没有头像",
      {},
      cmd("card.export_png", { card_id: "card-draft-001", path: "C:/Export/bai.png" }),
      CARD_EXPORT_FAILED,
    ],
    [
      "card.export_png 内置卡只读",
      {},
      cmd("card.export_png", { card_id: "builtin:phainon", path: "C:/Export/builtin.png" }),
      CARD_READ_ONLY,
    ],
    [
      "voice.card_create 未配置语音 Key",
      { voiceConfigured: false },
      cmd("voice.card_create", { card_id: "card-draft-001", mode: "design" }),
      VOICE_NOT_CONFIGURED,
    ],
    ["card.get 缺少 card_id", {}, cmd("card.get"), "invalid_params"],
    ["card.get 卡不存在", {}, cmd("card.get", { card_id: "card-999" }), "card_not_found"],
    ["card.create_draft 名称为空", {}, cmd("card.create_draft", { name: " " }), "invalid_params"],
    [
      "card.update 内置卡只读",
      {},
      cmd("card.update", { card_id: "builtin:phainon", card: {} }),
      CARD_READ_ONLY,
    ],
    [
      "card.update 缺少整卡 JSON",
      {},
      cmd("card.update", { card_id: "card-draft-001" }),
      "invalid_params",
    ],
    [
      "card.update 卡不存在",
      {},
      cmd("card.update", { card_id: "card-999", card: { spec: "chara_card_v3", data: { name: "不存在的卡" } } }),
      "card_not_found",
    ],
    ["card.duplicate 卡不存在", {}, cmd("card.duplicate", { card_id: "card-999" }), "card_not_found"],
    ["card.archive 草稿", {}, cmd("card.archive", { card_id: "card-draft-001" }), "card_invalid_state"],
    ["card.archive 卡不存在", {}, cmd("card.archive", { card_id: "card-999" }), "card_not_found"],
    ["card.unarchive 卡不存在", {}, cmd("card.unarchive", { card_id: "card-999" }), "card_not_found"],
    [
      "card.delete 未确认",
      {},
      cmd("card.delete", { card_id: "card-draft-001" }),
      "card_confirm_required",
    ],
    ["card.delete 内置卡只读", {}, cmd("card.delete", { card_id: "builtin:phainon", confirm: true }), CARD_READ_ONLY],
    ["card.select_active 内置卡只读", {}, cmd("card.select_active", { card_id: "builtin:phainon" }), CARD_READ_ONLY],
    [
      "card.select_active 已归档的卡",
      {},
      cmd("card.select_active", { card_id: "card-imported-004" }),
      "card_invalid_state",
    ],
    [
      "card.publish 草稿缺少第一条消息",
      {},
      cmd("card.publish", { card_id: "card-draft-001" }),
      CARD_PUBLISH_INVALID,
    ],
  ])("%s时以错误码拒绝", async (_name, options, command, code) => {
    const backend = new MockDesktopBackend("single-project", options);
    const failure = backend.request(command);
    await expect(failure).rejects.toBeInstanceOf(DesktopRequestError);
    await expect(failure).rejects.toMatchObject({ code });
  });

  it("voice.mobile_audio_chunk 按序收下分片回执 accepted，seq 不连续时抛出 voice_audio_seq_gap", async () => {
    const backend = new MockDesktopBackend("single-project");
    const start = await backend.request<{ session_id: string }>(
      cmd("voice.mobile_ptt_start", { conversation_id: "conv-1" }),
    );
    await expect(
      backend.request(
        cmd("voice.mobile_audio_chunk", { session_id: start.session_id, seq: 0, data: "ZAA=" }),
      ),
    ).resolves.toEqual({ accepted: true });
    await expect(
      backend.request(
        cmd("voice.mobile_audio_chunk", { session_id: start.session_id, seq: 2, data: "ZAA=" }),
      ),
    ).rejects.toMatchObject({ code: VOICE_AUDIO_SEQ_GAP });
  });

  it("approval.resolve 重复裁决抛出 approval_already_resolved，details 是先到的终态", async () => {
    const backend = new MockDesktopBackend("approval-request");
    await backend.request(cmd("approval.resolve", { approval_id: "approval-1", decision: "allow" }));
    await expect(
      backend.request(cmd("approval.resolve", { approval_id: "approval-1", decision: "deny" })),
    ).rejects.toMatchObject({
      code: APPROVAL_ALREADY_RESOLVED,
      details: { approval_id: "approval-1", decision: "allow", resolved_by: "desktop" },
    });
  });
});

describe("MockDesktopBackend 角色卡导入与音色", () => {
  it.each([
    [
      "C:/Cards/bai.json",
      { format: "json", avatar_available: false, avatar_width: null, avatar_height: null },
    ],
    [
      "C:/Cards/bai.PNG",
      { format: "png", avatar_available: true, avatar_width: 512, avatar_height: 512 },
    ],
  ])("card.peek_import 预览 %s 时给出格式与头像信息", async (path, expected) => {
    const backend = new MockDesktopBackend("single-project");
    await expect(backend.request(cmd("card.peek_import", { path }))).resolves.toMatchObject({
      preview: expected,
    });
  });

  it("card.import_png 入库为酒馆导入卡，PNG 字节同时作为头像", async () => {
    const backend = new MockDesktopBackend("single-project");
    const result = await backend.request<{ card_id: string; state: string }>(
      cmd("card.import_png", { path: "C:/Cards/bai.png" }),
    );
    expect(result.state).toBe("imported");

    const list = await backend.request<{
      cards: Array<{ card_id: string; has_avatar: boolean; source: string }>;
    }>(cmd("card.list"));
    expect(list.cards.find((card) => card.card_id === result.card_id)).toMatchObject({
      has_avatar: true,
      source: "tavern_import",
    });

    const detail = await backend.request<{ avatar: { mime_type: string } | null }>(
      cmd("card.get", { card_id: result.card_id }),
    );
    expect(detail.avatar).toMatchObject({ mime_type: "image/png" });
  });

  it("card.import_png 以副本导入时名称追加「（副本）」", async () => {
    const backend = new MockDesktopBackend("single-project");
    const original = await backend.request<{ name: string }>(
      cmd("card.import_png", { path: "C:/Cards/bai.png" }),
    );
    const duplicate = await backend.request<{ name: string }>(
      cmd("card.import_png", { path: "C:/Cards/bai.png", as_duplicate: true }),
    );
    expect(duplicate.name).toBe(`${original.name}（副本）`);
  });

  it("voice.card_create 在响应之前依次推送 voice_creating 与带 voice_id 的 voice_ready", async () => {
    const backend = new MockDesktopBackend("single-project");
    const changes: Array<Record<string, unknown>> = [];
    const unsubscribe = backend.subscribe((event) => {
      if (event.event === "voice.card_provision_changed") changes.push(event.payload);
    });
    try {
      await backend.request(
        cmd("voice.card_bind_reference", { card_id: "card-draft-001", path: "ref.wav" }),
      );
      const result = await backend.request<{ card_id: string; state: string; voice_id: string }>(
        cmd("voice.card_create", { card_id: "card-draft-001", mode: "clone" }),
      );

      expect(result).toEqual({ card_id: "card-draft-001", state: "voice_ready", voice_id: result.voice_id });
      expect(changes).toEqual([
        { card_id: "card-draft-001", state: "voice_creating", voice_id: null, error: null },
        { card_id: "card-draft-001", state: "voice_ready", voice_id: result.voice_id, error: null },
      ]);
      const list = await backend.request<CardListResult>(cmd("card.list"));
      expect(list.cards.find((card) => card.card_id === "card-draft-001")?.voice_state).toBe("voice_ready");
    } finally {
      unsubscribe();
    }
  });

  it("voice.card_create 失败时先推送 voice_failed，再以 voice_card_create_failed 拒绝", async () => {
    const backend = new MockDesktopBackend("single-project", { voiceProvisionFail: true });
    const changes: Array<Record<string, unknown>> = [];
    const unsubscribe = backend.subscribe((event) => {
      if (event.event === "voice.card_provision_changed") changes.push(event.payload);
    });
    try {
      const error = await backend
        .request(
          cmd("voice.card_create", { card_id: "card-draft-001", mode: "design", voice_prompt: "温柔的少女音" }),
        )
        .catch((reason: unknown) => reason);
      expect(error).toBeInstanceOf(DesktopRequestError);
      expect(error).toMatchObject({ code: "voice_card_create_failed" });

      expect(changes.map((change) => change.state)).toEqual(["voice_creating", "voice_failed"]);
      expect(changes[1]).toMatchObject({ voice_id: null, error: (error as DesktopRequestError).message });
      const list = await backend.request<CardListResult>(cmd("card.list"));
      expect(list.cards.find((card) => card.card_id === "card-draft-001")?.voice_state).toBe("voice_failed");
    } finally {
      unsubscribe();
    }
  });
});

describe("MockDesktopBackend 角色卡内容与 Sidecar 一致", () => {
  it("card.get 返回 card.update 写入的整卡，写入第一条消息后草稿可以发布", async () => {
    const backend = new MockDesktopBackend("single-project");
    const before = await backend.request<CardGetResult>(cmd("card.get", { card_id: "card-draft-001" }));
    const data = before.card.data as Record<string, unknown>;
    const edited = { ...before.card, data: { ...data, name: "改名后的草稿", first_mes: "你好。" } };

    await backend.request(cmd("card.update", { card_id: "card-draft-001", card: edited }));

    const after = await backend.request<CardGetResult>(cmd("card.get", { card_id: "card-draft-001" }));
    expect(after.card).toEqual(edited);
    const list = await backend.request<CardListResult>(cmd("card.list"));
    expect(list.cards.find((card) => card.card_id === "card-draft-001")?.name).toBe("改名后的草稿");
    await expect(backend.request(cmd("card.publish", { card_id: "card-draft-001" }))).resolves.toEqual({
      card_id: "card-draft-001",
      state: "saved",
    });
  });

  it("样例卡摘要的 has_avatar 与 card.get 的头像一致", async () => {
    const backend = new MockDesktopBackend("single-project");
    const list = await backend.request<CardListResult>(cmd("card.list", { include_archived: true }));
    for (const summary of list.cards) {
      const detail = await backend.request<CardGetResult>(cmd("card.get", { card_id: summary.card_id }));
      expect({ card_id: summary.card_id, avatar: detail.avatar !== null }).toEqual({
        card_id: summary.card_id,
        avatar: summary.has_avatar,
      });
    }
  });

  it("复制内置卡生成可编辑的导入卡副本，没有头像", async () => {
    const backend = new MockDesktopBackend("single-project");
    const copy = await backend.request<{ card_id: string; name: string }>(
      cmd("card.duplicate", { card_id: "builtin:phainon" }),
    );
    expect(copy.name).toBe("白厄（副本）");

    const list = await backend.request<CardListResult>(cmd("card.list"));
    expect(list.cards.find((card) => card.card_id === copy.card_id)).toMatchObject({
      name: "白厄（副本）",
      state: "imported",
      source: "tavern_import",
      has_avatar: false,
      read_only: false,
    });
    const detail = await backend.request<CardGetResult>(cmd("card.get", { card_id: copy.card_id }));
    expect(detail).toMatchObject({ read_only: false, avatar: null });
    expect((detail.card.data as Record<string, unknown>).name).toBe("白厄（副本）");
  });
});

describe("MockDesktopBackend 电源与远程设备", () => {
  it("power.get_status 与 Windows 上未开启远程服务时的 Sidecar 结果同形", async () => {
    const backend = new MockDesktopBackend("single-project");
    await expect(backend.request(cmd("power.get_status"))).resolves.toMatchObject({
      supported: true,
      platform: "win32",
      remote_serve_enabled: false,
      at_risk: false,
      reason: "远程服务未开启",
      threshold_seconds: 900,
      warnings: [],
    });
  });

  it("remote.list_devices 的设备带到期时间：签发后 30 天与最近使用后 7 天取早", async () => {
    const backend = new MockDesktopBackend("single-project");
    const result = await backend.request<RemoteListDevicesResult>(cmd("remote.list_devices"));
    expect(result.devices).toEqual([
      {
        device_name: "小米 14",
        issued_at: "2026-08-19T09:00:00+00:00",
        last_used_at: "2026-08-19T12:30:00+00:00",
        expires_at: "2026-08-26T12:30:00+00:00",
        revoked: false,
      },
    ]);
  });
});
