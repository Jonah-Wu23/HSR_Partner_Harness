# V0.4.0 角色卡视觉原型交付包

强视觉 AI 按并行双AI计划（`../../plans/并行双AI计划_强视觉AI.md`）产出的高保真原型，2026-08-18 交付并验收通过。V0.3.3+ 桌面端角色卡界面的视觉与交互依据。

## 文档（按时间线阅读）

1. `ui-design-plan.md` — UI 设计方案：色彩、字体、布局与 8 页面规划。
2. `handoff-requirements.md` — 数据字段与后端能力需求清单（面向强逻辑 AI 的交付物 12）。
3. `delivery-report-v0.4.0.md` — 交付报告：12 项交付物、9 处缺口修复与验收后补充（§3.5、§5）。
4. `验收报告与修改计划.md` — 验收报告与修复闭环（含 Playwright 冒烟）。
5. `DESIGN-MANIFEST.json` — 机器可读清单（open-design.design-manifest.v1）：屏幕、token、交互矩阵。
6. `DESIGN-HANDOFF.md` — 工具生成的实现交接契约（英文）。

## 原型页面（10 个自包含 HTML，从 `index.html` 进入）

`index.html`（入口）、`onboarding.html`、`character-library.html`、`character-create.html`、`character-editor.html`、`character-import.html`、`character-export.html`、`worldbook-editor.html`、`voice-create.html`、`avatar-flow.html`。

注意：`DESIGN-MANIFEST.json` 的 `sourceFiles` / `assets` 需与实际文件保持同步，本目录内增删文件时要更新该清单。
