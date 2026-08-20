import { useEffect } from "react";
import { navigate } from "../../lib/router";
import { useMobileStore } from "../../lib/mobileStore";

/**
 * V0.3.3 手机端聊天页（骨架空壳，由 W5 填充）。
 *
 * TODO(W5)：消息流渲染（角色/助手气泡、工具运行卡、审批条内联决议）、
 * 委派输入区（submitDelegation，target=assistant）、长列表虚拟化
 * （@tanstack/react-virtual）、message.delta 流式合并；语音保持静音——
 * 手机端不提供 TTS 入口。
 */
export function ChatPage(props: { conversationId: string }) {
  const conversation = useMobileStore(
    (state) => state.conversationsById[props.conversationId],
  );
  const messages = useMobileStore((state) => state.messages);
  const openConversation = useMobileStore((state) => state.openConversation);

  useEffect(() => {
    void openConversation(props.conversationId).catch(() => {
      // 装载失败如实回列表，由列表页 banner 呈现连接状态。
      navigate({ name: "list" });
    });
  }, [props.conversationId, openConversation]);

  return (
    <main className="page" data-testid="chat-page">
      <h1 className="page-title">{conversation?.title || "新聊天"}</h1>
      <p className="hint">骨架空壳：等待 W5 实现（见文件头 TODO）。</p>
      <p className="muted">已装载消息 {messages.length} 条。</p>
    </main>
  );
}
