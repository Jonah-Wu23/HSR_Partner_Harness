import type { CharacterIdentity, ConversationRecord } from "../contracts/protocol";

export function getConversationCharacterIdentity(
  conversation: Pick<ConversationRecord, "character_identity"> | null | undefined,
): CharacterIdentity | null {
  return conversation?.character_identity ?? null;
}

export function selectConversationCharacterIdentity(
  state: { conversationsById: Record<string, ConversationRecord> },
  conversationId: string | null,
): CharacterIdentity | null {
  return getConversationCharacterIdentity(
    conversationId ? state.conversationsById[conversationId] : null,
  );
}

export function isCharacterIdentityAvailable(
  identity: CharacterIdentity | null,
): identity is CharacterIdentity {
  return identity !== null && !identity.missing && identity.name.trim().length > 0;
}

export function getCharacterIdentityName(identity: CharacterIdentity | null): string {
  if (!identity) return "角色身份加载中";
  return isCharacterIdentityAvailable(identity) ? identity.name : "角色身份不可用";
}
