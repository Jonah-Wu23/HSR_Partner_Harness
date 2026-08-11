import type {
  DesktopCommand,
  DesktopEvent,
  DesktopResponse,
  DesktopSnapshot,
} from "../contracts/protocol";
import type { DesktopBackend } from "./backend";
import { RequestIdFactory } from "./backend";
import {
  createMockScenario,
  type MockScenario,
  type MockScenarioName,
} from "../mocks/scenarios";

export class MockDesktopBackend implements DesktopBackend {
  private readonly listeners = new Set<(event: DesktopEvent) => void>();
  private readonly requestIds = new RequestIdFactory();
  private scenario: MockScenario;
  private sequence: number;

  constructor(scenarioName: MockScenarioName = "single-project") {
    this.scenario = createMockScenario(scenarioName);
    this.sequence = this.scenario.snapshot.sequence;
  }

  setScenario(name: MockScenarioName): void {
    this.scenario = createMockScenario(name);
    this.sequence = this.scenario.snapshot.sequence;
  }

  get scenarioName(): MockScenarioName {
    return this.scenario.name;
  }

  async request<T>(command: DesktopCommand): Promise<T> {
    let result: unknown;
    if (command.method === "app.bootstrap") {
      result = this.clone(this.scenario.snapshot);
    } else if (command.method === "app.shutdown") {
      result = { stopped: true };
    } else if (command.method === "chat.submit") {
      for (const event of this.scenario.submitEvents) this.emit(event.event, event.payload);
      result = {
        conversation_id: command.params.conversation_id,
        task_id: null,
        status: null,
      };
    } else if (command.method === "project.update_settings") {
      result = this.clone(this.scenario.snapshot);
    } else {
      result = this.clone(this.scenario.snapshot);
    }
    return result as T;
  }

  subscribe(listener: (event: DesktopEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event: DesktopEvent["event"], payload: Record<string, unknown>): void {
    const message: DesktopEvent = {
      kind: "event",
      event,
      sequence: this.sequence + 1,
      payload,
    };
    this.sequence += 1;
    for (const listener of this.listeners) listener(message);
  }

  private clone<T>(value: T): T {
    return JSON.parse(JSON.stringify(value)) as T;
  }

  nextRequestId(): string {
    return this.requestIds.next();
  }
}

export function isDesktopSnapshot(value: unknown): value is DesktopSnapshot {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as DesktopSnapshot).projects) &&
    typeof (value as DesktopSnapshot).current_conversation_id === "string"
  );
}
