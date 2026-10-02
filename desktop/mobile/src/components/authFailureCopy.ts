import type { AuthFailureReason } from "../lib/wsClient";

/** 鉴权失败原因的界面文案；missing_token、invalid_token 使用通用的配对失效文案。 */
const AUTH_FAILURE_COPY: Partial<Record<AuthFailureReason, string>> = {
  expired_token: "登录令牌已过期（最长30天或7天未使用），请重新配对。",
  revoked_token: "本设备已被桌面端撤销授权，请重新配对。",
};

export const GENERIC_AUTH_FAILURE_COPY = "配对已失效或设备已被撤销，请重新配对";

export function describeAuthFailure(reason: AuthFailureReason | null): string {
  return (reason && AUTH_FAILURE_COPY[reason]) ?? GENERIC_AUTH_FAILURE_COPY;
}
