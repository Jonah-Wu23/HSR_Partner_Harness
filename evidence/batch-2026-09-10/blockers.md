# S4 桌面批次 blockers（batch-2026-09-10）

本批次受阻项及后续处理条件。受阻不等于通过，也不等于未执行：每项都有尝试日志、复现命令与下一次尝试条件。

## B-01 断网注入需要管理员权限（A06 的「断网」子项）

- **尝试**：`New-NetFirewallRule -DisplayName 'S4-A06-block-deepseek' -Direction Outbound -Action Block -Protocol TCP -RemoteAddress <解析出的 deepseek IP>`；
  目标 IP 解析成功（`119.188.175.46,221.204.163.76`），建规则返回 `rc=1`（非管理员会话被拒），随后 `Remove-NetFirewallRule` 与计数核对均为 0，未留下残留规则。
- **证据**：`A06/a06-run.json` 的 `firewall_block` / `firewall_restore` / `firewall_cleanup_check` 字段；`A06/sidecar.log`。
- **阻塞原因**：当前会话无提升权限，无法创建出站阻断规则。
- **复现命令**：
  ```powershell
  New-NetFirewallRule -DisplayName 'S4-A06-block-deepseek' -Direction Outbound -Action Block `
    -Protocol TCP -RemoteAddress (Resolve-DnsName api.deepseek.com -Type A).IPAddress
  ```
- **责任人**：测试执行方（权限）+ 环境提供方（管理员会话或可断网虚拟机）。
- **下一次尝试条件与时间**：取得管理员会话或在隔离虚拟机中执行；下一次复验批次开始时（与 V039-S4-014 一并复验）。

## B-02 语音输出受阻于上游限流与用户成本约束（A08/A09 的语音输出子项）

范围界定：本 blocker **只覆盖语音输出本身**（TTS 合成与播放）。同一用例中 `voice.preview` 被 `remote_playback_active` 拒绝、以及世界书装配预算被超出约 10 倍，都是已确认的产品缺陷（V039-S4-016、V039-S4-017），已判失败并登记入 `V0.3.9-问题与修复台账.md`，**不计入受阻**。

- **尝试**：A08 期间连续 80 个真实回合触发 DashScope `Throttling.RateQuota`（`A02/sidecar.log`、`A08/sidecar.log`）；A09 尝试用 `voice.preview` 制造 60–120 秒长播放被 `remote_playback_active` 拒绝后，改用真实长回复路径（520 字）取得播放中抢占证据（`A09/a09-long.json`：playing → synthesizing → idle）。
- **证据**：`A08/a08-run.json`（`voice_runtime_state.error` 携带原始限流报文）、`A09/a09-long.json`（`voice.error` 携带原始限流报文）。
- **阻塞原因**：上游按账号限流，合成请求被拒；且用户明确要求停止对 393KB 相关回合进行语音合成以控制成本（账号级 `voice.enabled` 已置 false）。这是服务侧与成本侧的限制，不是产品能力缺失。
- **复现命令**：
  ```powershell
  & 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' evidence\batch-2026-09-10\tools\run_a09.py
  ```
- **责任人**：环境提供方（额度与限流窗口）；产品侧需先修复 V039-S4-016，持权端才有可用的起播路径。
- **下一次尝试条件与时间**：在低速率、显式授权的额度窗口下复验语音输出；需先完成 V039-S4-016 修复以获得持权端起播路径。下一次复验批次。

## B-03 Codex 事件路径不可达（A07 的 Codex 子项）

- **尝试**：将对话供应商切到 OpenAI 兼容后端以走 codex 引擎，`config.set` 返回真实拒绝：
  「codex 引擎要求 Responses API 后端，当前对话端点不兼容：https://127.0.0.1:1/v1。codex-cli 无法对接 Chat Completions 端点（0.122+ 已移除 wire_api=chat）。请改用 DeepSeek 对话配置（委派将自动走 reasonix 引擎），或提供 Responses 兼容后端。」
- **证据**：`A06/a06-injections.json` 的 `provider_switch_rejected`。
- **阻塞原因**：本机可用服务为 DeepSeek Chat Completions 与 DashScope，没有 Responses 兼容后端；EXE 内置 codex-cli 为 0.147.0（候选交接已注明布局不符打包要求）。
- **下一次尝试条件与时间**：提供 Responses 兼容后端（或确认改用内置 codex 的可行配置）后执行 Codex 事件用例；下一次复验批次。

## B-04 A05 与移动平台矩阵不在本批次范围

- 依《V0.3.9-真机验证补充测试.md》§6 结尾：A05 与 A10、A11 及移动平台矩阵不在本文范围，不得用桌面结果替代。
- 本批次未执行，也未据此宣称通过。

## B-05 A08 混合时间线的工具与思考条目未取到

范围界定：这是取证覆盖缺口，不是产品缺陷。同一用例中装配预算超限属缺陷 V039-S4-017，已判失败并登记台账；本项只记受阻。

- **已尝试的执行路径**：把 fix-c 世界书卡（85 条）绑定到 project-alpha 与 project-beta 的 4 个会话，在夹具卡会话发起「请让第四面镜在项目根目录新建文件 a08-mixed.md」并要求真实委派；随后读取该回合的消息与工具记录。
- **实际证据**：`A08/a08-run.json` 的 `mixed_timeline` —— 取到 4 类消息（`user.text`、`character.speech`、`assistant.natural_language`、`system.approval` 且审批结果为「允许」），但 `tool_runs` 为空数组，未产生思考条目；同一回合的 `assistant.natural_language` 正文为空，与 V039-S4-008 同源，需一并复验（`A08/ws-frames.log`、`A08/events.log`）。
- **阻塞原因**：该回合绑定的是 fix-c 夹具角色卡（正文仅一句占位说明），不具备真实角色人格与协作配置，因此无法在同一回合内产出真实的工具执行与思考条目。取到工具/思考条目需要「世界书卡 + 可真实委派角色」的组合，本批次未构造该组合。
- **需要开发或环境提供什么支持**：无需开发支持。需要的是测试侧构造该组合：把 fix-c 的世界书挂到 A07 已跑通真实委派的同一 pair（第四面镜/白厄）上，或在夹具卡上补齐可委派的角色配置（仍须走真实 Reasonix 链路，不得用 mock）。
- **可执行的替代验证方案**：复用 A07 已跑通真实委派的提示词与 pair，在其会话上重新绑定 fix-c 世界书卡后重跑一个回合，读取该回合的 `messages` 与 `tool_runs`，验证 4 类以上时间线与世界书激活在同一回合内同时成立。
- **责任人**：测试执行方（夹具与 pair 组合的构造）。
- **下一次尝试条件与时间**：与 V039-S4-017、V039-S4-016 的复验同批执行；届时用可真实委派的 pair 承载世界书卡。
