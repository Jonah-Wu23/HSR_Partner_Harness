# 设计与调研索引

设计过程的参考资料与交付物，分四块：

## research/ — 外部产品与实现调研

- `research/mufy角色卡参考.md` — mufy 平台角色卡创作模板完整抄录（世界观 + 角色构建 YAML 模板），角色卡数据契约的字段设计依据。
- `research/SillyTavern的优点.md` — SillyTavern 角色扮演五层机制拆解（角色卡数据层 / 世界书注入 / 提示词组装 / 宏展开 / 上下文管理），以白厄卡为例。
- `research/DeepSeek-Reasonix实现.md` — DeepSeek-Reasonix 编码 agent 的架构与上下文/前缀缓存分析；本仓库 ACP 助手引擎（`src/pair_harness/adapters/acp/engine.py`）的选型依据。

## dashscope/ — 千问语音 API 参考

阿里云百炼帮助文档抄录，语音链路的 API 依据（`src/pair_harness/` 多处注释引用其路径）：

- `dashscope/千问语音识别文档.md` — 实时语音识别（ASR）用户指南。
- `dashscope/千问声音设计文档.md` — 用自然语言描述创建音色（`creation_mode: design`）。
- `dashscope/千问声音复刻文档.md` — 用音频样本复刻音色（`creation_mode: clone`）；自家实测结论见 `../character-card/千问参考音频能力验证记录.md`。

## web-prototype/ — V0.4.0 角色卡视觉原型

强视觉 AI 交付的完整原型包（10 个自包含 HTML 与配套文档），V0.3.3+ 桌面端角色卡界面的视觉与交互依据。详见 `web-prototype/README.md`。

## 旧版/ — v0.2.0 时代文档

v0.2.0 迭代的修改方案、视觉方案与交付文档，仅作历史参考。详见 `旧版/README.md`。
