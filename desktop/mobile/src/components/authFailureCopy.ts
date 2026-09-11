/**
 * V0.3.9 V06：鉴权失败原因文案。
 *
 * 契约要求「auth_failed 区分 token 过期与被撤销」。当前服务端只返回
 * `error.code = "unauthorized"`（ws_server.py 鉴权分支），协议与 wsClient 都还没有
 * 细分错误码，因此这里只对两个明确约定的错误码给出具体文案，其余一律返回 null，
 * 由调用方回退到通用文案——不按 message 关键词猜测原因。
 *
 * 待真实接线（跨轨需求）：Sidecar 在 unauthorized 上细分 error.code
 * （建议 token_expired / token_revoked），wsClient/mobileStore 把该 code 透出为
 * `authFailureCode`；接入前本函数始终返回 null，UI 保持通用文案。
 */
export function describeAuthFailure(code: string | null | undefined): string | null {
  if (code === "token_expired") return "配对凭据已过期，请重新配对。";
  if (code === "token_revoked") return "本设备已被桌面端撤销授权，请重新配对。";
  return null;
}
