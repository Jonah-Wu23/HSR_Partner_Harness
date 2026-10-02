import type { DesktopCommand } from "../contracts/protocol";
import type { DesktopBackend } from "../services/backend";

export interface FakeBackendOptions {
  /** 文件选择对话框的返回；null 表示用户取消。 */
  pickFileResult?: string | null;
  /** 保存对话框的返回；null 表示用户取消。 */
  saveFileResult?: string | null;
}

/**
 * 按 JSONL 请求/响应回放的后端夹具：记录下发的命令，respond 的返回值即响应帧的 result，
 * respond 抛出 DesktopRequestError 即错误帧。没有事件流；需要事件或有状态的协议时用 MockDesktopBackend。
 */
export function fakeBackend(
  respond: (command: DesktopCommand) => unknown,
  options: FakeBackendOptions = {},
): { backend: DesktopBackend; commands: DesktopCommand[] } {
  const commands: DesktopCommand[] = [];
  const backend: DesktopBackend = {
    async request<T>(command: DesktopCommand): Promise<T> {
      commands.push(command);
      return respond(command) as T;
    },
    async openChatWindow(): Promise<string> {
      throw new Error("独立聊天窗口需要在 Tauri 桌面运行时打开");
    },
    async pickFolder(): Promise<string | null> {
      return null;
    },
    async pickFile(): Promise<string | null> {
      return options.pickFileResult ?? null;
    },
    async saveFile(): Promise<string | null> {
      return options.saveFileResult ?? null;
    },
    subscribe: () => () => undefined,
    async reconnectSidecar(): Promise<void> {},
  };
  return { backend, commands };
}

/** respond 里遇到用例没有准备的命令时抛出，让多余或拼错的请求直接失败。 */
export function unexpectedCommand(command: DesktopCommand): never {
  throw new Error(`用例未准备 ${command.method} 的响应`);
}
