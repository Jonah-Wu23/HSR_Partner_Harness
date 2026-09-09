import type {
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PairRecord,
  ProjectRecord,
  ToolRun,
} from "../contracts/protocol";

export const MOCK_SCENARIO_NAMES = [
  "empty",
  "single-project",
  "many-projects",
  "multi-pair",
  "invalid-path",
  "chat-streaming",
  "collaboration-running",
  "dual-chat-running",
  "tabbed-window",
  "task-succeeded",
  "task-failed",
  "task-cancelled",
  "approval-request",
  "approval-review",
  "approval-full-auto",
  "voice-listening",
  "voice-playing",
  "performance-500",
  "message-failed",
  "background-tasks",
  "perf-many-conversations",
  "perf-many-projects",
  "perf-long-workbench",
  "light-theme",
  "dark-theme",
  "gate-default",
  "onboarding-pending",
] as const;

export type MockScenarioName = (typeof MOCK_SCENARIO_NAMES)[number];

export interface MockScenario {
  name: MockScenarioName;
  label: string;
  snapshot: DesktopSnapshot;
  submitEvents: DesktopEvent[];
  /** V0.3.2 M5：窗口视图状态示例（tabbed-window 等多标签场景）；
      测试/演示用它播种 store 的 viewId/openConversationIds/activeConversationId。 */
  viewState?: {
    viewId: string;
    openConversationIds: string[];
    activeConversationId: string | null;
  };
}

export const MOCK_PAIRS: PairRecord[] = [
  {
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
  },
  {
    pair_id: "firefly_sam",
    character: { id: "firefly", name: "流萤", voice_id: "demo-firefly" },
    assistant: {
      id: "sam",
      name: "萨姆",
      voice_id: "demo-sam",
    },
    theme: {
      character_text: "#D1FAE5",
      character_primary: "#52D1A3",
      character_deep: "#1B4738",
      character_active: "#22C58B",
      assistant_primary: "#E65A28",
      assistant_bright: "#FF844B",
      assistant_shadow: "#9C3210",
    },
  },
  {
    pair_id: "march7_fourth_mirror",
    character: { id: "march7", name: "三月七", voice_id: "demo-march7" },
    assistant: {
      id: "fourth_mirror",
      name: "第四面镜",
      voice_id: "demo-fourth-mirror",
    },
    theme: {
      character_text: "#FFE4EC",
      character_primary: "#FF8DA1",
      character_deep: "#542031",
      character_active: "#F43F5E",
      assistant_primary: "#A78BFA",
      assistant_bright: "#C4B5FD",
      assistant_shadow: "#6D28D9",
    },
  },
];

