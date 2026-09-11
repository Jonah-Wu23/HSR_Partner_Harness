"""生成各验收 ID 的 result.json（补充测试 §3 要求的字段全集）。

事实来源：各用例目录下的 *-run.json / events.log / ws-frames.log / sidecar.log 与
批次 manifest；本脚本只做汇总与规范化，不引入任何未采集的事实。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic")
EVIDENCE = REPO / "evidence" / "batch-2026-09-10"
BATCH = "batch-2026-09-10"
COMMIT = "897193a2fb983cd39c8328e98f7e225963a1ee64"
CONTRACT = "contract-v1（5dae701 + effa4f3）"
DEVICE = "Windows 11 10.0.26200 / Ryzen 7 7840H / 2560x1440 / 缩放150% / 本机桌面会话"
NETWORK = "本机直连公网；局域网 sidecar --serve 0.0.0.0:8765（Tailscale 未配置）"
EXE = str(REPO / "desktop/src-tauri/target/release/hsr-partner-harness.exe")
SIDECAR = str(REPO / "desktop/src-tauri/target/release/resources/sidecar/pair-harness-sidecar/pair-harness-sidecar.exe")

CASES: dict[str, dict] = {
    "A01": {
        "title": "协议级四会话并发、排队、取消与审批归属",
        "status": "通过",
        "preconditions": {
            "sidecar": "--real --serve 8765（token 由 UI 配对码经 remote.pair 换取）",
            "conversations": "四个新会话：A01-conv-1/2/3/4，覆盖 3 个搭档（白厄×2、三月七、流萤）",
        },
        "steps": [
            "四个独立 WS 会话（同一真实 token）同时 send chat.submit，记录各自发送时刻",
            "分别等待四个会话终态，核对消息归属、pair_id、串线",
            "同一会话内 0.187s 间隔连续提交两条，读取 queue_items 快照",
            "协作会话提交真实委派 → 捕获 approval.requested 归属 → task.cancel → 核对回收",
        ],
        "expected": "四会话提交时间最大差值 <1 秒；事件/消息/终态归属正确且零串线；排队项按序派发；取消回收待审批且无副作用",
        "actual": (
            "提交时间最大差值 0.0s（同一事件循环内四路并发，见 submit_spread_s）；"
            "四会话归属全部正确，三条标题按各自 pair 生成（守望/镜子/萤火），无串线；"
            "第二条提交在 0.187s 后进入 queue_items（status=queued, position=0），随后按 A→B 顺序派发完成；"
            "取消会话在生产 approval_id=5 后 task.cancel：active_task 归零、该会话待审批从 approvals 快照移除"
        ),
        "evidence": ["A01/ws-frames.log", "A01/events.log", "A01/a01-run.json",
                     "A01/a01-cancel.json", "A01/sidecar.log", "A01/sidecar-cancel.log",
                     "A01/commands.ps1", "A01/http.log", "A01/notes.md"],
        "ids": {"A01-conv-1": "2f9bea16-a862-4a41-9205-bf4dc20ee90e",
                "A01-conv-2": "59c487e5-0b4e-4280-af24-1e3d1d00631b",
                "A01-conv-3": "c87b576d-c182-47ab-9488-19915f2176f2",
                "A01-conv-4": "2dee07bd-96e6-4962-a552-327f3b792e8f",
                "A01-cancel": "dc234571-06c5-4b60-8850-c0a2b03f0c78",
                "approval_id": "2（并发裁决）/ 5（取消回收）"},
        "severity": "—", "frequency": "—", "impact": "—",
        "blocker": "", "owner": "—", "next_action": "",
    },
    "A02": {
        "title": "压缩触发（字节/条数）、真实摘要、保留最近 12 条与原文永久保存",
        "status": "失败",
        "preconditions": {
            "fixtures": "fix-a（402,315 B 单条）、fix-b2（80 条 × 约 1 KB，合计 77,246 B，隔离条数路径）",
            "note": "压缩触发为硬阈值：80 条或正文 256 KiB，任一先到",
        },
        "steps": [
            "会话 A02-bytes 提交 fix-a 原文作为一条消息正文（单条即超 256 KiB）",
            "等待 summary.started → summary.completed → 读取会话核对原文保留",
            "会话 A02-count 逐条提交 80 条 1KB 夹具（前 79 条提交后立即 task.cancel），第 80 条走真实模型完整回合",
            "等待条数阈值触发与真实摘要完成，核对消息与夹具留存",
            "尝试用 summary.get 读取摘要记录",
        ],
        "expected": "80 条或 256 KiB 任一触发；保留最近 12 条原文；原文永久保存；摘要正文由真实模型生成；摘要可通过只读命令读回",
        "actual": (
            "两条路径均真实触发并由真实模型生成摘要：字节路径 covers_message_count=1、条数路径 covers_message_count=80，"
            "status 均为 completed；落库摘要 content 为模型对该语料的概括（含「崩坏：星穹铁道」世界观要点）；"
            "会话 A02-bytes 原文保留（用户消息长度与夹具逐字符一致）；最近 12 条窗口由 role_context_window 实现"
            "（ROLE_CONTEXT_LIMIT_AFTER_SUMMARY=12）；"
            "但 summary.get 无法读回：空摘要会话返回 {\"summaries\": []} 正常，"
            "只要存在摘要记录即无响应并在 30 秒后超时（V039-S4-001）"
        ),
        "evidence": ["A02/a02-run.json", "A02/ws-frames.log", "A02/ws-frames-assembly.log",
                     "A02/events.log", "A02/sidecar.log", "A02/commands.ps1", "A02/http.log",
                     "fixtures/fixtures-manifest.json"],
        "ids": {"A02-bytes": "10014344-d00d-40be-8fc4-9ba57bb81e55",
                "A02-count": "b3b1bc41-67c7-4b69-baa3-ffc1923e9109"},
        "severity": "P1（读取链路）", "frequency": "必现",
        "impact": "摘要生成正常但用户与界面无法读回；压缩后的上下文对用户不可见",
        "blocker": "", "owner": "Sidecar Python / 前端诊断",
        "next_action": "修复 V039-S4-001 后复验 summary.get 读回与诊断面板展示",
    },
    "A03": {
        "title": "长期记忆入口侦查与隔离性",
        "status": "失败",
        "preconditions": {"scope_keys": "account_id/project_id/pair_id/character_ref/assistant_identity 五分量",
                          "note": "按补充测试 §7：缺入口判失败"},
        "steps": [
            "UI 路由/DOM 侦查：桌面端是否存在记忆增删改入口",
            "Rust 命令侦查：src-tauri 是否暴露记忆命令",
            "sidecar API 侦查：谁调用 upsert_memory（写入路径）",
            "协议枚举与调用：memory.list（缺分量/完整分量/同 pair 换 assistant_identity/换项目/按会话）、memory.update/delete（未知 id）",
        ],
        "expected": "存在可操作的记忆增删改入口或协议写入路径；五分量作用域隔离；同 pair 更换助手身份不读旧记忆；增删改实际生效",
        "actual": (
            "写入路径缺失：upsert_memory 在全库仅一处定义（storage/sqlite_store.py:1796），调用点零处；"
            "界面无入口：services/actions.ts 与 contracts/actions.ts 无记忆命令动作，"
            "desktop/src/ui 与 desktop/src/app 内零处调用 memory.list/update/delete；"
            "src-tauri 无记忆命令；"
            "协议侧本身正确：缺分量报 memory_invalid（MemoryScope 五分量必填），三种完整作用域与按会话解析均返回 [] 且可正常序列化，"
            "update/delete 对未知 id 报 memory_not_found。因此「0 条生效」恒为真，隔离性无真实数据可验"
        ),
        "evidence": ["A03/a03-run.json", "A03/ws-frames.log", "A03/events.log",
                     "A03/sidecar.log", "A03/commands.ps1", "A03/http.log"],
        "ids": {"account_id": "0b38c054-d2f1-4d1d-80c5-c06ac05c1cd6",
                "project_id": "4577124a-20f7-4b21-a39d-546f0ce4078c",
                "pair_id": "phainon_ancient_machine"},
        "severity": "P1", "frequency": "必现",
        "impact": "长期记忆功能整体不可达（无写入、无入口、隔离性无法验证）",
        "blocker": "", "owner": "Sidecar Python（写入路径）/ 前端（入口）",
        "next_action": "修复 V039-S4-003 后，用真实对话产出记忆再复验隔离矩阵",
    },
    "A06": {
        "title": "指标与装配诊断、真实服务失败注入",
        "status": "失败",
        "preconditions": {"card": "导入卡 ad95dd92f89d427f974e69d44b366901 绑定的会话",
                          "account": "错误注入在验收账号上进行后已恢复，最后核对 config.get 为原始配置"},
        "steps": [
            "装配诊断：普通查询与 include_hidden=true 对比，核对隐藏原文规则与是否进入对话流",
            "只读命令可用性：metrics.query / summary.get / memory.list / power.get_status",
            "失败注入：错误 API Key → 真实 401；切换 provider/base_url → 记录拒绝原因；同 provider 改 base_url → 核对是否生效",
            "断网：尝试用出站防火墙规则阻断 api.deepseek.com",
            "错误 Key 下跑真实回合，核对失败在会话中的呈现",
        ],
        "expected": "缺失指标为 null、真实零为 0；隐藏原文须显式请求且关闭清除、不进普通对话；错误可定位且原文可见",
        "actual": (
            "隐藏原文规则通过：普通查询 5 个模块 hidden_content 全为 null，include_hidden=true 返回 5 段共 14,771 字符，"
            "且模块原文不出现在对话消息里（hidden_text_absent_from_dialogue=true）；"
            "只读命令部分失败：metrics.query 有记录即超时（V039-S4-001）；summary.get 空则正常、有记录即超时（同一条缺陷）；"
            "错误 Key：config.test_connection 返回真实 401（原始供应商报文可见，错误可定位）；"
            "错误 base_url：config.set 返回成功但 config.get 显示 base_url 仍是 api.deepseek.com（被静默改写），"
            "test_connection 仍报「连接正常（延迟 531 ms）」（V039-S4-014）；"
            "切换 provider 被如实拒绝并说明原因（codex 需要 Responses 后端）；"
            "断网阻断：创建出站防火墙规则失败（非管理员，rc=1），未执行（见 blockers.md）；"
            "失败回合呈现：turn 终态 failed、用户消息 failed、出现 system.status 提示「本次回复失败：」但原因字段为空（V039-S4-015）"
        ),
        "evidence": ["A06/a06-run.json", "A06/a06-injections.json", "A06/a06-unreachable.json",
                     "A06/ws-frames.log", "A06/ws-frames-blast.log", "A06/ws-frames-unreachable.log",
                     "A06/a06-turn-terminal.json", "A06/sidecar.log", "A06/commands.ps1"],
        "ids": {"conversation_card": "daa0a2bc-629c-424b-8c0b-c2b48b83c3fb",
                "badkey_turn": "393b8673-5c26-4ad3-8e42-ab3020269ae3",
                "unreachable_turn": "cd8393c8-3765-4c3e-bcb7-455fd8078b90"},
        "severity": "P1（读取）/P2（配置静默改写）", "frequency": "必现",
        "impact": "诊断读取不可用；配置写入结果与提示不一致；失败原因不可见",
        "blocker": "断网注入需管理员权限（见 blockers.md B-01）",
        "owner": "Sidecar Python / 前端诊断与设置页",
        "next_action": "修复 V039-S4-001/014/015 后复验；断网注入改用管理员会话或虚拟机",
    },
    "A04": {
        "title": "后台运行、导航切换与重启恢复",
        "status": "通过",
        "preconditions": {"note": "本用例在 GUI 批次已完成，按补充测试 §最高指令只做交付物规范化，不重复执行"},
        "steps": [
            "协作模式下达真实委派，在任务运行期间切换聊天、打开设置与诊断抽屉",
            "正常关闭候选应用（窗口关闭按钮）",
            "重新启动候选 EXE 并核对恢复结果",
        ],
        "expected": "最后活跃聊天与时间线正确恢复，无错位",
        "actual": (
            "委派在后台持续运行，期间切换导航与设置抽屉均正常；"
            "关闭后重启，最后活跃会话（镜子）连同 4 条审批结果、委派卡片终态「已完成」、"
            "角色终局回复与工作台工具记录全部正确恢复，无错位"
        ),
        "evidence": ["A04/01-after-restart.png", "notes.md"],
        "ids": {"conversation": "e5e91b6f-722a-4cd6-8557-989760491aee（镜子）"},
        "severity": "—", "frequency": "—", "impact": "—",
        "blocker": "", "owner": "—", "next_action": "",
    },
    "A07": {
        "title": "真实 Reasonix 委派、多轮工具与 Codex 事件",
        "status": "通过",
        "preconditions": {"engine": "账号引擎为 DeepSeek → 委派走 Reasonix（ACP）；EXE 内置 codex-cli 0.147.0 未启用"},
        "steps": [
            "协作模式提交真实委派任务（含文件写入）",
            "逐轮批准工具调用并跟踪原始请求与事件",
            "委派结束后核对落盘结果、助手摘要与角色终局回复",
        ],
        "expected": "原始请求及事件可追踪；退出和失败直接暴露",
        "actual": (
            "真实链路完整：角色自然语言 → 结构化委派卡 → Reasonix 会话 → 4 轮工具调用"
            "（列目录 / 存在性与编码检查 / 写文件 / 回读校验）→ 4 次真实审批 → "
            "`acceptance-note.md` 按预期内容落盘（29 B，UTF-8 无 BOM，首字节 E7 9C 9F）→ "
            "助手结构化结果摘要 → 角色终局回复；工具与审批事件可在工作台与落库记录逐条追踪。"
            "协议侧同类委派在 A01/A08 中复现（含审批归属与取消）。"
            "Codex 事件子项受阻：切换 provider 被候选如实拒绝（需 Responses 兼容后端），见 blockers.md B-03"
        ),
        "evidence": ["A07-delegation/03-delegation-completed.png", "A07-delegation/db-delegation.txt",
                     "notes.md"],
        "ids": {"conversation": "e5e91b6f-722a-4cd6-8557-989760491aee",
                "task_id": "d55a166a-7c9c-4a20-bfe6-dd4f33d1c515"},
        "severity": "P2（V039-S4-009/008 待确认）", "frequency": "—",
        "impact": "—", "blocker": "Codex 事件路径不可达（B-03）",
        "owner": "Sidecar Python（引擎终态映射）", "next_action": "确认 V039-S4-009 语义后复验",
    },
    "A08": {
        "title": "长世界书混合时间线、装配诊断与真实语音输入输出",
        "status": "受阻",
        "preconditions": {"card": "fix-c 导入卡（393KB 世界书 85 条）绑定 4 个会话，跨 project-alpha 与 project-beta",
                          "voice": "语音开启、使用开发机 .env 作者音色；ASR 输入源为 Windows 系统 TTS 合成的 16kHz 单声道 WAV"},
        "steps": [
            "导入 fix-c 并绑定两个项目各两个会话",
            "含真实世界书关键词的回合 → 角色真实回复",
            "协作模式真实委派 → 产生角色/助手/系统混合消息",
            "装配诊断普通与 include_hidden 对比",
            "真实语音输入：系统 TTS 合成 → base64 PCM 分片喂入 mobile PTT → 取回 ASR 文本",
            "真实语音输出：voice.preview 与角色回复的 TTS 入队、固定模型标识核对",
        ],
        "expected": "仅角色自然语言进入 TTS；固定 ASR/TTS 模型不漂移；世界书按关键词激活且装配诊断可见（隐藏原文需显式请求）",
        "actual": (
            "装配诊断在绑定卡会话返回 5 个模块（世界书（角色设定前）/角色设定/性格/场景/世界书（角色设定后）），"
            "隐藏原文需 include_hidden=true；"
            "真实语音输入通过：42 个分片（131,680 B PCM）喂入后 ptt_stop 返回逐字一致的文本「请把项目根目录里的文件念给我听。」；"
            "固定模型标识：asr_model=qwen-audio-3.0-asr-flash-streaming、tts_model=qwen-audio-3.0-tts-flash（只读，无编辑入口）；"
            "朗读边界：用户消息 tts_eligible=false、角色最终消息 tts_eligible=true；"
            "混合时间线仅取到角色/助手/系统三类（该委派回合未在观测窗口内产出工具与思考条目）；"
            "语音输出受阻：voice.preview 以「手机正在控制语音」被拒（调用方即持控制权的远程端，提示与状态矛盾），"
            "且随后 DashScope 侧出现 Throttling.RateQuota 限流导致合成失败（错误已如实进入 voice.error）；"
            "补充：此用例消耗了真实 TTS 额度（用户随后要求停用语音，账号级 voice.enabled 已置 false）"
        ),
        "evidence": ["A08/a08-run.json", "A08/a08-asr-input.wav", "A08/ws-frames.log",
                     "A08/events.log", "A08/sidecar.log", "A08/commands.ps1", "A08/http.log"],
        "ids": {"A08-card-1": "daa0a2bc-629c-424b-8c0b-c2b48b83c3fb",
                "A08-card-2": "3f9a9425-8e0c-407b-aa8b-243e44513ce1",
                "card_id": "ad95dd92f89d427f974e69d44b366901",
                "project-beta": "358f5e7f-08e9-499f-af10-7d886df7d640"},
        "severity": "P2", "frequency": "高频回合下必现",
        "impact": "语音输出在远程控制态被拒；连续回合触发上游限流",
        "blocker": "上游 DashScope 限流（Throttling.RateQuota）；用户已要求停用语音以控制成本",
        "owner": "Sidecar Python（TTS 队列/错误呈现）",
        "next_action": "修复控制权守卫提示与限流退避后，在低速率下复验语音输出与混合时间线（工具/思考条目）",
    },
    "A09": {
        "title": "真实 TTS 播放中的抢占",
        "status": "受阻",
        "preconditions": {"voice": "语音开启（本用例执行时）；长回复由真实模型生成，约 520 字 ≈ 100 秒朗读"},
        "steps": [
            "领取远程播放控制权并尝试 voice.preview 长文本",
            "改为真实长回复路径：提交要求五百字以上的消息 → 角色长回复 → 观察 tts=playing",
            "播放中提交新消息（桌面发送抢占）→ 记录 voice 状态与事件",
            "播放停止后等待 8 秒，核对是否被迟到分片复活",
            "显式 voice.tts_stop",
        ],
        "expected": "旧播放、队列与在途合成停止；迟到 PCM 不复活播放；partial delta 不直接朗读",
        "actual": (
            "voice.preview 被拒（remote_playback_active，见 V039-S4-016）；"
            "改用真实长回复：520 字回复触发真实合成，voice.tts 观测为 playing；"
            "播放中提交新消息后：3 秒时 tts=synthesizing（旧播放已让位给新合成）、8 秒后 tts=idle、"
            "最终 tts=idle 且 speech_queue_len=0，未观察到迟到分片复活播放；"
            "朗读边界：user tts_eligible=false、character 最终消息 tts_eligible=true；"
            "voice.state_changed 事件捕获到播放态迁移"
        ),
        "evidence": ["A09/a09-run.json", "A09/a09-long.json", "A09/ws-frames.log",
                     "A09/ws-frames-long.log", "A09/events.log", "A09/events-long.log",
                     "A09/sidecar-long.log", "A09/commands.ps1", "A09/http.log"],
        "ids": {"A09-preemption": "225c5885-7492-4853-a1c2-d51e7ef0870e",
                "A09-long": "（见 a09-long.json conversation_id）"},
        "severity": "P3", "frequency": "远程控制态必现",
        "impact": "远程端无法用 preview 触发长播放；抢占用例只能走回复路径",
        "blocker": "远程持有播放控制权时 preview 被拒（提示与状态矛盾）；上游限流风险",
        "owner": "Sidecar Python（播放控制守卫文案/语义）",
        "next_action": "修正守卫语义后按桌面播放路径复验 created/首 delta 两类抢占",
    },
    "A12": {
        "title": "审批并发裁决、重放拒绝与真实 600 秒超时",
        "status": "通过",
        "preconditions": {"approval_timeout": "APPROVAL_TIMEOUT_S = 600.0 硬编码（application_service.py:335），无可配置入口，故按真实 600 秒验证"},
        "steps": [
            "对同一待审批从两个独立连接几乎同时发出 allow 与 deny",
            "核对生效方与后到方返回值，并重放同一动作",
            "核对待审批是否双端移除与副作用次数",
            "另起审批不做任何裁决，挂机等待真实超时，再验证迟到裁决",
        ],
        "expected": "首个终态获胜、后到者拿到真实终态；重放被拒；双端移除待审批；超时由服务端产生且迟到裁决被拒",
        "actual": (
            "并发裁决：allow 与 deny 在同一毫秒发出，allow 生效（resolved_by=remote），"
            "deny 收到 approval_already_resolved 且 details 携带生效方真实终态（decision=allow/resolved_at 等）；"
            "重放同一 allow 再次收到 approval_already_resolved（幂等，副作用仅一次）；"
            "生效后 approvals 快照不再包含该审批（双端移除）；"
            "真实超时：approval_id=6 于 2026-09-10T10:14:07.176Z 锚定，10:24:07.170Z 收到 approval.resolved，"
            "decision=timeout、resolved_by=system、actor=system、reason=等待审批超时、error_code=approval_timeout，"
            "实测等待 600.0 秒；迟到裁决被拒并携带真实终态"
        ),
        "evidence": ["A12/ws-frames-race-a.log", "A12/ws-frames-race-b.log",
                     "A12/ws-frames-timeout2.log", "A12/events-timeout2.log",
                     "A12/a12-timeout.json", "A12/a12-run.json", "A12/sidecar-timeout2.log",
                     "A12/commands-timeout.ps1", "A12/http.log"],
        "ids": {"approval_race": "2", "approval_timeout": "6",
                "race_conversation": "2dee07bd-96e6-4962-a552-327f3b792e8f",
                "timeout_conversation": "48bd0957-b73b-43ff-b68a-a6560d8abcfa"},
        "severity": "—", "frequency": "—", "impact": "—",
        "blocker": "", "owner": "—", "next_action": "",
    },
    "A13": {
        "title": "角色库主路径、393KB 长世界书导入导出与长字段操作",
        "status": "通过",
        "preconditions": {"fixture": "fix-c-worldbook-card.json（v3 卡承载 85 条世界书，正文 129,992 字节）"},
        "steps": [
            "card.import_json 导入 fix-c，记录 card_id 与 CompatReport",
            "card.get 核对条目数与字段长度",
            "card.export_json 导出并做条目数与正文字节的导回比对",
            "card.update 写入 242,332 字符长字段并回读比对",
            "card.import_json（as_duplicate=true）与 card.list",
        ],
        "expected": "原有主路径可用；长字段可操作；导入导出往返一致",
        "actual": (
            "导入成功（card_id=ad95dd92f89d427f974e69d44b366901，state=imported，report 含 applied/errors/warnings/not_executed/preserved/normalized_from_root）；"
            "card.get 返回 data.character_book 85 条、正文 129,992 字节；"
            "导出文件 187,536 B，条目数一致（roundtrip_entries_equal=true）；"
            "长字段：creator_notes 写入 242,332 字符后回读逐字符一致，且世界书条目数不变（85）；"
            "重复导入生成「（副本）」独立 card_id；card.list 共 5 张卡"
        ),
        "evidence": ["A13/a13-run.json", "A13/a13-longfield.json", "A13/exported-card.json",
                     "A13/ws-frames.log", "A13/ws-frames-longfield.log", "A13/sidecar.log",
                     "A13/commands.ps1", "A13/http.log"],
        "ids": {"card_id": "ad95dd92f89d427f974e69d44b366901",
                "duplicate_card_id": "25a31644b33547ce9f0ef5216edb51a6"},
        "severity": "—", "frequency": "—", "impact": "—",
        "blocker": "", "owner": "—", "next_action": "",
    },
    "A14": {
        "title": "鉴权失败、链路中断、真实休眠恢复与恢复后新 turn",
        "status": "通过",
        "preconditions": {"auth": "错误 token / 缺失 token / 由桌面签发配对码换取的真实 token",
                          "standby": "Windows Modern Standby（Kernel-Power 506→507）"},
        "steps": [
            "错误 token 与缺失 token 调用业务命令",
            "签发配对码 → 配对新设备 → remote.revoke → 观察连接关闭与后续请求",
            "经本机 TCP 代理切断在途请求（先确认请求已达服务端）",
            "重连后核对无重复消息并跑通新 turn",
            "真实休眠：注册 WakeToRun 计划任务 → 提权 SetSuspendState → 唤醒后核对状态与新 turn",
        ],
        "expected": "双端状态准确；恢复入口真实有效；恢复后新 turn 成功；撤销 token 立即生效",
        "actual": (
            "错误 token → unauthorized/invalid_token；缺失 token → unauthorized/missing_token；"
            "撤销：devices 列出 s4-a14-revoke（revoked_tokens=1），撤销后设备 revoked=true、"
            "已建立连接在 15 秒内收到关闭帧，随后同 token 请求 → unauthorized/revoked_token；"
            "在途断链：确认用户消息已落库后切断代理，发起方永久收不到响应（client_timeout_no_response），"
            "服务端照常完成该回合（角色回复「断」），重连后标记恰好 1 条（无重复），新 turn 回复「续」；"
            "真实休眠：Kernel-Power Id 506 于 18:54:30 进入 Modern Standby、Id 507 于 18:59:23 恢复（约 4 分 53 秒，符合 2–5 分钟要求），"
            "唤醒后应用与 sidecar 均为原进程（PID 25152/13984），无残留 active_task/approval，"
            "新 turn 完成（角色回复「醒」，turn status=completed）"
        ),
        "evidence": ["A14/a14-run.json", "A14/a14-inflight.json", "A14/a14-sleep.json",
                     "A14/a14-standby.json", "A14/a14-inflight-slow.json",
                     "A14/ws-frames-*.log", "A14/events-*.log", "A14/sidecar*.log",
                     "A14/02-remote-devices-page.png", "A14/03-pairing-code-issued.png",
                     "A14/commands.ps1", "A14/http.log"],
        "ids": {"revoke_device": "s4-a14-revoke（token sha256[:16]=91c76fa0551dbd12）",
                "netcut_conversation": "ff5a2fd2-79a9-4896-a63c-b4e284dcbb50",
                "inflight_conversation": "05e63c46-cef3-4063-ad34-928520c03760",
                "standby_conversation": "A14-standby-resume（见 a14-standby.json）"},
        "severity": "P2（附带发现）", "frequency": "—",
        "impact": "远程设备页地址就绪判定错误（V039-S4-004）",
        "blocker": "", "owner": "Sidecar Python（服务地址探测）",
        "next_action": "修复 V039-S4-004 后复验二维码入口",
    },
}


def write_case(case: str, payload: dict) -> Path:
    directory = EVIDENCE / case
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "batch": BATCH,
        "case_id": case,
        "title": payload["title"],
        "candidate_commit": COMMIT,
        "contract": CONTRACT,
        "build": {"exe": EXE, "sidecar": SIDECAR,
                  "exe_sha256": json.loads((EVIDENCE / "batch-manifest.json").read_text(encoding="utf-8"))["hashes"]["exe"]["sha256"],
                  "sidecar_sha256": json.loads((EVIDENCE / "batch-manifest.json").read_text(encoding="utf-8"))["hashes"]["sidecar_exe"]["sha256"]},
        "device": DEVICE,
        "network": NETWORK,
        "preconditions": payload["preconditions"],
        "steps": payload["steps"],
        "expected": payload["expected"],
        "actual": payload["actual"],
        "timestamps": {"batch": BATCH, "recorded_at": "2026-09-10T11:05:00Z"},
        "ids": payload["ids"],
        "evidence": payload["evidence"],
        "severity": payload["severity"],
        "frequency": payload["frequency"],
        "impact": payload["impact"],
        "status": payload["status"],
        "blocker": payload["blocker"],
        "owner": payload["owner"],
        "next_action": payload["next_action"],
    }
    path = directory / "result.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    for case, payload in CASES.items():
        print("written", write_case(case, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
