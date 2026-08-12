import type {
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PairRecord,
  ProjectRecord,
  ToolRun,
} from "../contracts/protocol";

export type MockScenarioName =
  | "empty"
  | "single-project"
  | "many-projects"
  | "invalid-path"
  | "chat-streaming"
  | "collaboration-running"
  | "task-succeeded"
  | "task-failed"
  | "task-cancelled"
  | "approval-request"
  | "approval-review"
  | "approval-full-auto"
  | "voice-listening"
  | "voice-playing"
  | "performance-500"
  | "light-theme"
  | "dark-theme"
  | "gate-default"
  | "onboarding-pending";

export interface MockScenario {
  name: MockScenarioName;
  label: string;
  snapshot: DesktopSnapshot;
  submitEvents: DesktopEvent[];
}

const pair: PairRecord = {
  pair_id: "phainon_ancient_machine",
  character: { id: "phainon", name: "白厄", voice_id: "demo-phainon" },
  assistant: {
    id: "ancient_machine",
    name: "神秘的古代机械",
    voice_id: "demo-ancient-machine",
  },
  theme: {
    character_text: "#C7D4E3",
    character_primary: "#8AA4D4",
    character_deep: "#3A548C",
    character_active: "#296CE1",
    assistant_primary: "#B08D57",
    assistant_bright: "#C5A059",
    assistant_shadow: "#8C6B3F",
  },
};

// V0.2 M4：场景默认已登录非默认账号（username != "default"，不触发账号门）；
// 账号门/引导场景单独用 gate-default / onboarding-pending。
const demoAccount: DesktopSnapshot["current_account"] = {
  account_id: "demo-account",
  username: "demo",
  display_name: "演示账号",
  avatar: "",
  last_login_at: "2026-08-11T00:00:00+00:00",
  onboarding_complete: true,
  theme: "dark",
};

const defaultLocalAccount: DesktopSnapshot["current_account"] = {
  account_id: "default-local",
  username: "default",
  display_name: "默认账号",
  avatar: "",
  last_login_at: null,
  onboarding_complete: false,
  theme: "dark",
};

export function project(
  id: string,
  name: string,
  rootPath: string,
  conversations: ProjectRecord["conversations"],
  pathAvailable = true,
): ProjectRecord {
  return {
    project_id: id,
    name,
    root_path: rootPath,
    approval_mode: "request_approval",
    reasoning_effort: "low",
    archived: false,
    created_at: "2026-08-11T00:00:00+00:00",
    last_opened_at: "2026-08-11T00:00:00+00:00",
    path_available: pathAvailable,
    conversations,
  };
}

export function conversation(
  id: string,
  projectId: string,
  title: string,
): ProjectRecord["conversations"][number] {
  return {
    conversation_id: id,
    project_id: projectId,
    pair_id: pair.pair_id,
    title,
    last_mode: "collaboration",
    archived: false,
    created_at: "2026-08-11T00:00:00+00:00",
    updated_at: "2026-08-11T00:00:00+00:00",
  };
}

export function message(
  id: string,
  conversationId: string,
  source: Message["source"],
  kind: Message["kind"],
  text: string,
): Message {
  return {
    message_id: id,
    conversation_id: conversationId,
    pair_id: pair.pair_id,
    engine_turn_id: null,
    source,
    kind,
    text,
    payload: {},
    tts_eligible: source === "character" || source === "assistant",
    created_at: "2026-08-11T00:00:00+00:00",
  };
}

function toolRun(
  conversationId: string,
  status: ToolRun["status"] = "running",
): ToolRun {
  return {
    tool_call_id: "mock-tool-1",
    conversation_id: conversationId,
    task_id: "mock-task-1",
    engine_turn_id: "mock-turn-1",
    sequence: 2,
    status,
    title: "检查项目文件",
    summary: status === "running" ? "正在读取项目状态" : "项目检查已完成",
    details: "mock backend 记录；不访问真实文件系统。",
  };
}

