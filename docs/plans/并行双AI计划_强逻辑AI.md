你是 HSR Partner Harness 的“强逻辑 AI”。

项目路径：
E:\AI\HSR Partner Harness

当前状态：
- 当前产品基线为 V0.3.1。
- V0.3.2 已冻结，正在由另一个 AI 开发。
- 你的任务与 V0.3.2 同时开展，但不得修改、覆盖或重构 V0.3.2 正在开发的代码。
- 不要启用 Superpowers 工作流。
- 不要提交、推送、打 tag、发布或构建安装包。

一、开始前必须完整阅读

1. E:\AI\HSR Partner Harness\AGENTS.md
2. E:\AI\HSR Partner Harness\docs\V0.3.0-V0.4.0 Plan.md
3. E:\AI\HSR Partner Harness\docs\V0.3.2版本修改计划.md
4. E:\Tavern\白厄（3.4前）.json
5. E:\AI\HSR Partner Harness\docs\design\mufy角色卡参考.md
6. E:\AI\HSR Partner Harness\docs\design\千问声音复刻文档.md
7. E:\AI\HSR Partner Harness\docs\design\千问声音设计文档.md
8. E:\AI\HSR Partner Harness\docs\design\千问语音识别文档.md
9. 当前角色卡、配对 YAML、角色提示词、语音适配器和测试代码，只读了解现状。

先检查 git 状态，保留用户和其他 AI 的现有修改。发现文件正在被 V0.3.2 修改时，不要编辑该文件。

二、本次目标

在不接入现有数据库、Sidecar、正式前端和语音设置页的情况下，提前完成 V0.4.0 角色卡功能可以独立开发的逻辑底座：

1. 酒馆 Character Card v2/v3 数据契约。
2. `mufy` 扩展字段契约。
3. JSON/PNG 角色卡纯编解码模块。
4. 头像和未知扩展字段的往返保留。
5. 固定千问模型下的参考音频能力验证。
6. 交给强视觉 AI 使用的稳定样例数据和状态契约。

三、允许完成的工作

### A. 角色卡数据契约

根据酒馆样例和 `mufy角色卡参考.md`，建立内部角色卡契约。

酒馆已有内容继续使用标准字段：

- name
- description
- personality
- scenario
- first_mes
- mes_example
- creator_notes
- system_prompt
- post_history_instructions
- tags
- creator
- character_version
- alternate_greetings
- group_only_greetings
- character_book
- data.extensions

酒馆标准没有覆盖的字段进入：

data.extensions.hsr

至少包括：

- schema_version
- world_architecture
- character_architecture
- relationship_system
- event_system
- narrative_rules
- command_panels
- avatar_asset
- voice_profile

同一数据不得同时保存在标准字段和 `extensions.hsr` 中。必须明确每个字段的权威位置、类型、默认值、是否必填以及导入导出方式。

### B. 纯角色卡编解码模块

允许在全新、隔离的模块中实现：

- Character Card v2 JSON 导入
- Character Card v3 JSON 导入
- Character Card v3 JSON 导出
- Character Card v2/v3 PNG 元数据读取
- Character Card v3 PNG 元数据写入
- PNG 头像保留
- 根级兼容字段与 `data` 正式字段归一化
- 未识别但合法的第三方扩展原样保留
- 酒馆世界书条目读取和写回
- 备选问候、群组问候和 depth prompt 保留
- 导入、导出、再导入的往返测试

使用下面的真实样例作为主要回归输入：

E:\Tavern\白厄（3.4前）.json

纯模块不得依赖 SQLite、Sidecar 请求、React 状态或当前配对系统。

### C. 运行契约

定义角色卡未来进入运行时的模块顺序，但本次不接入正式对话链路。

需要明确：

- 标准角色设定模块
- system prompt
- post-history instructions
- depth prompt
- 世界书
- HSR 高级扩展
- 关系与事件模块
- 头像资产
- 角色音色状态

世界书关键词只用于角色卡内容激活。代码不得根据关键词猜测用户是否要求委派、是否需要工具、角色当前情绪或任务是否成功。

导入卡中的活动脚本和任意 HTML 不得直接作为应用代码执行。可以保留原始数据，并在兼容报告中标记为“已保留但未运行”。

### D. 语音能力验证

语音模型永久固定：

- ASR：qwen-audio-3.0-asr-flash-streaming
- TTS、声音复刻和声音设计：qwen-audio-3.0-tts-flash

用户不能修改模型名称。

根据三份千问文档验证：

1. 固定 TTS 模型创建复刻音色时接受哪些参考音频输入形式。
2. 本地 WAV、MP3、M4A 是否能直接提交。
3. 是否需要公网可访问 URL。
4. 创建音色 ID 的真实请求和响应结构。
5. 音色创建失败时的原始错误。
6. 音色 ID 与角色卡的绑定数据需要保存哪些字段。

有可用配置和参考音频时执行真实验证。缺少条件时如实记录阻塞，不使用 mock 结果代替真实结论。

不要修改当前语音设置页、V0.3.2 的 BYOK 实现和助手语音代码。

四、禁止修改的范围

本次不得进行以下工作：

- 不修改 V0.3.2 计划。
- 不修改现有 SQLite 数据库和迁移。
- 不修改 Sidecar JSONL 协议。
- 不修改当前前端共享类型。
- 不把角色卡接入正式对话和配对系统。
- 不修改多聊天并发链路。
- 不修改上下文压缩和长期记忆。
- 不删除助手 TTS。
- 不修改现有语音设置页。
- 不构建 EXE 或 NSIS。
- 不提交或推送 Git。
- 不用兜底数据掩盖失败。

五、交付物

至少交付：

1. 角色卡数据契约文档。
2. 酒馆字段与 HSR 扩展字段映射表。
3. 纯 JSON/PNG 编解码模块。
4. 使用白厄样例的往返测试。
5. 提供给强视觉 AI 的角色卡样例数据。
6. 提供给强视觉 AI 的状态枚举：
   - draft
   - saved
   - imported
   - invalid
   - voice_unconfigured
   - voice_creating
   - voice_ready
   - voice_failed
7. 千问参考音频能力验证记录。
8. 一份后续接入清单，说明 V0.3.2 完成后需要连接哪些数据库、Sidecar 和前端位置。

六、验收标准

- 白厄样例可以导入、导出并再次导入。
- 标准字段、五个备选问候、世界书和扩展字段没有无故丢失。
- 未知合法扩展能够保留。
- PNG 编解码能保留头像和角色卡元数据。
- `mufy` 字段有唯一、明确的保存位置。
- 模块不依赖 V0.3.2 最终数据库和协议。
- 没有修改 V0.3.2 正在开发的文件。
- 真实验证失败时保留原始错误。
- 最终报告列出新增文件、修改文件、测试结果和仍待 V0.3.2 完成后处理的事项。
