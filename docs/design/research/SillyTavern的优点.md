# 为什么 SillyTavern 能够做非常好的角色扮演

> 结论先行：SillyTavern 把"角色扮演"从一句提示词拆解成了 **角色卡数据层、世界书注入层、提示词组装层、宏展开层、上下文管理层** 五层可独立组合的机制。角色设定、世界观、表达规则、剧情节奏、输出格式各归其位，作者可以在任意一层做精细控制，而不必把所有东西塞进一段 system prompt 里赌模型的领悟力。
>
> 本文以两张真实文件为例说明：
> - 角色卡：`E:\Tavern\白厄（3.4前）.json`（Character Card v3 标准格式）
> - 提示词预设：`8.9【可待-从头越】 Agent版.json`（Prompt Manager 导出格式）

---

## 一、整体架构：五层机制

### 1. 角色卡（Character Card）数据层 —— "角色是谁"

角色卡是 ST 的存档单元，标准格式为 `chara_card_v3`（由 `src/character-card-parser.js` 解析）。一张卡把一个角色封闭成一个可携带、可分享的文件，结构上分为两块：

- **`data`**：角色本体。name、description（外貌与背景）、personality（性格底层逻辑）、scenario（开场情境）、first_mes（开场白）、mes_example（示例对话）、alternate_greetings（多条备用开场白）、system_prompt（表达铁律）、post_history_instructions（对话后的行为协议）。
- **`character_book`**：内嵌世界书。跟角色一起打包的"世界怎么运转"。

角色卡还支持"外链"机制：`extensions.world: "翁法罗斯"` 声明这张卡依赖一本同名世界书，导入时从 ST 的 `data/Worlds/` 目录挂载。世界观可以独立于角色长期积累、跨卡复用。

### 2. 世界书（World Info）注入层 —— "世界怎么运转"

世界书（`public/scripts/world-info.js`，约 6300 行）是一个**关键词触发的动态注入系统**：

- 每条目声明多个激活关键词（keys），扫描对话内容做关键词匹配；
- 支持深度扫描（depth buffer）、递归展开、min-activations、全局/角色/聊天三级作用域；
- 命中条目按优先级排序后，注入到提示词的 `worldInfoBefore`（角色设定前）或 `worldInfoAfter`（角色设定后）槽位。

效果：世界观条目平时不占上下文，**提到关键词才进提示词**。白厄卡的世界书把"翁法罗斯表层真相"（英雄史诗层）和"深层真相"（权杖 δ-me13 实验场、铁墓）分开成独立条目，靠不同关键词触发——模型默认只激活表层设定，深层设定要剧情推进到相关话题才注入，既省 token 又避免剧透式表演。

角色卡还有一个专属变体：`extensions.depth_prompt`，一条不靠关键词、而是**固定在对话第 4 条消息位置注入**的系统提示词（"深层设定默认锁死，不主动展开"），用于压住角色的长期行为基调。

### 3. 提示词组装层（Prompt Manager）—— "指令按什么顺序摆"

这是 ST 区别于所有简单前端的核心。每次生成消息，ST 不拼一段文本，而是维护一个"提示词集合"（`public/scripts/PromptManager.js`）：

- 内置固定槽位：`main`（主提示词）、`nsfw`、`jailbreak`、`enhanceDefinitions`（`PromptManager.js:313`）；
- 角色级 `prompt_order` 数组定义自定义提示词条目（内容、角色、开关、注入位置）的**精确顺序**；
- 组装时按 `prompt_order` 逐条渲染（`getPromptCollection`，`PromptManager.js:1516`），再与系统提示词部件按 identifier 合并、允许覆盖（`preparePromptsForChatCompletion`，`openai.js:1358`）；
- 最终由 `populateChatCompletion`（`openai.js:1176`）按固定顺序摆放：`worldInfoBefore → main → worldInfoAfter → charDescription → charPersonality → scenario → personaDescription → 自定义提示词 → 对话历史 → 示例对话`。

角色卡自己的 `system_prompt` 字段会**覆盖 `main` 槽位的内容**（`openai.js:1487-1494` 的 override 机制）；`post_history_instructions` 则注入对话历史之后，作为临场行为修正（白厄卡的 "Anti-Assistant 协议"：禁止以提问结尾引导对话）。作者可以分别控制"角色是谁""开场怎么写""聊到一半怎么纠偏"，互不干扰。

