import { useEffect, useState } from "react";
import {
  detectShellEnvironment,
  probeNotificationCapability,
  requestNotificationPermission,
} from "../lib/shellCapabilities";
import "./NotificationPreferences.css";

/**
 * V0.3.7 通知偏好设置（V8 前置组件）。
 *
 * 三类通知对应冻结 §2.3 的事件源（壳内本地判定，不新增 Sidecar 协议）：
 * - 任务完成 = message.finalized / turn.status_changed；
 * - 委派结果 = message.finalized（委派 target）；
 * - 审批请求 = approval.requested。
 *
 * 能力探测先行（冻结 §9.1/§9.2）：
 * - PWA：如实说明「本地通知仅在 Android 壳内可用」，不渲染任何开关；
 * - 壳内插件不可用：如实说明，同样不渲染开关；
 * - 壳内插件可用：可编辑偏好。偏好先以 localStorage 持久化（键 phm.notificationPreferences.v1），
 *   接线阶段由壳层把「启用 + 提醒方式」映射为 Android 通知渠道，并经 onPreferencesChange
 *   通知壳内通知规则引擎，本组件不再扩展其他协议。
 */

export type NotificationImportance = "high" | "default" | "silent";

export interface NotificationPreferenceItem {
  enabled: boolean;
  /** high=弹出并响铃 / default=通知栏提醒 / silent=静默（免打扰，仅通知栏展示）。 */
  importance: NotificationImportance;
}

export type NotificationTypeKey =
  | "taskCompleted"
  | "delegationResult"
  | "approvalRequested";

export interface NotificationPreferencesState {
  taskCompleted: NotificationPreferenceItem;
  delegationResult: NotificationPreferenceItem;
  approvalRequested: NotificationPreferenceItem;
}

export const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferencesState = {
  taskCompleted: { enabled: true, importance: "default" },
  delegationResult: { enabled: true, importance: "default" },
  approvalRequested: { enabled: true, importance: "high" },
};

interface NotificationTypeMeta {
  key: NotificationTypeKey;
  title: string;
  description: string;
}

export const NOTIFICATION_TYPES: readonly NotificationTypeMeta[] = [
  {
    key: "taskCompleted",
    title: "任务完成",
    description: "角色或助手结束一轮对话/任务时提醒",
  },
  {
    key: "delegationResult",
    title: "委派结果",
    description: "委派给工具或角色的任务产生结果时提醒",
  },
  {
    key: "approvalRequested",
    title: "审批请求",
    description: "需要你在手机上批准或拒绝的请求，建议保持开启",
  },
];

const IMPORTANCE_OPTIONS: ReadonlyArray<{
  value: NotificationImportance;
  label: string;
}> = [
  { value: "high", label: "高优先级（弹出并响铃）" },
  { value: "default", label: "常规（通知栏提醒）" },
  { value: "silent", label: "静默（仅通知栏，免打扰）" },
];

const STORAGE_KEY = "phm.notificationPreferences.v1";

function readStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function normalizeItem(value: unknown): NotificationPreferenceItem | null {
  if (!value || typeof value !== "object") return null;
  const record = value as { enabled?: unknown; importance?: unknown };
  if (typeof record.enabled !== "boolean") return null;
  if (
    record.importance !== "high" &&
    record.importance !== "default" &&
    record.importance !== "silent"
  ) {
    return null;
  }
  return { enabled: record.enabled, importance: record.importance };
}

export function loadNotificationPreferences(): NotificationPreferencesState {
  const raw = readStorage()?.getItem(STORAGE_KEY) ?? null;
  if (raw === null) {
    return { ...DEFAULT_NOTIFICATION_PREFERENCES };
  }
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(raw) as Record<string, unknown>;
  } catch (error) {
    console.warn("[NotificationPreferences] 本地通知偏好解析失败，按默认值处理：", error);
    return { ...DEFAULT_NOTIFICATION_PREFERENCES };
  }
  const next: NotificationPreferencesState = { ...DEFAULT_NOTIFICATION_PREFERENCES };
  let repaired = false;
  for (const meta of NOTIFICATION_TYPES) {
    const item = normalizeItem(parsed[meta.key]);
    if (item) {
      next[meta.key] = item;
    } else if (parsed[meta.key] !== undefined) {
      repaired = true;
    }
  }
  if (repaired) {
    console.warn(`[NotificationPreferences] 本地通知偏好存在无法识别的取值，对应项按默认值处理：${raw}`);
  }
  return next;
}

export function saveNotificationPreferences(
  preferences: NotificationPreferencesState,
): void {
  const store = readStorage();
  if (!store) return;
  store.setItem(STORAGE_KEY, JSON.stringify(preferences));
}

type ProbePhase =
  | { stage: "probing" }
  | { stage: "unavailable"; reason: "not_shell" | "plugin_unavailable" }
  | { stage: "ready"; permissionGranted: boolean };

export interface NotificationPreferencesProps {
  /** 接线阶段可注入初始偏好（如由壳层配置下发）；缺省从 localStorage 读取。 */
  initialPreferences?: NotificationPreferencesState;
  /** 偏好实际变更时回调（接线阶段接入壳内通知规则引擎）。 */
  onPreferencesChange?: (preferences: NotificationPreferencesState) => void;
}

