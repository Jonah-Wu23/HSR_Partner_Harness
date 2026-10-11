import type { MemoryScope, PairMemory, PairOption } from "../contracts/protocol";

/**
 * 一批记忆里用于展示的作用域：生效记录优先，全部已删除时退回删除记录。
 * 服务端按会话解析，同一批记录的分量一致，取第一条带作用域的即可。
 */
export function pickMemoryScope(memories: PairMemory[] | null | undefined): MemoryScope | null {
  if (!memories) return null;
  const active = memories.filter((memory) => memory.status === "active");
  return (active.find((memory) => memory.scope) ?? memories.find((memory) => memory.scope))?.scope ?? null;
}

/**
 * 按作用域的 pair_id 在搭档目录里取助手显示名。
 * 助手来自运行配置本身，共用同一 pair_id 的多条卡绑定给出同一个名字，取第一条匹配即可。
 * 目录尚未加载、pair_id 为空或没有匹配项时返回 null，界面回退原始 assistant_identity。
 */
export function findPairAssistantName(
  pairs: PairOption[] | null | undefined,
  pairId: string | null | undefined,
): string | null {
  if (!pairId) return null;
  const name = pairs?.find((option) => option.pair_id === pairId)?.assistant.name ?? "";
  return name.trim().length > 0 ? name : null;
}