### 4. 宏引擎 —— "提示词是活的"

`{{...}}` 宏在提示词渲染时展开（`preparePrompt`，`PromptManager.js:1277` 调用 `substituteParams`）：

- **数据宏**：`{{char}}`、`{{user}}`、`{{lastUserMessage}}`、`{{time}}` 等，把角色卡数据和当前对话状态填进提示词。白厄卡的 personality 直接写成 `{{char}}的气质明亮、温和…`，场景里用 `{{user}}` 指代玩家，提示词可以在多玩家之间复用；
- **变量宏**：`{{setvar}}/{{addvar}}/{{getvar}}/{{incvar}}` 等（`macros/definitions/variable-macros.js`）。`addvar` 是"追加副作用"，`getvar` 取值输出，且**展开按 prompt_order 顺序逐条执行**——提示词之间因此有了可编程的先后依赖，这是高阶预设（如"可待"）能实现模块拼装的地基；
- **脚本宏**：STScript（斜杠命令）可以直接嵌进提示词执行，实现"提示词内做逻辑判断"。

### 5. 上下文管理层 —— "装不下的怎么办"

`ChatCompletion` 类（`openai.js:3822`）把组装好的内容变成一个受控的消息流：

- `setTokenBudget` 按 `max_context - max_tokens` 设预算，提示词部件按序"采购"；
- 对话历史从最新消息往回装，token 超预算时截断最旧的部分，保证生成可用；
- `squashSystemMessages`（`openai.js:3827`）把相邻的 system 消息合并成一条，压缩结构开销；
- 配套机制：对话摘要（memory 扩展）、作者注记（AN）、向量记忆、上下文压缩，都是为了在有限窗口里保住最重要的信息。

在五层之上，还有**后处理层**：正则脚本（Regex）、CFG 引导、logit bias，可以对模型输出做加工后再展示，让复杂格式（如 HTML 折叠）成为可能。

---

## 二、实例一：白厄卡（角色卡 v3）如何组织一个角色

```
白厄（3.4前）.json
├── spec: chara_card_v3, spec_version: 3.0
├── data                          ← 角色本体
│   ├── name / description        ← 银发蓝眸的少年、阳光男大与萨摩耶特质
│   ├── personality               ← "共情与守护"的底层逻辑 + {{char}}/{{user}} 宏
│   ├── scenario                  ← 3.4 之前的时间线、地点、关系状态
│   ├── first_mes                 ← 开场白（动作描写 + <speak> 台词）
│   ├── mes_example               ← 示例对话（{{user}}/{{char}} 轮转）
│   ├── alternate_greetings       ← 多条备用开场
│   ├── system_prompt             ← 【核心表达铁律】：台词必须 <speak> 包裹、
│   │                                动作/心理描写放标签外、深层秘密默认不提
│   ├── post_history_instructions ← Anti-Assistant 协议：禁止"小作文+提问"结尾
│   ├── extensions
│   │   ├── world: "翁法罗斯"      ← 外链同名世界书
│   │   └── depth_prompt          ← 深度4注入：稳定陪伴基调 + 深层设定锁死
│   └── character_book            ← 内嵌世界书（20 条）
│       ├── [翁法罗斯/逐火之旅]     ← 表层真相：黑潮、十二泰坦、再创世
│       ├── [黄金裔/泰坦/白厄]      ← 角色在体系中的位置
│       ├── [权杖δ-me13/铁墓]      ← 深层真相：星体计算机、实验场
│       └── [奥赫玛/永恒圣城]       ← 场景设定
└── 顶层 description/personality  ← 兼容旧版阅读器的冗余字段
```

**ST 如何消费这张卡**（对应五层机制）：

