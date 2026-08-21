# docs 文档索引

本文件是 `docs/` 的总索引，采用渐进式披露：这里只记录顶层结构，需要细节时再进入对应子目录的 `README.md`。顶层概览同时记录在仓库根的 `AGENTS.md`「文档索引」一节。

## 顶层文件（不可移动）

- `index.html` — 项目官网营销落地页。GitHub Pages 从 `docs/` 根目录发布，此文件是站点入口。
- `assets/website/` — 官网使用的角色立绘（`index.html` 引用），与入口文件配套，同样不可移动。

## 子目录

| 目录 | 内容 | 详细索引 |
| --- | --- | --- |
| `plans/` | 开发计划。现行路线图 `V0.3.3-V0.4.0-Plan.md`（v0.3.2-patch1 → V0.4.0 五阶段收敛，角色卡与手机远程两条主线），另有已执行完毕的两份并行双AI任务指令书。 | `plans/README.md` |
| `release-notes/` | 历次版本发布说明：v0.3.2-patch1（当前基线）、v0.3.2、v0.2.0。 | `release-notes/README.md` |
| `character-card/` | 角色卡数据契约（hsr schema 1.0）、酒馆字段映射、状态枚举与接入清单。`src/pair_harness/character_cards/` 注释引用此处路径，移动文件需同步代码。 | `character-card/README.md` |
| `design/` | 设计调研与参考：`research/`（mufy、SillyTavern、DeepSeek-Reasonix 外部调研）、`dashscope/`（千问语音 API 参考，`src/` 多处注释引用其路径）、`web-prototype/`（V0.4.0 视觉原型交付包）、`旧版/`（v0.2.0 时代文档）。 | `design/README.md` |
| `website/` | 官网相关文档：`官网文案规则.md`（官网与宣发文案的写作方法论）。 | — |
| `promo/` | 宣发工作目录：B 站视频大纲、口播稿、宣发计划、素材/成品视频/抽帧/BGM。本地目录，Git 忽略，不入库。 | `promo/README.md` |

## 维护约定

- 新增文档放进对应子目录并更新该目录 `README.md`；出现新类别才新建目录。
- 移动或重命名 `character-card/`、`design/dashscope/` 下的文档时，同步更新 `src/` 代码注释中的路径引用。
- 已完结且不再被现行文档引用的旧文档放入 `design/旧版/`；需退出仓库历史的移入 `.archive/`（Git 忽略）。
