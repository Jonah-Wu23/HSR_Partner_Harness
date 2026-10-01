import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  ConversationOpenResult,
  ConversationRecord,
  DesktopSnapshot,
  PairRecord,
  PowerStatusPayload,
} from "@shared/contracts/protocol";
import { FakeWebSocket, installFakeWebSocket, latestSocket } from "../test/fakeWebSocket";
import { mobileWsClient, useMobileStore } from "./mobileStore";
import { getStoredToken, MobileWsClient, saveCredentials } from "./wsClient";

const CONVERSATION: ConversationRecord = {
  conversation_id: "c",
  project_id: "p",
  pair_id: "pair-default",
  title: "Chat",
  last_mode: "chat",
  archived: false,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const PROJECT = {
  project_id: "p",
  name: "Project",
  root_path: "D:/project",
  approval_mode: "request_approval",
  reasoning_effort: "medium",
  archived: false,
  created_at: null,
  last_opened_at: null,
  path_available: true,
} as const;

const PAIR: PairRecord = {
  pair_id: "pair-default",
  character: { id: "phainon", name: "白厄", voice_id: "" },
  assistant: { id: "fourth_mirror", name: "第四面镜", voice_id: "" },
  theme: {
    character_text: "#fff",
    character_primary: "#ffd",
    character_deep: "#aa8",
    character_active: "#ff0",
    assistant_primary: "#aaf",
    assistant_bright: "#ccf",
    assistant_shadow: "#558",
  },
};

const SNAPSHOT = {
  projects: [{ ...PROJECT, conversations: [CONVERSATION] }],
  current_conversation_id: "",
  messages: [],
  tool_runs: [],
  queue_items: [],
  approvals: [],
  active_task: null,
  active_tasks: [],
  remote_control: { state: "free", device_key: null, expires_at: null, grace_expires_at: null, reason: null },
  sequence: 1,
  stream_id: "s",
} as unknown as DesktopSnapshot;

const OPEN_RESULT: ConversationOpenResult = {
  conversation: CONVERSATION,
  project: PROJECT,
  pair: PAIR,
  messages: [],
  tool_runs: [],
  turns: [],
  queue_items: [],
  active_task: null,
  sequence: 1,
  stream_id: "s",
};

const POWER_STATUS: PowerStatusPayload = {
  supported: false,
  platform: "linux",
  plan_name: "",
  ac_sleep_timeout_seconds: null,
  dc_sleep_timeout_seconds: null,
  remote_serve_enabled: true,
  threshold_seconds: 900,
  at_risk: false,
  reason: "",
  checked_at: "2026-09-01T00:00:00",
  warnings: [],
};

const CLAIMED = { claimed: true, active_controllers: 1 };

beforeEach(async () => {
  installFakeWebSocket();
  // 同步成功后 store 主动拉一次电源状态，与本文件的连接流程无关，自动应答。
  FakeWebSocket.autoResults.set("power.get_status", POWER_STATUS);
  window.localStorage.clear();
  await useMobileStore.getState().disconnect();
  useMobileStore.getState().start();
  mobileWsClient.connect();
  latestSocket().open();
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

it("旧 socket 迟到的关闭回调不影响新连接及其请求", async () => {
  const client = new MobileWsClient();
  client.connect();
  const old = latestSocket();
  old.open();
  client.disconnect();
  client.connect();
  const fresh = latestSocket();
  fresh.open();
  const outcome = client.request("ping");
  old.onclose?.();
  fresh.respond(fresh.lastFrame("ping"), { server_time: "2026-09-01T00:00:00+00:00" });
  await expect(outcome).resolves.toEqual({ server_time: "2026-09-01T00:00:00+00:00" });
  client.disconnect();
});

it("鉴权失败后配对在新连接上发出 remote.pair，同步完成后恢复连接", async () => {
  saveCredentials("revoked-token", "Phone");
  const sync = useMobileStore.getState().retrySync();
  const failedSocket = latestSocket();
  failedSocket.respondError(failedSocket.lastFrame("app.bootstrap"), "unauthorized", "revoked_token");
  await expect(sync).rejects.toThrow("revoked_token");
  expect(useMobileStore.getState().connection).toBe("auth_failed");

  const pairing = useMobileStore.getState().pairDevice("123456", "Phone");
  expect(latestSocket()).not.toBe(failedSocket);
  latestSocket().open();
  await vi.waitFor(() => latestSocket().lastFrame("remote.pair"));
  const pairFrame = latestSocket().lastFrame("remote.pair");
  expect(pairFrame.params).toEqual({ code: "123456", device_name: "Phone" });
  expect(pairFrame).not.toHaveProperty("auth");
  latestSocket().respond(pairFrame, { token: "new-token" });
  await vi.waitFor(() => latestSocket().lastFrame("app.bootstrap"));
  latestSocket().respond(latestSocket().lastFrame("app.bootstrap"), SNAPSHOT);
  await vi.waitFor(() => latestSocket().lastFrame("remote.claim_control"));
  latestSocket().respond(latestSocket().lastFrame("remote.claim_control"), CLAIMED);
  await pairing;

  expect(mobileWsClient.getState()).toBe("connected");
  expect(useMobileStore.getState()).toMatchObject({ connection: "connected", deviceName: "Phone" });
  expect(getStoredToken()).toBe("new-token");
});

it("控制声明失败时配对失败，同步不标记完成", async () => {
  const outcome = useMobileStore.getState().pairDevice("123456", "Phone");
  latestSocket().open();
  await vi.waitFor(() => latestSocket().lastFrame("remote.pair"));
  latestSocket().respond(latestSocket().lastFrame("remote.pair"), { token: "token" });
  await vi.waitFor(() => latestSocket().lastFrame("app.bootstrap"));
  latestSocket().respond(latestSocket().lastFrame("app.bootstrap"), SNAPSHOT);
  await vi.waitFor(() => latestSocket().lastFrame("remote.claim_control"));
  latestSocket().respondError(
    latestSocket().lastFrame("remote.claim_control"),
    "remote_identity_required",
    "远程控制需要已鉴权设备身份",
  );

  await expect(outcome).rejects.toThrow("远程控制需要已鉴权设备身份");
  expect(useMobileStore.getState().bootstrapped).toBe(false);
});

it("打开着聊天时重连，控制声明成功后才装载该聊天", async () => {
  saveCredentials("token", "Phone");
  useMobileStore.setState({ activeConversationId: "c" });
  useMobileStore.getState().reconnect();
  latestSocket().open();
  latestSocket().respond(latestSocket().lastFrame("app.bootstrap"), SNAPSHOT);
  await vi.waitFor(() => latestSocket().lastFrame("remote.claim_control"));
  expect(latestSocket().sentFrames("conversation.open")).toEqual([]);
  latestSocket().respond(latestSocket().lastFrame("remote.claim_control"), CLAIMED);
  await vi.waitFor(() => latestSocket().lastFrame("conversation.open"));
  latestSocket().respond(latestSocket().lastFrame("conversation.open"), OPEN_RESULT);
  await vi.waitFor(() =>
    expect(useMobileStore.getState()).toMatchObject({
      bootstrapped: true,
      timelineLoading: false,
      pair: PAIR,
    }),
  );
});

it("控制声明在途时再次重连，新连接重新同步并完成", async () => {
  saveCredentials("token", "Phone");
  useMobileStore.getState().reconnect();
  latestSocket().open();
  latestSocket().respond(latestSocket().lastFrame("app.bootstrap"), SNAPSHOT);
  await vi.waitFor(() => latestSocket().lastFrame("remote.claim_control"));

  useMobileStore.getState().reconnect();
  latestSocket().open();
  latestSocket().respond(latestSocket().lastFrame("app.bootstrap"), SNAPSHOT);
  await vi.waitFor(() => latestSocket().lastFrame("remote.claim_control"));
  latestSocket().respond(latestSocket().lastFrame("remote.claim_control"), CLAIMED);
  await vi.waitFor(() => expect(useMobileStore.getState().bootstrapped).toBe(true));
});

it("断开连接时收到释放控制的确认后才清除凭据", async () => {
  saveCredentials("token", "Phone");
  const pending = useMobileStore.getState().disconnect();
  await vi.waitFor(() => latestSocket().lastFrame("remote.release_control"));
  expect(getStoredToken()).toBe("token");
  expect(latestSocket().readyState).toBe(FakeWebSocket.OPEN);

  latestSocket().respond(latestSocket().lastFrame("remote.release_control"), {
    released: true,
    active_controllers: 0,
  });
  await pending;
  expect(getStoredToken()).toBeNull();
  expect(mobileWsClient.getState()).toBe("disconnected");
});

it("释放控制失败时保留凭据与连接并抛出服务端错误", async () => {
  saveCredentials("token", "Phone");
  const outcome = useMobileStore.getState().disconnect();
  await vi.waitFor(() => latestSocket().lastFrame("remote.release_control"));
  latestSocket().respondError(
    latestSocket().lastFrame("remote.release_control"),
    "internal_error",
    "release failed",
  );

  await expect(outcome).rejects.toThrow("release failed");
  expect(getStoredToken()).toBe("token");
  expect(latestSocket().readyState).toBe(FakeWebSocket.OPEN);
});

it("服务端以 unauthorized 拒绝释放时照常清除已撤销的凭据", async () => {
  saveCredentials("revoked-token", "Phone");
  const pending = useMobileStore.getState().disconnect();
  await vi.waitFor(() => latestSocket().lastFrame("remote.release_control"));
  latestSocket().respondError(
    latestSocket().lastFrame("remote.release_control"),
    "unauthorized",
    "revoked_token",
  );

  await pending;
  expect(getStoredToken()).toBeNull();
});