const pair: PairRecord = MOCK_PAIRS[0];

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
  pairId: string = pair.pair_id,
): ProjectRecord["conversations"][number] {
  return {
    conversation_id: id,
    project_id: projectId,
    pair_id: pairId,
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
  pairId: string = pair.pair_id,
): Message {
  return {
    message_id: id,
    conversation_id: conversationId,
    pair_id: pairId,
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
  taskId = "mock-task-1",
): ToolRun {
  return {
    tool_call_id: `mock-tool-${taskId}`,
    conversation_id: conversationId,
    task_id: taskId,
    engine_turn_id: `mock-turn-${taskId}`,
    sequence: 2,
    status,
    title: "检查项目文件",
    summary: status === "running" ? "正在读取项目状态" : "项目检查已完成",
    details: "mock backend 记录；不访问真实文件系统。",
    timeline_order: status === "running" ? 2 : null,
  };
}

function baseSnapshot(
  projects: ProjectRecord[],
  conversationId: string,
  messages: Message[] = [],
  toolRuns: ToolRun[] = [],
  pairOverride?: PairRecord,
): DesktopSnapshot {
  const currentProject = projects.find((item) =>
    item.conversations.some((item) => item.conversation_id === conversationId),
  );
  const currentConversation = currentProject?.conversations.find(
    (item) => item.conversation_id === conversationId,
  );
  const fallbackProject = currentProject ?? projects[0];
  const fallbackConversation = currentConversation ?? fallbackProject?.conversations[0];
  const activePair = pairOverride ?? pair;
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
      pair_id: activePair.pair_id,
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
    // V0.3.2 M5：新协议快照始终携带 active_tasks 全量集合（与 active_task/busy 一致）
    active_tasks: [],
    busy: false,
    approvals: [],
    voice: {
      supported: true,
      enabled: true,
      assistant_voice_enabled: false,
      vad: "idle",
      vad_enabled: false,
      ptt: false,
      tts: "idle",
      asr_partial: "",
      error: null,
      // V0.2 M4：待播队列条数（VoiceMiniPlayer 的 queuedCount）
      speech_queue_len: 0,
    },
    pair: activePair,
    pairs: MOCK_PAIRS,
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
  } else if (name === "multi-pair") {
    const conv1 = conversation(
      "conv-phainon",
      "project-1",
      "白厄与古代机械 - 麦田日常",
      "phainon_ancient_machine",
    );
    const conv2 = conversation(
      "conv-firefly",
      "project-1",
      "流萤与萨姆 - 苍穹与甜点",
      "firefly_sam",
    );
    const conv3 = conversation(
      "conv-march7",
      "project-1",
      "三月七与第四面镜 - 冰晶摄影",
      "march7_fourth_mirror",
    );
    projects = [
      project("project-1", "多搭档联合项目", "C:/Projects/hsr-partners", [
        conv1,
        conv2,
        conv3,
      ]),
    ];
    messages = [
      message("msg-p-1", "conv-phainon", "user", "user.text", "小白，今天去哪训练？", "phainon_ancient_machine"),
      message("msg-p-2", "conv-phainon", "character", "character.speech", "先去广场转转，听说西塔罗斯先生又进了一批老物件。", "phainon_ancient_machine"),
      message("msg-f-1", "conv-firefly", "user", "user.text", "流萤，今天感觉怎么样？", "firefly_sam"),
      message("msg-f-2", "conv-firefly", "character", "character.speech", "我很好。刚才去买了橡木蛋糕卷，分你一半。", "firefly_sam"),
      message("msg-m-1", "conv-march7", "user", "user.text", "三月，拍到好照片了吗？", "march7_fourth_mirror"),
      message("msg-m-2", "conv-march7", "character", "character.speech", "本姑娘出马当然拍到啦，看，这张构图绝了吧！", "march7_fourth_mirror"),
    ];
    snapshot = baseSnapshot(projects, "conv-firefly", messages, [], MOCK_PAIRS[1]);
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
    snapshot.active_tasks = [snapshot.active_task];
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
  } else if (name === "message-failed") {
    // V0.3.9 V01：消息真实终态离线样例——failed 带原始 error，cancelled 带 cancelled_reason。
    messages = [
      message("message-1", firstConversation.conversation_id, "user", "user.text", "帮我看看这个项目"),
      {
        ...message(
          "message-2",
          firstConversation.conversation_id,
          "character",
          "character.speech",
          "好，我和你一起看。",
        ),
        status: "done",
      },
      {
        ...message(
          "message-3",
          firstConversation.conversation_id,
          "user",
          "user.text",
          "再帮我跑一次测试",
        ),
        status: "failed",
        payload: { error: "dialogue provider 返回 500：internal server error" },
      },
      {
        ...message(
          "message-4",
          firstConversation.conversation_id,
          "character",
          "character.speech",
          "（这条回复被取消）",
        ),
        status: "cancelled",
        payload: { cancelled_reason: "用户取消了任务" },
      },
      {
        ...message(
          "message-5",
          firstConversation.conversation_id,
          "user",
          "user.text",
          "这条还在排队",
        ),
        status: "queued",
      },
      {
        ...message(
          "message-6",
          firstConversation.conversation_id,
          "character",
          "character.speech",
          "（失败但服务端没有给出错误详情）",
        ),
        status: "failed",
        payload: {},
      },
    ];
    snapshot = baseSnapshot(projects, firstConversation.conversation_id, messages, []);
  } else if (name === "background-tasks") {
    // V0.3.9 V01：跨聊天后台任务与审批归属离线样例（两个项目、四个聊天）。
    const convA = conversation("conv-1", "project-1", "奥赫玛的项目聊天");
    const convB = conversation("conv-2", "project-1", "星穹项目：长世界书校对");
    const convC = conversation("conv-3", "project-2", "流萤的甜点配方");
    const convD = conversation("conv-4", "project-2", "三月七的照片归档");
    projects = [
      project("project-1", "星穹项目", "C:/Projects/astral", [convA, convB]),
      project("project-2", "日常项目", "C:/Projects/daily", [convC, convD]),
    ];
    messages = [
      message("msg-a-1", convA.conversation_id, "user", "user.text", "帮我看看这个项目"),
      message("msg-a-2", convA.conversation_id, "character", "character.speech", "好，我和你一起看。"),
      message("msg-c-1", convC.conversation_id, "user", "user.text", "流萤，今天想吃什么？"),
      message("msg-c-2", convC.conversation_id, "character", "character.speech", "橡木蛋糕卷。"),
    ];
    snapshot = baseSnapshot(projects, convA.conversation_id, messages, []);
    snapshot.active_tasks = [
      {
        project_id: "project-1",
        conversation_id: convB.conversation_id,
        task_id: "task-b",
        engine_turn_id: "turn-b",
      },
      {
        project_id: "project-2",
        conversation_id: convC.conversation_id,
        task_id: "task-c",
        engine_turn_id: "turn-c",
      },
    ];
    snapshot.active_task = snapshot.active_tasks[0];
    snapshot.busy = true;
    snapshot.approvals = [
      {
        approval_id: "approval-current",
        conversation_id: convA.conversation_id,
        operation: {
          tool_kind: "shell",
          command: "pytest -q",
          paths: [],
          patch_file_count: null,
          summary: "当前聊天里的测试命令",
        },
        reason: "当前聊天需要审批",
        task_id: "task-a",
      },
      {
        approval_id: "approval-other-1",
        conversation_id: convC.conversation_id,
        operation: {
          tool_kind: "file_write",
          command: null,
          paths: ["C:/Projects/daily/recipe.md"],
          patch_file_count: 1,
          summary: "写入甜点配方",
        },
        reason: "另一个聊天需要审批",
        task_id: "task-c",
      },
      {
        approval_id: "approval-other-2",
        conversation_id: convC.conversation_id,
        operation: {
          tool_kind: "file_delete",
          command: null,
          paths: ["C:/Projects/daily/old.md"],
          patch_file_count: null,
          summary: "删除旧文件",
        },
        reason: "同一个聊天里的第二条待审批",
        task_id: "task-c",
      },
    ];
  } else if (name === "perf-many-conversations") {
    // V0.3.9 V05：导航聊天列表负载样例（单项目 400 个聊天）。
    const manyConversations = Array.from({ length: 400 }, (_, index) =>
      conversation(
        `conv-${index + 1}`,
        "project-1",
        `聊天 ${index + 1}：用于导航列表负载测试的较长标题`,
      ),
    );
    projects = [
      project("project-1", "大量聊天的项目", "C:/Projects/many-conversations", manyConversations),
    ];
    snapshot = baseSnapshot(projects, "conv-1", [], []);
  } else if (name === "perf-many-projects") {
    // V0.3.9 V05：项目轨道负载样例（200 个项目，每项目 2 个聊天）。
    projects = Array.from({ length: 200 }, (_, index) => {
      const projectId = `project-${index + 1}`;
      return project(
        projectId,
        `项目 ${index + 1}：用于项目轨道负载测试`,
        `C:/Projects/project-${index + 1}`,
        [
          conversation(`${projectId}-conversation-1`, projectId, "聊天 1"),
          conversation(`${projectId}-conversation-2`, projectId, "聊天 2"),
        ],
      );
    });
    snapshot = baseSnapshot(projects, "project-1-conversation-1", [], []);
  } else if (name === "perf-long-workbench") {
    // V0.3.9 V05：工作台时间线负载样例（800 条助手消息 + 800 条工具记录）。
    const characterMessages = Array.from({ length: 40 }, (_, index) =>
      message(
        `char-${index + 1}`,
        firstConversation.conversation_id,
        index % 2 === 0 ? "user" : "character",
        index % 2 === 0 ? "user.text" : "character.speech",
        `角色区消息 ${index + 1}`,
      ),
    );
    const assistantMessages = Array.from({ length: 800 }, (_, index) => ({
      ...message(
        `assistant-${index + 1}`,
        firstConversation.conversation_id,
        "assistant",
        "assistant.natural_language",
        `助手工作台消息 ${index + 1}`,
      ),
      timeline_order: index * 2,
    }));
    tools = Array.from({ length: 800 }, (_, index) => ({
      ...toolRun(firstConversation.conversation_id, "succeeded"),
      tool_call_id: `tool-${index + 1}`,
      engine_turn_id: `turn-${index + 1}`,
      sequence: index,
      timeline_order: index * 2 + 1,
    }));
    snapshot = baseSnapshot(
      projects,
      firstConversation.conversation_id,
      [...characterMessages, ...assistantMessages],
      tools,
    );
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
