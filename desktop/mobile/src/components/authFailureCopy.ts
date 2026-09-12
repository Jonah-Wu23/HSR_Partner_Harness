/**
 * V0.3.9 V06 / V0.4.0 D5：鉴权失败原因文案。
 *
 * 契约要求「auth_failed 区分 token 过期与被撤销」。
 * - expired_token / token_expired: 登录令牌已过期（最长30天或7天未使用），请重新配对。
 * - token_revoked / revoked_token: 本设备已被桌面端撤销授权，请重新配对。
 */
export function describeAuthFailure(code: string | null | undefined): string | null {
  if (
    code === "expired_token" ||
    code === "token_expired" ||
    code === "auth_failed: expired_token"
  ) {
    return "登录令牌已过期（最长30天或7天未使用），请重新配对。";
  }
  if (code === "token_revoked" || code === "revoked_token") {
    return "本设备已被桌面端撤销授权，请重新配对。";
  }
  return null;
}