| 卡的字段 | 进入 ST 的哪个机制 |
|---|---|
| `data.system_prompt` | override `main` 槽位（`openai.js:1487`） |
| `data.post_history_instructions` | 注入对话历史之后的 system 消息 |
| `data.character_book` | 合并进世界书池，按关键词激活，注入 `worldInfoBefore/After` |
| `extensions.world: 翁法罗斯` | 挂载 `data/Worlds/翁法罗斯.json`，与内嵌书合并 |
| `extensions.depth_prompt` | 作为深度注入提示词，固定插到对话第 4 条位置 |
| `data.mes_example` | 示例对话区，`dialogueExamples` 槽位 |
| `{{char}}/{{user}}` 宏 | 渲染时替换为角色名/玩家名 |

这张卡体现的设计思想：**表达规则（<speak> 铁律）与内容设定（性格、场景）分离，表层世界观与深层真相分层**。模型永远先读到"你是谁、怎么说话"，深层秘密只在关键词触发时出现。

---

## 三、实例二：可待·从头越 Agent版 8.9（提示词预设）如何组织"创作系统"

这份文件不是角色卡（顶层没有 data/world），而是**纯 Prompt Manager 导出**：195 个提示词条目 + 161 项 `prompt_order`，挂到 `character_id: 100001` 名下。它把"创作系统"组织成了四件套：

### 1. `main` 是清零语句

`main` 提示词的内容是一行 14 个 `{{setvar::可待_XXX::}}`，把所有变量（`可待_前置处理`、`可待_创作准则`、`可待_文风准则`、`可待_后置功能`、`可待_思维链_本体`、`可待_定位`…）重置为空。它是纯副作用，展开后输出为空——保证每轮对话从干净状态开始。

### 2. 模块提示词用 `{{addvar}}` 追加规则

每个规则模块形如：

```
{{addvar::可待_前置处理:: ## 语言处理要求，请仔细阅读…}}
```

按 `prompt_order` 顺序（main 之后依次是 72c0e348 的前置处理总纲、21584678 的语言要求、441650ff 的字数要求、cb65a926 的注意事项、dc674646 的思考量要求、27c1fc66 的禁库限制……）逐个展开，每展开一个就往对应变量追加一段。**开关 = prompt_order 里的 enabled**，打开哪个模块就追加哪段规则。

### 3. 包装提示词用 XML 标签 + `{{getvar}}` 收口

前置处理模块全部展开后，第 145 位的包装提示词：

```
<overall-rules>{{addvar::可待_前置处理:: </overall-rules>}}{{getvar::可待_前置处理}}
```

先追加闭合标签，再取出完整变量，拼出：

```
<overall-rules>
  …所有前置处理规则…
</overall-rules>
```

同样的套路有四个层级：`<overall-rules>`（前置处理）→ `<writing-guidelines>`（创作准则）→ `<literary-styles>`（文风准则）→ `<rear-functions>`（后置功能），从总纲到细节层层包裹。

### 4. 输出模板 + assistant 预填充收尾

第 154 位 `<output-template>` 定义最终输出格式：思维链区 `<thinking>`、故事时间 `<scene>`、正文 `<content>`、定位区 `<g>`（实时总结/伏笔/大纲）。第 158 位是 **role=assistant** 的提示词：

```
{{getvar::可待_思维链_预填充定位}}
```

它排在 prompt_order 最后，成为发给 API 的最后一条 assistant 消息，即 **assistant prefill**：模型看到系统区要求"思考必须用 `<thinking>` 结构输出"，又看到助手消息已经打出思维模式要求的开头，于是从思维链开始续写。配套的 RegexBinding 把 `<thinking>` 内容折叠成界面里的 HTML 折叠栏，实现"思考可见、正文干净"。

另有 `54f71e2a`、`f38eb6c1` 等一组互斥的 setvar 候选，分别定义不同的思维链模式——启用哪个就把哪个注入 `可待_思维链_预填充定位` 变量（即"开关组"约定：❔组内选一）。

### 与 ST 机制的映射

| 预设里的东西 | ST 的实现 |
|---|---|
| `prompts` + `prompt_order` | `getPromptCollection`（`PromptManager.js:1516`），按顺序逐条展开 |
| `main`/`nsfw`/`jailbreak`/`enhanceDefinitions` | 内置提示词槽位（`PromptManager.js:313`） |
| `{{setvar}}/{{addvar}}/{{getvar}}` | 变量宏（`macros/definitions/variable-macros.js`），按 prompt_order 顺序产生副作用 |
| 世界书/角色数据占位（空 content 的 `worldInfoBefore` 等） | `preparePromptsForChatCompletion` 按 identifier 合并运行时数据 |
| assistant 预填充 | role=assistant 的 prompt 落为消息流最后一条 assistant 消息 |
| `extensions.RegexBinding` | 输出后处理，正则替换消息内容（纯显示层） |

