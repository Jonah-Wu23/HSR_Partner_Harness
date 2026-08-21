# 角色卡文档索引

角色卡功能（V0.3.3–V0.4.0 主线）的契约与实施文档。`src/pair_harness/character_cards/` 代码注释引用本目录路径，移动文件需同步更新。

## 阅读顺序

1. `角色卡数据契约.md` — 根契约（hsr schema 1.0）：酒馆标准字段、`data.extensions.hsr` 扩展、世界书、头像/音色资产、PNG 载体与装配顺序。
2. `酒馆字段与HSR扩展字段映射表.md` — 契约的字段级展开：酒馆 v3 字段与内部模型的逐字段映射，mufy 模板板块的归置规则（V0.3.7 酒馆双向兼容的对照基准）。
3. `强视觉AI-角色卡样例数据与状态枚举.md` — 冻结的 `CharacterCardState` / `CharacterVoiceState` 正交状态枚举，与 `samples/` 样例成对阅读。
4. `V0.3.2完成后接入清单.md` — 落地实施清单：SQLite 持久化、Sidecar 命令/事件、前端接入点、提示词装配与语音链路。

## 独立记录

- `千问参考音频能力验证记录.md` — 2026-08-16 对 DashScope 音色复刻端点的 6 个真实探针：本地音频转 Base64 data URI 放 `input.url` 可直接创建音色；GitHub raw 实测不可用，jsDelivr CDN 可用。被契约 §7 与接入清单 §5 引用，服务端策略变化时以新实测为准。

## samples/

- `samples/角色库样例.json` — 强视觉 AI 界面开发样例（`hsr.character_library_sample/1.0`），5 张卡覆盖全部状态组合；非真实用户数据，不作为验收证据。

外部依据：`../design/research/mufy角色卡参考.md`（模板板块来源）、`../design/dashscope/`（千问语音 API 参考）。