export function NotificationPreferences({
  initialPreferences,
  onPreferencesChange,
}: NotificationPreferencesProps) {
  const [phase, setPhase] = useState<ProbePhase>({ stage: "probing" });
  const [preferences, setPreferences] = useState<NotificationPreferencesState>(() => ({
    ...(initialPreferences ?? loadNotificationPreferences()),
  }));
  const [requesting, setRequesting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const isAndroid = detectShellEnvironment() === "android_shell";

  useEffect(() => {
    let cancelled = false;
    probeNotificationCapability().then((capability) => {
      if (cancelled) return;
      if (capability.kind === "ready") {
        setPhase({ stage: "ready", permissionGranted: capability.permission_granted });
      } else {
        setPhase({ stage: "unavailable", reason: capability.reason });
      }
    });
    // probeNotificationCapability 约定不抛错；一旦违反约定，按不可用处理并保留原始错误。
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (initialPreferences) {
      setPreferences({ ...initialPreferences });
    }
  }, [initialPreferences]);

  const updateItem = (
    key: NotificationTypeKey,
    patch: Partial<NotificationPreferenceItem>,
  ) => {
    const next: NotificationPreferencesState = {
      ...preferences,
      [key]: { ...preferences[key], ...patch },
    };
    setPreferences(next);
    saveNotificationPreferences(next);
    onPreferencesChange?.(next);
  };

  const handleRequestPermission = async () => {
    setRequesting(true);
    setRequestError(null);
    try {
      const granted = await requestNotificationPermission();
      if (granted) {
        setPhase({ stage: "ready", permissionGranted: true });
      } else {
        setRequestError(
          "仍未获得系统通知权限。若手机此前弹过「拒绝」提示，请到 系统设置 → 应用 → 通知 中手动开启后重试。",
        );
      }
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setRequesting(false);
    }
  };

  return (
    <section
      className="card notif-prefs"
      aria-label="通知偏好设置"
      data-testid="notification-preferences"
    >
      <h2 className="notif-prefs-title">通知偏好</h2>

      {phase.stage === "probing" ? (
        <p className="hint" data-testid="notif-probing">
          正在检测当前环境的通知能力…
        </p>
      ) : null}

      {phase.stage === "unavailable" && phase.reason === "not_shell" ? (
        <div className="notif-unavailable" data-testid="notif-unavailable-pwa">
          <p className="notif-unavailable-main">本地通知仅在 Android 壳内可用。</p>
          <p className="hint">
            当前在浏览器中使用：页面关闭后无法弹出系统通知，只有打开应用时才能看到新消息。
            以下三类通知可在 Android 壳内配置：
          </p>
          <ul className="notif-type-brief">
            {NOTIFICATION_TYPES.map((meta) => (
              <li key={meta.key}>{meta.title}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {phase.stage === "unavailable" && phase.reason === "plugin_unavailable" ? (
        <p className="notif-unavailable" data-testid="notif-unavailable-plugin">
          当前壳内未能加载通知能力，通知偏好暂不可编辑。通知功能需要应用内置通知插件后才会生效。
        </p>
      ) : null}

      {phase.stage === "ready" ? (
        <>
          {phase.permissionGranted ? (
            <p className="notif-permission-ok" data-testid="notif-permission-granted">
              已获得系统通知权限
            </p>
          ) : (
            <div
              className="notif-permission-missing"
              data-testid="notif-permission-missing"
            >
              <p>
                尚未获得系统通知权限：未授权时，锁屏与后台收不到审批请求、任务完成等通知。
              </p>
              <button
                type="button"
                className="notif-btn"
                onClick={handleRequestPermission}
                disabled={requesting}
                data-testid="btn-request-permission"
              >
                {requesting ? "正在申请权限…" : "申请通知权限"}
              </button>
              {requestError ? (
                <p
                  className="notif-permission-error"
                  role="alert"
                  data-testid="notif-permission-error"
                >
                  {requestError}
                </p>
              ) : null}
            </div>
          )}

          <ul className="notif-type-list">
            {NOTIFICATION_TYPES.map((meta) => {
              const item = preferences[meta.key];
              return (
                <li
                  key={meta.key}
                  className="notif-type-row"
                  data-testid={`notif-row-${meta.key}`}
                >
                  <div className="notif-type-text">
                    <span className="notif-type-title">{meta.title}</span>
                    <span className="hint">{meta.description}</span>
                  </div>
                  <div className="notif-type-controls">
                    <label className="notif-switch">
                      <input
                        type="checkbox"
                        checked={item.enabled}
                        onChange={(event) =>
                          updateItem(meta.key, { enabled: event.target.checked })
                        }
                        data-testid={`notif-toggle-${meta.key}`}
                      />
                      <span>{item.enabled ? "已开启" : "已关闭"}</span>
                    </label>
                    <label className="notif-importance">
                      <span className="hint">提醒方式</span>
                      <select
                        value={item.importance}
                        onChange={(event) =>
                          updateItem(meta.key, {
                            importance: event.target
                              .value as NotificationImportance,
                          })
                        }
                        disabled={!item.enabled}
                        aria-label={`${meta.title}的提醒方式`}
                        data-testid={`notif-importance-${meta.key}`}
                      >
                        {IMPORTANCE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}

      {isAndroid ? (
        <div className="notif-foreground-note" data-testid="notif-foreground-note">
          <h3 className="notif-note-title">关于「保持连接中」常驻通知</h3>
          <p className="hint">
            Android 壳会保留一条「保持连接中」的常驻通知，用于维持手机与电脑的长连接：
            锁屏或切到后台后，审批请求、任务完成等通知仍能送达。
          </p>
          <p className="hint">
            关闭方式：常驻通知由 Android 系统管理，不能在应用内直接关闭。
            可在通知栏长按该条目，或前往 系统设置 → 应用 → 通知 中关闭；
            关闭后应用退到后台或锁屏时连接可能中断，断连状态会在应用内如实显示，不会伪装在线。
          </p>
        </div>
      ) : null}
    </section>
  );
}
