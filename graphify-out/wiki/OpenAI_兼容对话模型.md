# OpenAI 兼容对话模型

> 21 nodes · cohesion 0.16

## Key Concepts

- **OpenAICompatibleDialogueModel** (49 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **DialogueProtocolError** (14 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **.stream_reply()** (10 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **.build_messages()** (9 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **.generate_title()** (8 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **.complete_json()** (7 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **._request_extras()** (7 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **Any** (6 connections)
- **_apply_depth_injections()** (5 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **_chunk_delta()** (5 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **.generate_summary()** (5 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **._client_or_raise()** (4 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **.aclose()** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **ValueError** (1 connections)
- **以助手身份为聊天命名，不经过角色输出协议。** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **以助手身份生成聊天摘要；摘要字段与语义由模型决定。** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **DeepSeek 端点使用 JSON Output 并关闭 thinking，其他端点保持标准请求体。 deepseek-v4-flash 在…** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **解析一个 Chat Completions 流式数据块，返回首个 choice 的 delta。 OpenAI 协议允许 choices 为空的数据块（例如…** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **模型输出或 Chat Completions 响应不符合协议，消息带原始数据。** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **把世界书 atDepth 与 depth_prompt 注入插进对话消息列表（SillyTavern doChatInject）。 同 (depth,…** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **OpenAI Chat Completions 兼容端点上的角色对话、标题、摘要与 JSON 补全。 角色回合的 system…** (1 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`

## Relationships

- [OpenAI 兼容对话解析](OpenAI_兼容对话解析.md) (15 shared connections)
- [角色回合输出解析测试](角色回合输出解析测试.md) (12 shared connections)
- [对话供应商与搭档配置](对话供应商与搭档配置.md) (6 shared connections)
- [增量 JSON 流解析测试](增量_JSON_流解析测试.md) (5 shared connections)
- [演示模型与对话契约](演示模型与对话契约.md) (5 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (3 shared connections)
- [对话请求装配测试](对话请求装配测试.md) (3 shared connections)
- [角色卡模型与提示装配](角色卡模型与提示装配.md) (2 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (2 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (2 shared connections)
- [增量 JSON speech 解析](增量_JSON_speech_解析.md) (2 shared connections)
- [DeepSeek 请求体形状](DeepSeek_请求体形状.md) (2 shared connections)

## Source Files

- `src/pair_harness/adapters/dialogue/openai_compatible.py`

## Audit Trail

- EXTRACTED: 76 (73%)
- INFERRED: 28 (27%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*