这张卡说明：**ST 的 prompt_order 是可编程的**。作者不写死一份提示词，而是把规则拆成模块、用变量做拼装、用开关做配置、用顺序做依赖——最终提示词是运行时装配出来的。

---

## 四、两者如何结合：白厄卡 × 可待预设

在 ST 里，一张角色卡可以同时挂上提示词预设，两层各自生效：

```
白厄卡（角色数据层）                 可待预设（提示词层）
├── system_prompt ──────────override→ main 槽位（可待的 main 被替换）
├── post_history_instructions ──────→ 对话历史后注入
├── character_book ────关键词激活──→ worldInfoBefore/After 槽位
├── depth_prompt ────────深度注入──→ 对话第 4 条位置
└── data.* ───────────────{{char}}→ 供所有提示词引用

                                    可待的模块提示词（addvar 拼装）
                                    包装提示词（<overall-rules> 等）
                                    输出模板 + assistant prefill
```

组合效果：白厄卡提供"角色是谁、世界怎么运转、怎么说话"，可待预设提供"创作系统怎么思考、怎么写、输出什么格式"。两者互不覆盖：可待的 `main` 被白厄卡的 `system_prompt` 覆盖后，纯变量清零副作用依然执行（setvar 在覆盖前已渲染），创作规则模块照常追加。

一次生成的完整旅程：

```
1. 用户发送消息
2. prepareOpenAIMessages（openai.js:1533）
   ├─ preparePromptsForChatCompletion（openai.js:1358）
   │   收集世界书、角色描述、人格、场景 → 与 prompt_order 集合按 identifier 合并
   ├─ getPromptCollection（PromptManager.js:1516）
   │   按 prompt_order 顺序逐条 preparePrompt → 宏展开（setvar/addvar/getvar）
   ├─ populateChatCompletion（openai.js:1176）
   │   固定顺序摆放 + 对话历史回填 + 示例对话 + assistant 预填充
   └─ ChatCompletion（openai.js:3822）
        token 预算管理 → squashSystemMessages 合并
3. 发送给 API → 流式返回 → 正则脚本后处理 → 渲染
```

---

## 五、ST 相对"普通提示词工程"的本质区别

1. **结构代替长度**。普通玩法是把所有设定写进一大段 system prompt；ST 用五个槽位 + 任意自定义提示词把"设定"结构化摆放，每部分有明确语义位置。
2. **动态代替静态**。世界书按关键词进出上下文，深度提示词按对话位置注入，token 预算按实际容量截断——提示词内容随对话状态实时变化。
3. **可编程代替可编辑**。宏的副作用 + prompt_order 的先后顺序让提示词本身成为程序，"可待"这类预设就是证明：main 清零 → addvar 拼装 → getvar 收口 → prefill 引导，全靠引擎的顺序语义驱动。
4. **角色与世界解耦**。角色卡（身份、性格、表达）与世界书（世界观、势力、秘密）分开管理，可独立演进、跨卡复用。
5. **生态开放**。扩展系统（记忆、向量、TTS、表情）、正则脚本、斜杠命令都挂在提示词管线上，任何一层都可以被第三方增强。

## 参考

- SillyTavern 源码（`E:\Tavern\SillyTavern`）：
  - `public/scripts/PromptManager.js` — 提示词集合与顺序
  - `public/scripts/openai.js` — 消息组装与 ChatCompletion
  - `public/scripts/world-info.js` — 世界书
  - `public/scripts/macros/definitions/variable-macros.js` — 变量宏
  - `src/character-card-parser.js` — 角色卡解析
- 实例文件：
  - `E:\Tavern\白厄（3.4前）.json`（角色卡 v3）
  - `E:\AI\HSR Partner Harness\.archive\legacy-pyqt-2026-08-12\docs\referances\8.9【可待-从头越】 Agent版.json`（提示词预设）