function baseSnapshot(
  projects: ProjectRecord[],
  conversationId: string,
  messages: Message[] = [],
  toolRuns: ToolRun[] = [],
): DesktopSnapshot {
  const currentProject = projects.find((item) =>
    item.conversations.some((item) => item.conversation_id === conversationId),
  );
  const currentConversation = currentProject?.conversations.find(
    (item) => item.conversation_id === conversationId,
  );
  const fallbackProject = currentProject ?? projects[0];
  const fallbackConversation = currentConversation ?? fallbackProject?.conversations[0];
  return {
    projects,
    current_account_id: demoAccount.account_id,
    current_account: { ...demoAccount },
    accounts: [{ ...demoAccount, is_last_login: true }],
    current_project_id: fallbackProject?.project_id ?? "",
    current_conversation_id: fallbackConversation?.conversation_id ?? "",
    current_project: fallbackProject
      ? { ...fallbackProject, conversations: undefined } as Omit<ProjectRecord, "conversations">
      : {
          project_id: "",
          name: "",
          root_path: "",
          approval_mode: "request_approval",
          reasoning_effort: "low",
          archived: false,
          created_at: null,
          last_opened_at: null,
          path_available: false,
        },
    current_conversation: fallbackConversation ?? {
      conversation_id: "",
      project_id: null,
      pair_id: pair.pair_id,
      title: "",
      last_mode: "chat",
      archived: false,
      created_at: "2026-08-11T00:00:00+00:00",
      updated_at: "2026-08-11T00:00:00+00:00",
    },
    messages,
    tool_runs: toolRuns,
    turns: [],
    queue_items: [],
    active_task: null,
    busy: false,
    approvals: [],
    voice: {
      supported: true,
      vad: "idle",
      vad_enabled: false,
      ptt: false,
      tts: "idle",
      asr_partial: "",
      error: null,
      // V0.2 M4：待播队列条数（VoiceMiniPlayer 的 queuedCount）
      speech_queue_len: 0,
    },
    pair,
    sequence: 0,
  };
}

function submitEvents(conversationId: string): DesktopEvent[] {
  return [
    {
      kind: "event",
      event: "message.created",
      sequence: 1,
      payload: {
        message: message(
          "mock-user-2",
          conversationId,
          "user",
          "user.text",
          "继续看看这个项目",
        ),
      },
    },
    {
      kind: "event",
      event: "message.delta",
      sequence: 2,
      payload: {
        message_id: "mock-character-stream",
        conversation_id: conversationId,
        source: "character",
        kind: "character.speech",
        delta: "我已经看见了",
      },
    },
    {
      kind: "event",
      event: "message.delta",
      sequence: 3,
      payload: {
        message_id: "mock-character-stream",
        conversation_id: conversationId,
        source: "character",
        kind: "character.speech",
        delta: "，我们一起继续。",
      },
    },
    {
      kind: "event",
      event: "message.finalized",
      sequence: 4,
      payload: { message_id: "mock-character-stream", conversation_id: conversationId },
    },
  ];
}

export const MOCK_SCENARIO_NAMES: MockScenarioName[] = [
  "empty",
  "single-project",
  "many-projects",
  "invalid-path",
  "chat-streaming",
  "collaboration-running",
  "task-succeeded",
  "task-failed",
  "task-cancelled",
  "approval-request",
  "approval-review",
  "approval-full-auto",
  "voice-listening",
  "voice-playing",
  "performance-500",
  "light-theme",
  "dark-theme",
  "gate-default",
  "onboarding-pending",
];

