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

## B-02 语音输出受阻于上游限流与用户成本约束（A08/A09）

- **尝试**：A08 期间连续 80 个真实回合触发 DashScope `Throttling.RateQuota`（`A02/sidecar.log`、`A08/sidecar.log`）；A09 尝试用 `voice.preview` 制造 60–120 秒长播放，被 `remote_playback_active` 拒绝，改用真实长回复路径（520 字）取得播放中抢占证据。
- **证据**：`A08/a08-run.json`（`voice_runtime_state.error` 携带原始限流报文）、`A09/a09-run.json`（`preview` 被拒）、`A09/a09-long.json`（playing → synthesizing → idle）。
- **阻塞原因**：上游按账号限流；且用户明确要求停止对 393KB 相关回合进行语音合成以控制成本（账号级 `voice.enabled` 已置 false）。
- **复现命令**：
  ```powershell
  & 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' evidence\batch-2026-09-10\tools\run_a09.py
  ```
- **责任人**：产品侧（TTS 节流/退避与错误呈现）+ 环境提供方（额度）。
- **下一次尝试条件与时间**：修复 V039-S4-016 的守卫语义后，在低速率、显式授权的额度下复验 created 与首 delta 两类抢占；下一次复验批次。

## B-03 Codex 事件路径不可达（A07 的 Codex 子项）

- **尝试**：将对话供应商切到 OpenAI 兼容后端以走 codex 引擎，`config.set` 返回真实拒绝：
  「codex 引擎要求 Responses API 后端，当前对话端点不兼容：https://127.0.0.1:1/v1。codex-cli 无法对接 Chat Completions 端点（0.122+ 已移除 wire_api=chat）。请改用 DeepSeek 对话配置（委派将自动走 reasonix 引擎），或提供 Responses 兼容后端。」
- **证据**：`A06/a06-injections.json` 的 `provider_switch_rejected`。
- **阻塞原因**：本机可用服务为 DeepSeek Chat Completions 与 DashScope，没有 Responses 兼容后端；EXE 内置 codex-cli 为 0.147.0（候选交接已注明布局不符打包要求）。
- **下一次尝试条件与时间**：提供 Responses 兼容后端（或确认改用内置 codex 的可行配置）后执行 Codex 事件用例；下一次复验批次。

## B-04 A05 与移动平台矩阵不在本批次范围

- 依《V0.3.9-真机验证补充测试.md》§6 结尾：A05 与 A10、A11 及移动平台矩阵不在本文范围，不得用桌面结果替代。
- 本批次未执行，也未据此宣称通过。
