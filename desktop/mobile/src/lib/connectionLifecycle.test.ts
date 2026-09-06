import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mobileWsClient, useMobileStore } from "./mobileStore";
import { getStoredToken, MobileWsClient, saveCredentials } from "./wsClient";

type Frame = {id: string; method: string};
class Socket {
  static instances: Socket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = 0;
  sent: Frame[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  constructor() { Socket.instances.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; }
  send(raw: string) {
    const frame = JSON.parse(raw) as Frame;
    this.sent.push(frame);
    if (frame.method === "power.get_status") {
      queueMicrotask(() => this.respond(frame, {supported:false, at_risk:false}));
    }
  }
  respond(frame: Frame, result: unknown = {}, error?: {code: string; message: string}) {
    this.onmessage?.({ data: JSON.stringify({ kind: "response", id: frame.id, ok: !error, result, error }) });
  }
}
const current = () => Socket.instances[Socket.instances.length - 1];
const find = (method: string) => current().sent.find(f => f.method === method)!;
const snapshot = { projects: [{project_id: "p", name: "Project", conversations: [{conversation_id: "c", project_id:"p", title:"Chat"}]}], messages: [], tool_runs: [], queue_items: [], approvals: [], sequence: 1 };

beforeEach(() => {
  vi.stubGlobal("WebSocket", Socket);
  window.localStorage.clear();
  useMobileStore.getState().disconnect();
  Socket.instances = [];
  window.localStorage.clear();
  useMobileStore.getState().start();
  mobileWsClient.connect();
  current().open();
});
afterEach(() => {
  window.localStorage.clear();
  useMobileStore.getState().disconnect();
  vi.unstubAllGlobals();
});

it("late close from an old socket cannot discard a new connection or its request", async () => {
  const client = new MobileWsClient();
  client.connect();
  const old = current(); old.open();
  client.disconnect(); client.connect();
  const fresh = current(); fresh.open();
  const outcome = client.request("ping").then(value => ({value}), error => ({error}));
  old.onclose?.();
  fresh.respond(fresh.sent[0], {alive:true});
  const result = await outcome;
  client.disconnect();
  expect(result).toEqual({value:{alive:true}});
});

it("pairing after unauthorized restores authenticated connection", async () => {
  const rejected = mobileWsClient.request("app.bootstrap");
  current().respond(find("app.bootstrap"), {}, {code:"unauthorized", message:"expired"});
  await expect(rejected).rejects.toThrow("expired");
  const pairing = useMobileStore.getState().pairDevice("123456", "Phone");
  await vi.waitFor(() => expect(find("remote.pair")).toBeDefined());
  current().respond(find("remote.pair"), {token:"new-token"});
  await vi.waitFor(() => expect(current().sent.filter(f=>f.method==="app.bootstrap")).toHaveLength(2));
  current().respond(current().sent.filter(f=>f.method==="app.bootstrap")[1], snapshot);
  await vi.waitFor(() => expect(find("remote.claim_control")).toBeDefined());
  current().respond(find("remote.claim_control"), {active:true});
  await pairing;
  expect(mobileWsClient.getState()).toBe("connected");
  expect(useMobileStore.getState().connection).toBe("connected");
});

it("control failure rejects pairing and does not leave bootstrap complete", async () => {
  const outcome = useMobileStore.getState().pairDevice("123456", "Phone").then(()=>"success", error=>error.message);
  await vi.waitFor(() => expect(find("remote.pair")).toBeDefined());
  current().respond(find("remote.pair"), {token:"token"});
  await vi.waitFor(() => expect(find("app.bootstrap")).toBeDefined());
  current().respond(find("app.bootstrap"), snapshot);
  await vi.waitFor(() => expect(find("remote.claim_control")).toBeDefined());
  current().respond(find("remote.claim_control"), {}, {code:"control_failed", message:"control failed"});
  expect(await outcome).toBe("control failed");
  expect(useMobileStore.getState().bootstrapped).toBe(false);
});

it("reconnect with active chat claims control before synchronization completes", async () => {
  saveCredentials("token", "Phone");
  useMobileStore.setState({activeConversationId:"c"});
  useMobileStore.getState().reconnect(); current().open();
  current().respond(find("app.bootstrap"), snapshot);
  await vi.waitFor(() => {
    const claim = find("remote.claim_control");
    if (claim) current().respond(claim, {active:true});
    expect(find("conversation.open")).toBeDefined();
  });
  current().respond(find("conversation.open"), {messages:[],tool_runs:[],queue_items:[],pair:null,active_task:null,sequence:1});
  await vi.waitFor(() => expect(useMobileStore.getState().bootstrapped).toBe(true));
  expect(find("remote.claim_control")).toBeDefined();
});

it("reconnect starts a fresh bootstrap while the old control request is pending", async () => {
  saveCredentials("token", "Phone");
  useMobileStore.getState().reconnect(); current().open();
  current().respond(find("app.bootstrap"), snapshot);
  await vi.waitFor(() => expect(find("remote.claim_control")).toBeDefined());
  useMobileStore.getState().reconnect(); current().open();
  expect(find("app.bootstrap")).toBeDefined();
  current().respond(find("app.bootstrap"), snapshot);
  await vi.waitFor(() => expect(find("remote.claim_control")).toBeDefined());
  current().respond(find("remote.claim_control"), {active:true});
  await vi.waitFor(() => expect(useMobileStore.getState().bootstrapped).toBe(true));
});

it("disconnect preserves credentials until release acknowledgement", async () => {
  saveCredentials("token", "Phone");
  const pending = useMobileStore.getState().disconnect();
  await vi.waitFor(() => expect(find("remote.release_control")).toBeDefined());
  expect(getStoredToken()).toBe("token");
  expect(current().readyState).toBe(Socket.OPEN);
  current().respond(find("remote.release_control"), {released:true, active_controllers:0});
  await pending;
  expect(getStoredToken()).toBeNull();
  expect(mobileWsClient.getState()).toBe("disconnected");
});

it("release failure preserves credentials and surfaces the remote error", async () => {
  saveCredentials("token", "Phone");
  const outcome = useMobileStore.getState().disconnect().then(()=>"success", error=>error.message);
  await vi.waitFor(() => expect(find("remote.release_control")).toBeDefined());
  current().respond(find("remote.release_control"), {}, {code:"internal_error", message:"release failed"});
  expect(await outcome).toBe("release failed");
  expect(getStoredToken()).toBe("token");
  expect(current().readyState).toBe(Socket.OPEN);
});

it("server-confirmed unauthorized permits clearing revoked credentials", async () => {
  saveCredentials("revoked-token", "Phone");
  const pending = useMobileStore.getState().disconnect();
  await vi.waitFor(() => expect(find("remote.release_control")).toBeDefined());
  current().respond(find("remote.release_control"), {}, {code:"unauthorized", message:"revoked"});
  await pending;
  expect(getStoredToken()).toBeNull();
});