export function createMockScenario(name: MockScenarioName): MockScenario {
  const firstConversation = conversation("conv-1", "project-1", "奥赫玛的项目聊天");
  const firstProject = project("project-1", "星穹项目", "C:/Projects/astral", [firstConversation]);
  const defaultMessages = [
    message("message-1", firstConversation.conversation_id, "user", "user.text", "帮我看看这个项目"),
    message(
      "message-2",
      firstConversation.conversation_id,
      "character",
      "character.speech",
      "好，我和你一起看。需要执行的事情交给古代机械。",
    ),
  ];
  let projects = [firstProject];
  let messages = defaultMessages;
  let tools: ToolRun[] = [];
  let snapshot = baseSnapshot(projects, firstConversation.conversation_id, messages, tools);

  if (name === "empty") {
    snapshot = baseSnapshot([], "", [], []);
  } else if (name === "many-projects") {
    projects = Array.from({ length: 5 }, (_, projectIndex) => {
      const projectId = `project-${projectIndex + 1}`;
      return project(
        projectId,
        `项目 ${projectIndex + 1}：一个很长的项目标题用于检查导航布局`,
        `C:/Projects/project-${projectIndex + 1}`,
        Array.from({ length: 6 }, (_, conversationIndex) =>
          conversation(
            `${projectId}-conversation-${conversationIndex + 1}`,
            projectId,
            `聊天 ${conversationIndex + 1}：持续讨论中的较长标题`,
          ),
        ),
      );
    });
    snapshot = baseSnapshot(projects, "project-1-conversation-1", [], []);
  } else if (name === "invalid-path") {
    projects = [project("project-1", "路径失效项目", "C:/Missing/project", [firstConversation], false)];
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, []);
  } else if (name === "chat-streaming") {
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, []);
  } else if (name === "collaboration-running") {
    tools = [toolRun(firstConversation.conversation_id, "running")];
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, tools);
    snapshot.busy = true;
    snapshot.active_task = {
      project_id: firstProject.project_id,
      conversation_id: firstConversation.conversation_id,
      task_id: "mock-task-1",
      engine_turn_id: "mock-turn-1",
    };
  } else if (name === "task-succeeded" || name === "task-failed" || name === "task-cancelled") {
    const status: ToolRun["status"] = name === "task-succeeded" ? "succeeded" : "failed";
    tools = [toolRun(firstConversation.conversation_id, status)];
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, tools);
  } else if (name === "approval-request" || name === "approval-review" || name === "approval-full-auto") {
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, [toolRun(firstConversation.conversation_id)]);
    snapshot.current_project.approval_mode =
      name === "approval-review" ? "review" : name === "approval-full-auto" ? "full_auto" : "request_approval";
    snapshot.projects[0].approval_mode = snapshot.current_project.approval_mode;
    if (name === "approval-request" || name === "approval-review") {
      snapshot.approvals = [
        {
          approval_id: "approval-1",
          conversation_id: firstConversation.conversation_id,
          operation: {
            tool_kind: "shell",
            command: "pytest -q",
            paths: [],
            patch_file_count: null,
            summary: "运行项目测试",
          },
          reason: "该操作需要审批",
        },
      ];
    }
  } else if (name === "voice-listening" || name === "voice-playing") {
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, []);
    snapshot.voice.vad = name === "voice-listening" ? "listening" : "playing";
    snapshot.voice.vad_enabled = name === "voice-listening";
    snapshot.voice.tts = name === "voice-playing" ? "playing" : "idle";
    snapshot.voice.asr_partial = name === "voice-listening" ? "我正在说" : "";
  } else if (name === "performance-500") {
    messages = Array.from({ length: 500 }, (_, index) =>
      message(
        `message-${index + 1}`,
        firstConversation.conversation_id,
        index % 2 === 0 ? "user" : "character",
        index % 2 === 0 ? "user.text" : "character.speech",
        `第 ${index + 1} 条用于滚动性能测试的消息`,
      ),
    );
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, messages, []);
  } else if (name === "light-theme" || name === "dark-theme") {
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, []);
  } else if (name === "gate-default") {
    // V0.2 M4：默认账号（未设密码）→ 整屏账号门；可登录到演示账号进入应用
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, []);
    snapshot.current_account_id = defaultLocalAccount.account_id;
    snapshot.current_account = { ...defaultLocalAccount };
    snapshot.accounts = [
      { ...defaultLocalAccount, is_last_login: true },
      { ...demoAccount, is_last_login: false },
    ];
  } else if (name === "onboarding-pending") {
    // V0.2 M4：已注册账号但首次引导未完成 → 整屏 Onboarding
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, defaultMessages, []);
    const alice = {
      ...demoAccount,
      account_id: "alice-account",
      username: "alice",
      display_name: "爱丽丝",
      onboarding_complete: false,
    };
    snapshot.current_account_id = alice.account_id;
    snapshot.current_account = alice;
    snapshot.accounts = [
      { ...defaultLocalAccount, is_last_login: false },
      { ...alice, is_last_login: true },
    ];
  }

  return {
    name,
    label: name,
    snapshot,
    submitEvents: name === "chat-streaming" ? submitEvents(snapshot.current_conversation_id) : [],
  };
}
