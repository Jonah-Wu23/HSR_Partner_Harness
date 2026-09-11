# Graph Report - HSR Partner Harness  (2026-09-11)

## Corpus Check
- Large corpus: 965 files · ~1,953,828 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 7620 nodes · 18326 edges · 311 communities (255 shown, 42 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 2233 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- 规划式评审测试夹具
- 复现脚本与 ACP 链路
- 对话上下文与消息模型
- ACP 编码引擎
- 会话编排器
- 前端状态与状态条
- 角色卡模型与 HSR 扩展
- 前端命令协议
- UI 图标组件
- Codex 对话模型
- 角色卡编解码与兼容报告
- Demo 服务与队列测试
- 审批管理器
- 前端动作契约
- 委派与契约模型
- 移动端通知偏好
- 桌面后端应用服务
- 前端服务与快照模型
- 搭档头像与视图模型
- 存储增量缓冲与刷盘
- AppController 控制器
- 移动端音频与 ASR 会话
- 角色卡界面与兼容弹窗
- 桌面协议编解码测试
- 语音运行时接线
- 桌面状态仓库
- 语音播放与采集控制
- 角色上下文窗口与摘要
- 长期记忆与身份
- 世界书激活与 token 估算
- 搭档配对与助手提示词
- 引导与设置界面
- V0.3.9 R1 重置脚本测试
- V0.3.9 存储测试
- 聊天页测试与假 WebSocket
- 场景夹具与 Mock 数据
- 桌面后端角色卡命令
- 移动端委派卡
- Silero VAD 语音活动检测
- 世界书深度注入激活
- 角色卡仓库
- 后端引导与快照解析
- V0.3.5 接线测试
- 电源状态采集
- Demo 语音合成
- 千问语音合成适配器
- 服务模式集成测试
- 移动端连接生命周期
- 语音运行时测试
- 移动端语音播放
- 角色卡导出流程
- 移动端依赖清单
- PNG 角色卡读写
- 诊断抽屉
- Codex 传输集成测试
- 电源状态测试
- 千问流式语音识别
- JSONL 子进程传输
- Tauri 后端重连与退避
- 会话投影
- 边车协议解析
- 摘要与投影存储校验
- OpenAI 兼容层测试
- 事件扇出
- 高级编辑器面板
- 角色资产服务
- 记忆命令处理
- 深度注入消息装配测试
- 假聊天服务器测试
- WebSocket 服务测试
- Android 版本号测试
- 移动端状态仓库
- 发布缺陷与验收门禁
- 角色创建页
- 移动端应用外壳
- 委派重试测试
- V0.3.8 委派执行链测试
- V0.3.9 B03 仅聊天补全测试
- 边车入口与信号处理
- Codex 登录状态测试
- SQLite 存储与 schema 迁移
- Tauri 后端状态类型
- 世界书条目编辑器
- 千问流式识别测试
- 存储批量写入
- ACP 引擎测试
- PWA 静态资源路由
- 摘要事件载荷与身份
- 移动端连接提示与设备列表
- Codex 鉴权服务
- 审批代理
- Codex 审批流集成测试
- 协议契约文档节点
- 回合指标存储
- 语音试听声源校验测试
- 基础信息表单与头像
- 对话供应商配置
- 回合调度与终态
- 配对级长期记忆存储
- 角色卡 PNG 命令测试
- 审批终态测试
- 世界书与注入契约
- 模型输出解析
- 全局引擎状态
- 控制租约测试
- 角色音色页面
- V0.2.0 旧版设计文档
- 助手装配断言测试
- 千问音频实网测试
- V0.3.8 会话幂等测试
- 移动端语音采集
- 表单控件工具
- 角色卡数据契约文档
- 架构决策文档节点
- 音色创建 CLI
- 音色绑定与参考音
- 语音播放队列
- 控制租约
- 配对与鉴权服务
- 并发入口测试
- Tauri 边车启动与日志
- 桌面端依赖清单
- 官网文案规范
- Codex 事件编解码
- Codex app-server 引擎
- 数据宏展开
- 会话仓储
- 增量 JSON 解析测试
- 子进程启动与终止
- 提示词装配诊断
- V0.3.9 指标与诊断测试
- 移动端语音输入测试
- 音色 CLI 测试
- src: WsAddressInput.tes…
- src: appendTtsChunk()
- tsconfig.json: tsconfig.json
- tauri.conf.json: tauri.conf.json
- tsconfig.app.json: tsconfig.app.json
- desktop_backend: DiagnosticCallback
- adapters: incremental_json.p…
- core: sandbox.py
- desktop_backend: _extract_frame_id(…
- test_sounddevice_io.py: test_sounddevice_i…
- test_v039_s4_voice_tts.py: EventLog
- test_v039_prompt_assembly_seams.py: test_v039_prompt_a…
- test_v039_turn_metric_seams.py: test_v039_turn_met…
- test_deepseek_request_shape.py: AsyncClient
- adapters: OutputStream
- adapters: 距离下一次可起始还需等待的秒数（<=…
- test_v039_assembler_summary_memory.py: test_v039_assemble…
- src: ChatListPage.tsx
- adapters: AcpCodec
- desktop_backend: ._account_exists()
- storage: records.py
- test_accounts_store.py: test_accounts_stor…
- test_acp_engine.py: engine_and_server(…
- test_pairing.py: _FakeClock
- test_v035_codex_fixes.py: test_v035_codex_fi…
- test_v038_t4_delegation_chain.py: _HangingTransport
- test_v039_summary_memory_commands.py: test_v039_summary_…
- AGENTS.md: AGENTS.md 仓库协作准则
- web-prototype: 角色快速创建页面
- 手机远程语音说明.md: 删除语音赞助二维码与作者承担费用承诺
- test_pair_config.py: adopt_voice_id()
- test_v038_t2_device_mutex.py: test_v038_t2_devic…
- test_v038_t4_delegation_chain.py: _FakeCodexAuth
- test_v039_r2_application_fixes.py: test_v039_r2_appli…
- ui: helpers.tsx
- tsconfig.node.json: tsconfig.node.json
- v0.3.4-acceptance.md: 前节交谈、后节执行的双空间联动
- adapters: sounddevice_io.py
- adapters: Predictable rolepl…
- desktop_backend: _atomic_write_text…
- test_text_loop_live.py: test_text_loop_liv…
- test_application_service.py: __init__()
- src: BackendMode
- web-prototype: 角色高级编辑器页面
- V0.3.3-V0.4.0-Plan.md: 纯 JSON/PNG 编解码模块
- v0.2.0-release-notes.md: 持久化会话队列 conversati…
- adapters: customization_endp…
- src: ApprovalCard.tsx
- package.json: devDependencies
- adapters: DemoSpeechRecogniz…
- adapters: qwen_voice_customi…
- desktop_backend: pairing.py
- test_acp_engine.py: FakeTransport
- test_application_service.py: 角色流不走 coding busy，…
- test_v039_s4_application_fixes.py: MonkeyPatch
- risk_rules.yaml: 高风险操作判定规则表
- package.json: scripts
- src: chat_window_title(…
- web-prototype: V0.4.0 角色卡系统 UI 原型…
- index.html: Tauri 2 + Python S…
- V0.3.5-契约冻结.md: 助手永久禁用 TTS
- v0.3.5-visual-ai-acceptance.md: PTT 测试竞态修复（vad.ses…
- repro_sidecar_process.py: repro_sidecar_proc…
- desktop_backend: ._audit_log()
- test_sounddevice_io.py: FakeOutputStream
- test_voice_runtime.py: DrainPlayer
- PHILOSOPHY.md: Let It Fail（真实失败必须…
- README.md: 古代机器音色提示词
- v0.3.2-release-notes.md: v0.3.2-patch1 为当前产…
- adapters: PostJson
- repro_onboarding_flow.py: FrontendStore
- smoke_serve_mode.py: smoke_serve_mode.p…
- verify_qwen_reference_v035.py: verify_qwen_refere…
- adapters: AbstractEventLoop
- test_codex_transport_robustness.py: test_codex_transpo…
- test_v035_wiring.py: install_fake_qwen_…
- dashscope: 本地模型目录说明
- 千问参考音频能力验证记录.md: 千问参考音频能力验证记录
- V0.4.0关键产品级决策.md: 手机远程架构八原则
- V0.3.9-续作计划.md: V0.3.9 验收记录
- test_application_service.py: V0.2 M2-4：voice.tt…
- test_pairing.py: test_pairing.py
- test_pairing.py: export_state 不含 AP…
- test_v032_m6_voice.py: test_v032_m6_voice…
- package.json: dependencies
- web-prototype: 头像设置三步弹层页面
- web-prototype: 角色导入流程页面
- web-prototype: 参考音频公网 URL 要求
- V0.3.5-契约冻结.md: 审批仲裁与命令来源 origin
- verify_qwen_reference_audio.py: verify_qwen_refere…
- adapters: .close()
- core: available_input_me…
- test_voice_runtime.py: FakeCapture
- tauri.android.conf.json: tauri.android.conf…
- web-prototype: 角色导出流程页面
- web-prototype: 助手永远不使用 TTS
- 并行双AI计划_强视觉AI.md: 角色卡数据契约与字段映射表
- desktop_backend: _CodeEntry
- storage: 打开数据库并完成迁移。 clock …
- character_cards: _generate_png_fixt…
- test_v039_l08_preemption.py: PreemptRecordingRu…
- src: Socket
- capabilities: default.json
- 强视觉AI-角色卡样例数据与状态枚举.md: 失败保持失败（CardImportE…
- web-prototype: 设计 token 前置抽取契约
- repro_v037_visual_contracts.py: repro_v037_visual_…
- test_desktop_sidecar_loop.py: StreamReader
- fake_codex_app_server.py: .notify()
- test_codex_transport.py: EofConnection
- test_acp_engine.py: FakeAcpConnection
- test_application_service.py: V0.3.3：手动重播助手消息在语音…
- test_pairing.py: list_devices 返回 De…
- test_pairing.py: 审计条目不含消息正文与密钥（仅含方法…
- test_pairing.py: 验证配对模块使用 hmac.comp…
- test_qwen_event_mapping.py: FakeRecognition
- test_qwen_event_mapping.py: FakeTtsSynthesizer
- repro_full_flow.py: repro_full_flow.py
- adapters: JsonLineConnection
- core: .normalize_unicode…
- test_serve_mode.py: _BlockingStdin
- test_application_service.py: F7：attach_voice_ru…
- test_v035_wiring.py: DesktopCommand
- test_v038_t4_delegation_chain.py: _binding()
- test_v039_s4_voice_tts.py: V039-S4-018：抢占旧合成不…
- index.html: 搭档手机端 HTML 入口
- tauri-with-first-run-reset.ps1: tauri-with-first-r…
- V0.3.7-验收记录.md: V0.3.7 验收记录（§6.1 矩…
- V0.3.9-复测计划.md: C4 委派链卡死
- serve_driver_v037.py: serve_driver_v037.…
- adapters: ._ensure_initializ…
- desktop_backend: .cancel_all_for_co…
- desktop_backend: ._prune_stopped()
- test_v032_baselines.py: _jsonl()
- test_v033_wiring.py: service()
- test_v039_s4_application_fixes.py: V039-S4-008：只有思考的段…
- tsconfig.json: tsconfig.json
- 并行双AI计划_强逻辑AI.md: 千问参考音频能力验证
- V0.3.7-验收记录.md: 电源提示双向翻转实测
- V0.3.9-验收记录.md: A10/A11 最终记录
- repro_out.txt: 复现脚本输出 repro_out.t…
- test_acp_engine.py: V0.3.3：消费方在 TOOL_S…
- test_sounddevice_io.py: _fresh_streams()
- test_v039_s4_application_fixes.py: V039-S4-015：异常自述为空…
- V0.3.7-真机验收发现与问题清单.md: C1 后台事件不达（保活失败）
- V0.3.8-修复实施计划.md: 工作流门禁（真机→CI→Codex→…
- V0.3.9-真机验证补充测试.md: 四态判定（通过/失败/受阻/不适用）
- V0.3.9-问题与修复台账.md: V039-S4-002 演示模式静默…
- adapters: __init__.py
- adapters: __init__.py
- adapters: __init__.py
- config: __init__.py
- core: __init__.py
- desktop_backend: .add_revoke_listen…
- desktop_backend: .export_state()
- __init__.py: __init__.py
- test_openai_compatible.py: 公开解析入口（Codex 适配器共用…
- web-prototype: 8px 基线布局基元（8px 圆角 …
- web-prototype: 三段字体体系（思源宋体 Displa…
- web-prototype: Playwright 十页渲染冒烟验…
- V0.3.5-双轨实施计划.md: Let It Fail 准则
- V0.3.5-双轨实施计划.md: Let It Go 准则
- V0.3.5-双轨实施计划.md: 视觉自主权声明
- Cargo.toml: hsr-partner-harnes…
- pyproject.toml: pair-harness

## God Nodes (most connected - your core abstractions)
1. `DesktopApplicationService` - 305 edges
2. `SQLiteStore` - 225 edges
3. `ConversationOrchestrator` - 154 edges
4. `HarnessActions` - 144 edges
5. `ServiceError` - 139 edges
6. `Message` - 133 edges
7. `build_demo_service()` - 117 edges
8. `MessageSource` - 108 edges
9. `CharacterTurn` - 93 edges
10. `ApprovalMode` - 93 edges

## Surprising Connections (you probably didn't know these)
- `cmd()` --calls--> `DesktopCommand`  [INFERRED]
  scripts/repro_full_flow.py → src/pair_harness/desktop_backend/commands.py
- `test_data_uri_rejects_unknown_audio_extension()` --uses--> `VoiceCustomizationError`  [INFERRED]
  tests/unit/test_voice_cli.py → src/pair_harness/adapters/audio/qwen_voice_customization.py
- `test_normalize_prefix_rejects_empty()` --uses--> `VoiceCustomizationError`  [INFERRED]
  tests/unit/test_voice_cli.py → src/pair_harness/adapters/audio/qwen_voice_customization.py
- `test_normalize_prefix_rejects_more_than_10_characters()` --uses--> `VoiceCustomizationError`  [INFERRED]
  tests/unit/test_voice_cli.py → src/pair_harness/adapters/audio/qwen_voice_customization.py
- `test_engine_session_reference_is_opaque_to_application()` --uses--> `EngineSessionRef`  [INFERRED]
  tests/unit/test_contracts.py → src/pair_harness/core/contracts.py

## Import Cycles
- 5-file cycle: `src/pair_harness/desktop_backend/application_service.py -> src/pair_harness/desktop_backend/pairing.py -> src/pair_harness/desktop_backend/ws_server.py -> src/pair_harness/desktop_backend/event_fanout.py -> src/pair_harness/desktop_backend/router.py -> src/pair_harness/desktop_backend/application_service.py`

## Hyperedges (group relationships)
- **V0.4.0 公网接入安全模型（隧道 + 回环 + 限流 + 令牌 + 控制面）** — docs_plans_v0_4_0_key_product_decisions_security_gaps, docs_plans_v0_4_0_key_product_decisions_d1_cloudflare_tunnel, docs_plans_v0_4_0_key_product_decisions_d2_loopback, docs_plans_v0_4_0_key_product_decisions_d3_rate_limit, docs_plans_v0_4_0_key_product_decisions_d5_token_lifetime, docs_plans_v0_4_0_key_product_decisions_d6_control_plane, docs_plans_v0_4_0_key_product_decisions_d7_public_url [EXTRACTED 1.00]
- **双轨契约冻结流程（路线图 → 执行计划 → 契约冻结 → 实现）** — docs_plans_v0_3_3_v0_4_0_plan_dual_track_dev, docs_plans_v0_3_5_dual_track_plan_plan, docs_plans_v0_3_5_contract_freeze_contract, docs_plans_v0_3_7_dual_track_plan_plan, docs_plans_v0_3_7_contract_freeze_contract [EXTRACTED 1.00]
- **真机验收纪律（只测不修 + 四态判定 + 固定格式台账 + 验收记录）** — docs_plans_v0_3_9_device_verification_supplementary_test_instructions, docs_plans_v0_3_9_device_verification_supplementary_test_four_states, docs_plans_v0_3_9_device_verification_supplementary_test_no_fix_rule, docs_plans_v0_3_9_device_verification_supplementary_test_issue_format, docs_plans_v0_3_9_device_verification_requirements_core_cases, docs_plans_v0_3_9_issue_ledger_ledger, docs_plans_v0_3_9_acceptance_record_record [EXTRACTED 1.00]
- **角色创建到配对对话的主路径** — docs_design_web_prototype_character_library, docs_design_web_prototype_character_create, docs_design_web_prototype_character_editor, docs_design_web_prototype_voice_create, docs_design_web_prototype_onboarding [EXTRACTED 1.00]
- **角色卡 v3 数据契约** — docs_design_web_prototype_handoff_requirements_character_card_fields, docs_design_web_prototype_handoff_requirements_raw_json_schema, docs_design_web_prototype_handoff_requirements_worldbook_entry_fields, docs_design_web_prototype_handoff_requirements_voice_fixed_models, docs_design_web_prototype_character_editor [EXTRACTED 1.00]
- **原型设计 token 与视觉约束系统** — docs_design_web_prototype_ui_design_plan_accent_token, docs_design_web_prototype_ui_design_plan_dual_theme, docs_design_web_prototype_ui_design_plan_layout_primitives, docs_design_web_prototype_ui_design_plan_typography, docs_design_web_prototype_ui_design_plan_icon_system, docs_design_web_prototype_design_handoff_token_extraction [EXTRACTED 1.00]
- **V0.3.3 强逻辑轨道四路并行交付** — docs_v0_3_3_logic_ai_acceptance_delivery_table, docs_v0_3_3_logic_ai_acceptance_character_card_repo, docs_v0_3_3_logic_ai_acceptance_tts_boundary_freeze, docs_v0_3_3_logic_ai_acceptance_serve_mode, docs_v0_3_3_logic_ai_acceptance_pairing_auth [EXTRACTED 1.00]
- **V0.3.8 诊断到 G2 前复核到 G2 验收闭环** — docs_release_notes_v0_3_8_device_diagnostic_2026_09_06_report, docs_release_notes_v0_3_8_pre_g2_review_2026_09_06_doc, docs_release_notes_v0_3_8_g2_acceptance_report_2026_09_06_report [INFERRED 0.95]
- **V0.3.8 G2 实测矩阵 C1 至 C6** — docs_release_notes_v0_3_8_g2_acceptance_report_2026_09_06_c1_notification, docs_release_notes_v0_3_8_g2_acceptance_report_2026_09_06_c2_playback, docs_release_notes_v0_3_8_g2_acceptance_report_2026_09_06_c3_queue, docs_release_notes_v0_3_8_g2_acceptance_report_2026_09_06_c4_delegation, docs_release_notes_v0_3_8_g2_acceptance_report_2026_09_06_c5_lockscreen, docs_release_notes_v0_3_8_g2_acceptance_report_2026_09_06_c6_reuse [EXTRACTED 1.00]
- **角色卡契约体系（契约/映射/状态/接入清单）** — docs_character_card_juesekashujuqiyue, docs_character_card_jiuguanziduanyu_hsr_kuozhanziduanyingshebiao, docs_character_card_qiangshijue_ai_juesekayanglishujuyuzhuangtaimeiju, docs_character_card_v0_3_2_wanchenghoujieruqingdan [EXTRACTED 1.00]
- **千问音色复刻链路（固定契约 / 提交路径 / 边界）** — docs_character_card_juesekashujuqiyue_voiceprofile, docs_character_card_qianwencankaoyinpinnengliyanzhengjilu_gudingqiyue, docs_character_card_qianwencankaoyinpinnengliyanzhengjilu_datauritijiao, docs_character_card_qianwencankaoyinpinnengliyanzhengjilu_gongwangkedadaoxing, docs_character_card_qianwencankaoyinpinnengliyanzhengjilu_daxiaobianjie, docs_character_card_qianwencankaoyinpinnengliyanzhengjilu_shengyinsheji [EXTRACTED 1.00]
- **主体/协处理器深度机制（在场节拍 / 裁决 / 证据 / 记忆）** — philosophy_zhutiself, philosophy_zaichangjieda, philosophy_caijue, philosophy_zhengjuxiabaihe, philosophy_sangeshijianchidu, philosophy_guanxichendian [EXTRACTED 1.00]
- **SillyTavern 五层角色扮演机制** — docs_design_research_sillytavern_advantages_character_card_v3, docs_design_research_sillytavern_advantages_world_info, docs_design_research_sillytavern_advantages_prompt_manager, docs_design_research_sillytavern_advantages_macro_engine, docs_design_research_sillytavern_advantages_context_management [EXTRACTED 1.00]
- **Reasonix 前缀缓存命中的四层机制** — docs_design_research_deepseek_reasonix_implementation_prefix_cache_stability, docs_design_research_deepseek_reasonix_implementation_tail_riding_injection, docs_design_research_deepseek_reasonix_implementation_context_compaction_checkpoint, docs_design_research_deepseek_reasonix_implementation_metadata_stripping [EXTRACTED 1.00]
- **委派—执行—裁决闭环** — config_prompts_characters_firefly_delegation_protocol, config_prompts_assistants_sam_task_request_boundary, config_prompts_characters_reviewer_review_principles, config_pairs_reviewer [INFERRED 0.75]
- **高风险操作判定维度** — config_risk_rules_high_risk_tool_kinds, config_risk_rules_shell_rules, config_risk_rules_patch_max_files, config_risk_rules_sensitive_paths [EXTRACTED 1.00]
- **人类广告文案系统工作流** — docs_website_guanwang_wenan_guize_renlei_guanggao_wenan_xitong, docs_website_guanwang_wenan_guize_renlei_yingxiao_wenan_wuceng, docs_website_guanwang_wenan_guize_chuangyi_mingti, docs_website_guanwang_wenan_guize_chuangyi_xuanze, docs_website_guanwang_wenan_guize_ai_jiafa_ren_jianfa [INFERRED 0.85]
- **AI 文案诊断四维度** — docs_website_guanwang_wenan_guize_kuayemian_yuyi_fangcha, docs_website_guanwang_wenan_guize_pinpai_tihuan_ceshi, docs_website_guanwang_wenan_guize_biaoti_zhengwen_yuyi_chongfu, docs_website_guanwang_wenan_guize_xiuci_jizhongdu [EXTRACTED 1.00]

## Communities (311 total, 42 thin omitted)

### Community 0 - "规划式评审测试夹具"
Cohesion: 0.04
Nodes (128): 计划 A 的测试实现：按预先给定的 ReviewerVerdict 列表依次返回。, ScriptedReviewer, ApprovalMode, CharacterTurn, ProjectRef, ReviewerVerdict, TaskRequestDraft, 切换项目级审批模式（计划 A5：输入区下拉框切换）。 (+120 more)

### Community 1 - "复现脚本与 ACP 链路"
Cohesion: 0.03
Nodes (83): ACP 引擎集成测试：复刻 engine_factory 的 reasonix acp 子进程链路。 验证 WinError 2 修复：initialize…, 原始 ACP 流调试：手工走 initialize → session/new → session/prompt，转储全部消息。, 复现「让角色介绍项目」的对话模型流：确认 stream_reply 是否产出 character.final。 使用仓库根 .env 的真实 DeepSeek…, 复现「跳过跳过→开始使用→回到创建第一个项目」的完整事件链路。 模拟前端 desktopStore 的序号逻辑（hydrate/applyEvents…, Codex 登录状态服务——V0.2 M3（方案 §M3-4）。 Codex app-server 的认证数据是…, _first_markdown_section(), _normalize_title(), 从助手提示词取“身份”一节作为搭档表达配置（名称+表达风格）。 (+75 more)

### Community 2 - "对话上下文与消息模型"
Cohesion: 0.04
Nodes (97): main(), 只保留用户与角色的真实对话，排除助手与工具内部记录。 委派卡（origin=character_delegation 的 user 镜像）是任务指令的副本，…, recent_roleplay_context(), Message, MessageKind, MessageOrigin, MessageSource, MessageStatus (+89 more)

### Community 3 - "ACP 编码引擎"
Cohesion: 0.04
Nodes (52): ABC, ApprovalCallback, main(), AcpCodingEngine, DeepSeek 编程助手（Reasonix ACP v1 客户端）——V0.2 M3（方案 §M3-5）。 复用本地 DeepSeek-Reasonix 的…, 打开（或恢复）ACP 会话。工具审批映射到 ACP 的 tool_approval 配置。, Reasonix ACP 会话的 CodingEngine 适配器。 每个会话（conversation）一个 ACP…, 回复 ACP request_permission 请求（outcome.selected + optionId）。 reasonix 按… (+44 more)

### Community 4 - "会话编排器"
Cohesion: 0.03
Nodes (56): Lock, MessageTarget, ExecutionContext, V0.3.2 M4：不可变执行上下文。 提交被接受时从 SQLite 与搭档目录一次性解析，随该 Turn 传递到角色…, CharacterResultSummary, ConversationOrchestrator, ConversationOutcome, Message (+48 more)

### Community 5 - "前端状态与状态条"
Cohesion: 0.03
Nodes (46): ContextStatusStripProps, LeaseStatusPanelProps, formatSleepSeconds(), PowerStatusBanner(), PowerStatusBannerProps, MobileState, ContextStatusStoreFields, ContextStatusView (+38 more)

### Community 6 - "角色卡模型与 HSR 扩展"
Cohesion: 0.04
Nodes (100): CharacterBook, CharacterCard, HsrExtension, ``data.extensions.hsr``：酒馆标准未覆盖的 HSR 高级扩展。 内容块（world_architecture…, 内部角色卡规范模型。 导入 v2/v3 JSON 或 PNG 时归一化到本模型；导出生成 v3 JSON/PNG。…, SillyTavern depth prompt（权威位置：``data.extensions.depth_prompt``）。…, 首句 + 备选问候总数（导入结果展示用）。, 酒馆世界书（character_book）。 (+92 more)

### Community 7 - "前端命令协议"
Cohesion: 0.03
Nodes (85): SubmitMessageResult, VoiceProvisionResult, APPROVAL_ALREADY_RESOLVED, ApprovalMode, CARD_AVATAR_TOO_LARGE, CARD_AVATAR_UNSUPPORTED, CARD_EXPORT_FAILED, CARD_IMPORT_FAILED (+77 more)

### Community 8 - "UI 图标组件"
Cohesion: 0.04
Nodes (73): AddConversationIcon(), CheckIcon(), CloseIcon(), CollapseIcon(), DarkModeIcon(), DeleteIcon(), EditIcon(), ErrorIcon() (+65 more)

### Community 9 - "Codex 对话模型"
Cohesion: 0.04
Nodes (62): CodexDialogueModel, 用 Codex app-server 为角色提供对话模型。 OpenAI OAuth 的凭据由 Codex 自己管理，因此角色对话也走同一条 app-…, 把 Codex app-server 的文本输出收敛成角色 JSON 对话事件。, OpenAICompatibleDialogueModel, _output_source_label(), _parse_json_object(), _progress_summary_text(), Any (+54 more)

### Community 10 - "角色卡编解码与兼容报告"
Cohesion: 0.05
Nodes (87): _book_to_dict(), _bool_with_default(), _card_data_dict(), CardImportError, _collect_runtime_trigger_paths(), CompatReport, dump_card_v3(), _entry_to_dict() (+79 more)

### Community 11 - "Demo 服务与队列测试"
Cohesion: 0.05
Nodes (83): build_demo_service(), 创建不需要外部凭据、不执行真实文件操作的 Sidecar 服务。, asyncio, MonkeyPatch, Path, V0.2 M2：queue.edit 改文本、queue.withdraw 撤回、queue.prioritize 置队首。, V0.2 M2：conversation_inbox 持久化——重启后 bootstrap 快照仍含队列项。, V0.2 M3：注册即登录；快照携带当前账号与账号列表。 (+75 more)

### Community 12 - "审批管理器"
Cohesion: 0.06
Nodes (63): ApprovalManager, ApprovalRequired, GateOutcome, RuntimeError, V0.2：调用审查智能体并发出 review.started/completed/failed。…, 操作是否携带足够判定风险的信息。 B1 联调：真实 app-server 的 fileChange 审批请求不携带路径 （grantRoot/reason…, O3.1：裁决引擎侧挂起的原生审批请求。 与 :meth:`gate` 的差异： - ``approval_id`` 来自 app-…, 处理用户或审查智能体的裁决。 若用户选择“本对话内允许”，则把操作签名写入当前聊天缓存。 (+55 more)

### Community 13 - "前端动作契约"
Cohesion: 0.03
Nodes (4): HarnessActions, ApprovalViewModel, ApprovalBar(), ApprovalBarProps

### Community 14 - "委派与契约模型"
Cohesion: 0.05
Nodes (54): DelegationDraft, AccountRecord, CharacterProgressSummary, enum_value(), ExecutionReceipt, FrozenModel, MemoryDraft, next_created_at() (+46 more)

### Community 15 - "移动端通知偏好"
Cohesion: 0.05
Nodes (65): DEFAULT_NOTIFICATION_PREFERENCES, IMPORTANCE_OPTIONS, loadNotificationPreferences(), normalizeItem(), NOTIFICATION_TYPES, NotificationImportance, NotificationPreferenceItem, NotificationPreferences() (+57 more)

### Community 16 - "桌面后端应用服务"
Cohesion: 0.03
Nodes (29): 关闭自建 client；注入的 client 交由调用方关闭。, DesktopApplicationService, 审批归属当前展示聊天；V0.3.2 M4 起审批项自身携带聊天/任务 id。, 是否存在未过期的远程控制租约（V0.3.9 契约 §6）。 读取前先做一次惰性回收，保证过期租约不会继续阻断桌面播放。, 桌面朗读被抢占（V0.3.9 契约 §7：voice.playback_interrupted）。, 抢占桌面本地朗读（契约 §6）。 运行时未提供抢占入口（测试替身）时如实跳过：既有的 stop_speaking_async…, V0.3.8 T1（契约 §14.3）：WS 心跳——响应携带服务端时间作活性信号。 客户端约 30s 收不到任何入站消息即判定半开连接，主动断开走既有重连。…, 把已完成 ASR 的文本送入同一条后台 Turn 链。 M4.3：PTT 开始后不可变上下文优先；即使用户录音期间切换会话，… (+21 more)

### Community 17 - "前端服务与快照模型"
Cohesion: 0.07
Nodes (7): QueueItemRow(), QueueItemRowProps, DesktopSnapshot, ProjectRecord, QueueItem, MockScenario, MockDesktopBackend

### Community 18 - "搭档头像与视图模型"
Cohesion: 0.07
Nodes (48): getPairAvatars(), PAIR_AVATARS, PairAvatars, AccountGateViewModel, ChatTabsViewModel, useDesktopStore(), AppShell(), runTest() (+40 more)

### Community 19 - "存储增量缓冲与刷盘"
Cohesion: 0.04
Nodes (18): Row, 在一个 SQLite 事务里写入全部配置与密钥。 任一条写入失败都会回滚整个事务，调用方数据库保持旧值；成功后才 提交，供配置保存的“先验证后提交”流程使用。, 把消息放入普通增量缓冲（contract-v1 第 4 节）。 同一 message_id 只保留最后状态，位置保持首次出现；达到 50 条…, 把工具记录放入普通增量缓冲；主键是 (conversation_id, tool_call_id)。, 返回最老挂起写应刷盘的绝对单调时间；没有挂起写时返回 None。 接线方用它调度定时刷盘（loop.call_at），到点调用 flush_if_due。, 按 50 条 / 50ms 阈值刷盘；未到阈值返回 False，不做任何写入。, 把缓冲写入一个非空事务；失败原样抛出且缓冲保留。 返回写入行数。事务失败时不丢弃缓冲，调用链拿到原始异常后可以 决定重试或退出，不把失败写成成功。, 写入计数器（测试与诊断用，不参与业务语义）。 (+10 more)

### Community 20 - "AppController 控制器"
Cohesion: 0.05
Nodes (22): AppController(), AppControllerProps, DesktopCommand, DesktopEvent, DesktopResponse, controller, ErrorBoundary, initialConversationId (+14 more)

### Community 21 - "移动端音频与 ASR 会话"
Cohesion: 0.06
Nodes (51): _AsrSession, _feed_stream(), MobileAsrSessionManager, MobileAudioError, MobileTtsInterrupted, MobileTtsSequencer, Any, Queue (+43 more)

### Community 22 - "角色卡界面与兼容弹窗"
Cohesion: 0.06
Nodes (55): CompatReportPayload, CharacterCardSummaryView, CharacterCardItem(), CharacterCardItemProps, CharacterCompatModal(), CharacterCompatModalProps, CompatPhase, isPlainObject() (+47 more)

### Community 23 - "桌面协议编解码测试"
Cohesion: 0.06
Nodes (64): DesktopCommand, encode_message(), Any, 编码单行协议消息；调用方负责追加换行并 flush。, response_ok(), test_parse_request_and_encode_jsonl(), command(), DesktopCommand (+56 more)

### Community 24 - "语音运行时接线"
Cohesion: 0.05
Nodes (23): 账号级配置 + 密钥合并视图（api_key 保留明文供运行时使用）。, V0.3.2 M6：按当前账号语音配置重建 VoiceRuntime。 调用方必须已持有账号切换锁（config.set / _switch_account…, voice 快照：先同步待播队列长度（VoiceMiniPlayer 的 queuedCount）。, 广播 voice 快照（事件与命令响应共用）。, 清除已不再成立的语音错误（V039-S4-012）。 ``scope`` 限定来源：合成恢复只清除合成错误，识别错误保持原样。…, 角色自然语言回复 → 手机 TTS 下发；助手/工具/思考零下发。 ``voice_id`` 由调用方（_on_message）预判注入：无可用音色时如实…, 移动端朗读的可用音色解析（message.created 预判与 relay 共用）。 与 _relay_mobile_tts_task 同规则：卡级…, V0.3.2 M6：语音账号配置 + 6 说话方生成状态视图（不含明文 Key）。 (+15 more)

### Community 25 - "桌面状态仓库"
Cohesion: 0.05
Nodes (52): ConversationOpenResult, MemoryWirePayload, pairMemoryFromPayload(), recordMemoryWrite(), resolveMemoryConversationId(), activeTasksFromSnapshot(), applyBusinessEvent(), applyConnectionStatus() (+44 more)

### Community 26 - "语音播放与采集控制"
Cohesion: 0.05
Nodes (25): Task, 待播队列条数（不含正在播放的当前条）；VoiceMiniPlayer 的 queuedCount。, V0.3.3：助手永不使用 TTS——此开关仅保留给账号配置同步路径调用。 已不再影响任何 TTS 入队：助手消息一律由…, 打开麦克风；VAD 可单独关闭，但仍保留采集供 PTT。, 只切换 VAD；关闭 VAD 时不关闭麦克风，保证 PTT 仍可用。, 启动唯一的播放消费任务与播放器线程；重复调用无效。, B2 UI 退出时关闭采集、识别与播放任务。, 后台提交 PTT 文本；停止聆听不能等待模型或工具回合。 (+17 more)

### Community 27 - "角色上下文窗口与摘要"
Cohesion: 0.07
Nodes (53): utc_now(), 进入角色上下文的原文窗口（契约 §2）。 - 尚无成功摘要覆盖：保留最近 ``ROLE_CONTEXT_LIMIT_PRE_SUMMARY`` 条； -…, role_context_window(), completed_summary(), ConversationSummary, failed_summary(), is_final_message(), messages_after_coverage() (+45 more)

### Community 28 - "长期记忆与身份"
Cohesion: 0.07
Nodes (53): active_memories(), character_ref_card_id(), character_ref_for(), ConversationIdentity, is_card_character_ref(), memory_event_payload(), MemoryError, MemoryScope (+45 more)

### Community 29 - "世界书激活与 token 估算"
Cohesion: 0.12
Nodes (59): activate_world_book(), 冻结的近似 token 计数（契约 §3.8）。 ``CJK 字符数 + ceil(非 CJK 字符数 / 4)``；CJK 判定含中日韩统一表意 文字及扩展…, 世界书运行时激活（契约 §3.2-§3.8）。 ``scan_texts`` 为时间正序的最近对话文本；生效扫描深度 ``book.scan_depth ??…, token_estimate(), _book(), _entry(), 世界书运行时激活引擎测试（V0.3.7 契约 §3、§6、§12 锚点）。, 最小反例：两英文单字符条目的边际之和是 1，而单条估算之和是 2。 token_estimate 对非 CJK 取… (+51 more)

### Community 30 - "搭档配对与助手提示词"
Cohesion: 0.05
Nodes (59): 流萤 × 萨姆 配对配置, 三月七 × 第四面镜 配对配置, 白厄 × 神秘的古代机械 配对配置, 审查智能体 × 神秘的古代机械 配对配置, 神秘的古代机械 执行助手提示词, 第四面镜 执行助手提示词, 萨姆 执行助手提示词, TaskRequest / TaskAmendment 执行边界 (+51 more)

### Community 31 - "引导与设置界面"
Cohesion: 0.06
Nodes (38): RemotePairingViewModel, SettingsViewModel, Onboarding(), OnboardingProps, QrCode(), QrCodeProps, DIALOGUE_PROVIDER_IDS, DIALOGUE_PROVIDERS (+30 more)

### Community 32 - "V0.3.9 R1 重置脚本测试"
Cohesion: 0.06
Nodes (50): _apply_deny_delete_ace(), _current_user_sid(), _delete_succeeds(), _parse_errors(), CompletedProcess, fixture, Path, r"""V039-R1-001 / V039-S4-010：首启清理脚本的编码与失败传播测试（离线）。… (+42 more)

### Community 33 - "V0.3.9 存储测试"
Cohesion: 0.10
Nodes (55): fixture, store(), _drop_v039_objects(), _message(), _metric(), Connection, MonkeyPatch, Path (+47 more)

### Community 34 - "聊天页测试与假 WebSocket"
Cohesion: 0.06
Nodes (37): CONVERSATION, FakeWebSocket, lastFrameOf(), lastInstance(), lastSentFrame(), openConversationOnce(), SAMPLE_APPROVAL, SAMPLE_MESSAGE (+29 more)

### Community 35 - "场景夹具与 Mock 数据"
Cohesion: 0.07
Nodes (42): baseSnapshot(), conversation(), createMockScenario(), defaultLocalAccount, demoAccount, message(), MOCK_PAIRS, MOCK_SCENARIO_NAMES (+34 more)

### Community 36 - "桌面后端角色卡命令"
Cohesion: 0.07
Nodes (17): AvatarAsset, ``data.extensions.hsr.avatar_asset``：内部头像资产引用。 只保存引用与来源信息，不把图片二进制写进角色卡 JSON；…, Path, V0.2 快速接受（问题 1）：同步落库用户消息，立即返回真实 id。 回合处理移到后台任务（``_run_submit_turn``），前端按真实…, V0.2 M2：队列变化推送全量快照（按 position 有序）。, 编辑队列项文本（仅尚未派发的 queued 项）。, 撤回队列项（不再自动派发，状态置 withdrawn）。, 逐条朗读：按 message_id 从会话取消息文本，重新合成入队（可重播）。 (+9 more)

### Community 37 - "移动端委派卡"
Cohesion: 0.07
Nodes (39): DelegationCard(), DelegationCardProps, DelegationStatus, STATUS_TEXT, ArrowDownIcon(), BackIcon(), CheckIcon(), ChevronDownIcon() (+31 more)

### Community 38 - "Silero VAD 语音活动检测"
Cohesion: 0.07
Nodes (40): DemoVoiceActivityDetector, 按注入的状态序列输出 VAD 事件，用于验证状态机。, copy_reference_model(), Path, RuntimeError, Silero VAD v5 本地语音活动检测（B2）。 把 16 kHz 单声道 int16 PCM 块流切成语音事件。内部： - 任意大小的 PCM 块按…, 把旧项目的 silero_vad_v5.onnx 复制到项目 assets/models/。, VAD 模型文件缺失或 onnxruntime 不可导入。 (+32 more)

### Community 39 - "世界书深度注入激活"
Cohesion: 0.06
Nodes (48): ActivatedEntry, ActivationDiagnostics, ActivationResult, _append_budget_warnings(), collect_turn_triggers(), DepthEntryGroup, _entry_not_run_fields(), _entry_ref() (+40 more)

### Community 40 - "角色卡仓库"
Cohesion: 0.07
Nodes (30): CardRecord, CardSummary, CharacterCardRepository, _now(), 以传入卡重新 dump 覆盖 card_json，刷新 updated_at。, 导入一张解析后的卡：state=imported, source=tavern_import，新 card_id。 ``as_duplicate=True``…, 复制一张卡：新 card_id、名称加后缀（副本），state/source 与源卡一致。, 归档一张卡：draft 状态拒绝；已归档的保留原名与状态，仅进归档集合。 (+22 more)

### Community 41 - "后端引导与快照解析"
Cohesion: 0.08
Nodes (16): _params_card_id(), Any, Message, remote_control 快照/状态：state/device_key/expires_at/ grace_expires_at/reason，无值一律…, params.character_card_id 的显式值；空/缺失返回 None（走 active 快照）。, V0.3.2 M4/M5：多窗口显式读取命令（只读装载，不改变全局导航）。 ``view_id`` 由前端携带用于路由，Sidecar 不保存窗口导航状态；本…, V0.2：独立模式命令——只改模式，返回定向响应，不回推整份快照。, 当前可作为新对话角色身份的 active 卡；draft 与归档卡不生效。 (+8 more)

### Community 42 - "V0.3.5 接线测试"
Cohesion: 0.10
Nodes (46): asset_dir(), call(), create_conversation_model(), create_published_card(), expect_service_error(), force_voice_profile(), grant_voice_credentials(), Path (+38 more)

### Community 43 - "电源状态采集"
Cohesion: 0.07
Nodes (48): _build_reason(), _capture(), _console_output_encoding(), _decode_bytes(), _parse_ac_dc(), _parse_plan_name(), PowerStatus, PowerStatusError (+40 more)

### Community 44 - "Demo 语音合成"
Cohesion: 0.08
Nodes (35): DemoSpeechSynthesizer, AudioChunk, SpeechRequest, SpeechSynthesizer, _character_message(), GatedSynthesizer, _pair_config(), asyncio (+27 more)

### Community 45 - "千问语音合成适配器"
Cohesion: 0.08
Nodes (37): _ActiveSynthesis, RuntimeError, Task, QwenSpeechSynthesizer, QwenTtsError, Qwen TTS 流式合成适配器（B2.4）。 用 ``dashscope.audio.tts_v2.SpeechSynthesizer`` 的…, 后台等待一个被放弃等待的合成线程任务；确实卡死才如实告警。, qwen-audio-3.0-tts-flash 流式合成。 ``api_key`` / ``ws_url`` 可显式传入；缺省按… (+29 more)

### Community 46 - "服务模式集成测试"
Cohesion: 0.08
Nodes (42): StringIO, _capture_service(), _events(), _free_port(), _isolate_from_dev_env(), Any, asyncio, ClientWebSocketResponse (+34 more)

### Community 47 - "移动端连接生命周期"
Cohesion: 0.08
Nodes (18): current(), find(), Frame, snapshot, clearCredentials(), INBOUND_STALE_MS, MobileWsClient, PendingEntry (+10 more)

### Community 48 - "语音运行时测试"
Cohesion: 0.10
Nodes (41): FakeRecognizer, FakeSynthesizer, FakeVad, make_runtime(), Any, SimpleNamespace, B2.6 VoiceRuntime 单元测试：注入假适配器验证上行/下行协调行为。 覆盖设计文档 §5 的关键行为： - VAD 完整流：静音期 pre-…, 消费完整音频流后按序产出 partials 与 final 的假 ASR。 ``blocks``/``on_blocks``：收到第 ``blocks``… (+33 more)

### Community 49 - "移动端语音播放"
Cohesion: 0.07
Nodes (25): MobileTtsChunk, MobileVoicePlayback, TTS_MAX_BUFFERED_PCM_BYTES, createEngineHarness(), EngineHarness, FakeAudioBuffer, FakeAudioBufferSourceNode, FakeAudioContext (+17 more)

### Community 50 - "角色卡导出流程"
Cohesion: 0.08
Nodes (37): CardExportJsonResult, CardExportPngResult, CardImportJsonResult, CardImportPreviewPayload, CharacterExportFlow(), ExportFormat, ExportPhase, getExtensionKeys() (+29 more)

### Community 51 - "移动端依赖清单"
Cohesion: 0.05
Nodes (43): dependencies, react, react-dom, @tanstack/react-virtual, @tauri-apps/api, @tauri-apps/plugin-notification, zustand, devDependencies (+35 more)

### Community 52 - "PNG 角色卡读写"
Cohesion: 0.10
Nodes (41): _chunk_bytes(), _iter_chunks(), _make_text_chunk(), png_image_dimensions(), PngCardError, ValueError, Character Card v2/v3 PNG 元数据读取与 v3 PNG 写入。 PNG 角色卡约定（SillyTavern 惯例）： -…, 把 v3 角色卡元数据写入头像 PNG，返回单文件角色卡字节。 移除原有 ``chara``/``ccv3`` tEXt 块后在 IHDR 之后插入新的… (+33 more)

### Community 53 - "诊断抽屉"
Cohesion: 0.11
Nodes (31): DiagnosticsDrawer(), DiagnosticsDrawerProps, DiagnosticsTab, DiagnosticsDrawerHostProps, formatCharRange(), formatDurationMs(), formatMemoryInjected(), formatMetricNumber() (+23 more)

### Community 54 - "Codex 传输集成测试"
Cohesion: 0.09
Nodes (24): QueueJsonLineConnection, ExitedConnection, asyncio, app-server EOF 要保留退出码/启动 stderr，而不是只报泛化 EOF。, O2.3：取消任务发出 turn/interrupt，参数携带 threadId 与 turnId。, O3.1：服务端发起的请求（带 id+method，如 requestApproval）不得被 当作客户端请求的响应（否则挂起请求被错误消费、裁决回复丢失）。, B1：app-server 协议要求 initialize 握手先于 thread/start。 真实 app-server 未握手时返回 {"code":…, M1.3：app-server 存活但不发事件时，短超时先 interrupt 再 TURN_FAILED。 (+16 more)

### Community 55 - "电源状态测试"
Cohesion: 0.08
Nodes (22): _cp(), _FakeRunner, CompletedProcess, parametrize, skipif, _query_out(), power 模块单元测试（V0.3.7 契约 §1.5 / §8）。 覆盖：真实形状样例解析（中文标签 + 8 位十六进制索引，GUID 行原样）、 16…, 控制台代码页对应无效编码名（LookupError）时跳过该候选，不影响后续解码。 (+14 more)

### Community 56 - "千问流式语音识别"
Cohesion: 0.11
Nodes (36): _append_stable_segment(), _BridgeEvent, _fold_events(), _longest_suffix_prefix_overlap(), merge_asr_partial(), merge_asr_segments(), _prefer_more_complete(), AbstractEventLoop (+28 more)

### Community 57 - "JSONL 子进程传输"
Cohesion: 0.09
Nodes (18): ConnectionFactory, JsonlProcessTransport, Any, BaseException, RuntimeError, V0.3.2 M3：返回按 session 路由的键。 只对携带 ``params.sessionId`` 的 ACP…, 单个 ACP session 的通知订阅器（V0.3.2 M3）。 ``next()`` 只返回路由到该 session 的事件；transport…, One-reader JSONL RPC transport with request correlation. (+10 more)

### Community 58 - "Tauri 后端重连与退避"
Cohesion: 0.06
Nodes (20): AllocConsole(), BACKOFF_MAX_SECS, BACKOFF_START_SECS, classify_exit(), configure_console(), debug_console_requested(), encode_request_line(), ExitClass (+12 more)

### Community 59 - "会话投影"
Cohesion: 0.12
Nodes (36): build_projection(), ConversationProjection, _created_at_text(), message_timeline_key(), projection_diagnostics(), ProjectionError, ProjectionItem, Any (+28 more)

### Community 60 - "边车协议解析"
Cohesion: 0.08
Nodes (24): CommandValidationError, ValueError, 前端命令结构不符合 Sidecar 协议。, parse_request(), protocol_error(), ProtocolError, ValueError, 一行 JSONL 无法解析或不是请求对象。 (+16 more)

### Community 61 - "摘要与投影存储校验"
Cohesion: 0.07
Nodes (16): ConversationSummary, ProjectionEntry, Any, field_validator, 持久化投影条目：只存引用与顺序，不复制原文（契约第 2 节）。 - position：投影内顺序，0 起，按会话唯一； -…, 返回该条目引用的记录 id（按其 kind）。, 聊天级摘要（契约第 2 节）。 covers_* 描述连续、已最终落库的消息区间；content 是模型产出的结构化…, _require_text() (+8 more)

### Community 62 - "OpenAI 兼容层测试"
Cohesion: 0.11
Nodes (28): _deepseek_model(), _info_messages(), _mock_stream_transport(), handler(), asyncio, LogCaptureFixture, MockTransport, DeepSeek 结构化端点持续空输出：有界重试后仍失败才报「输出为空」。 不合成结果：三次真实请求后直接抛错（初始 + 2 次有界重试）。 (+20 more)

### Community 63 - "事件扇出"
Cohesion: 0.09
Nodes (20): RemoteEventWriter, EventFanout, 可退订的订阅句柄；unsubscribe 幂等。, 事件扇出：stdout 权威 + 全部已订阅远程连接。 publish 先写 stdout（JsonlWriter，唯一权威写入器），再逐个写已订阅连接。…, 扇出一条事件。 默认先写 stdout（唯一权威）再写全部远程订阅者；BrokenPipe 语义由 JsonlWriter…, 是否存在已订阅的远程连接（手机 TTS 只在有在线端时合成）。, _Subscription, JsonlWriter (+12 more)

### Community 64 - "高级编辑器面板"
Cohesion: 0.12
Nodes (27): ADVANCED_SECTIONS, AdvancedEditorPanel(), TreeSection, ArrowLeftIcon(), InfoIcon(), CommandPanelsView(), renderPanelValue(), MufyAdvancedEditor() (+19 more)

### Community 65 - "角色资产服务"
Cohesion: 0.08
Nodes (27): AssetRecord, CharacterAssetError, CharacterAssetService, _infer_extension(), _now(), Path, RuntimeError, 角色卡受管理资产服务（V0.3.5 强逻辑 AI 轨道，成员 C）。 契约：``docs/plans/V0.3.5-契约冻结.md``… (+19 more)

### Community 66 - "记忆命令处理"
Cohesion: 0.08
Nodes (25): _iso_timestamp(), _json_text(), _memory_payload(), _optional_datetime(), _optional_text(), params 中可选的字符串；空串/缺失返回 None。, params 中可选的 ISO 时间字符串；不可解析抛 ValueError（由调用方转业务错误码）。, storage 记录的时间戳 → 协议载荷文本。 契约 §5：只读查询必须可序列化；记录层持有 datetime，协议层统一为 ISO 8601… (+17 more)

### Community 67 - "深度注入消息装配测试"
Cohesion: 0.12
Nodes (36): _assembled(), _injection(), make_model(), make_request(), _message(), asyncio, ProjectRuntimeContext, SimpleNamespace (+28 more)

### Community 68 - "假聊天服务器测试"
Cohesion: 0.13
Nodes (33): BaseHTTPRequestHandler, fake_chat_server(), _FakeChatHandler, make_model(), make_request(), asyncio, fixture, MonkeyPatch (+25 more)

### Community 69 - "WebSocket 服务测试"
Cohesion: 0.14
Nodes (32): ClientSession, _auth_ws(), _event(), FakeDispatch, _free_port(), Any, asyncio, ClientWebSocketResponse (+24 more)

### Community 70 - "Android 版本号测试"
Cohesion: 0.08
Nodes (26): _AndroidBuildSandbox, _properties_lines(), CompletedProcess, fixture, parametrize, Path, r"""V039-R2-002：Android 打包脚本必须让 APK 带上真实版本号（离线）。…, 脚本只对工具链做存在性检查，空占位文件即可满足。 (+18 more)

### Community 71 - "移动端状态仓库"
Cohesion: 0.10
Nodes (29): applySnapshot(), base64PcmByteLength(), client, decodeMemoryPayload(), endedTtsMessages, indexConversations(), memoryIdFromPayload(), MobileVoiceCapture (+21 more)

### Community 72 - "发布缺陷与验收门禁"
Cohesion: 0.10
Nodes (33): D1 播放状态循环回写, D2 双端缺少播放设备互斥, D3 锁屏返回白屏与恢复失败, D5 缺省创建符合 reuse_active 契约, 诊断证据索引与原始留痕归档, G2 真实设备验收门禁, G3 PR 与合并流程, C1–C6 验收矩阵 (+25 more)

### Community 73 - "角色创建页"
Cohesion: 0.12
Nodes (27): CardAvatarPayload, AdvancedEditorPanelProps, BasicInfoSection(), BasicInfoSectionProps, CharacterCreatePage(), formatTime(), CharacterLivePreview(), CharacterLivePreviewProps (+19 more)

### Community 74 - "移动端应用外壳"
Cohesion: 0.11
Nodes (19): App(), describeAuthFailure(), CONNECTION_MESSAGES, ConnectionBanner(), ErrorBoundary, ErrorBoundaryProps, ErrorBoundaryState, currentRoute (+11 more)

### Community 75 - "委派重试测试"
Cohesion: 0.16
Nodes (32): _failed_result(), _final_turn(), _model(), asyncio, MockTransport, 委派失败重试与失败可见性。 委派判定权交给语言模型自己（运行时协议的 delegate 字段），代码只查…, 模型自报 delegate=true 却没带 delegation → 通用端点也要纠偏重试。 用户说法不受词典约束（“这个项目是做什么的呢”与“删掉…, 用户措辞不含任何资源词（截图中删除 Hello World 点 txt 的形态）： 只要模型自报 delegate=true 就必须纠偏，不再依赖关键词。 (+24 more)

### Community 76 - "V0.3.8 委派执行链测试"
Cohesion: 0.11
Nodes (28): _conversation_id(), _drain_turn(), _enqueue(), _make_engine(), asyncio, V0.3.8 T4：委派执行链修复的回归测试（真机验收 C4）。 覆盖（docs/plans/V0.3.8-修复实施计划.md §2 T4、契约…, Reasonix 静默时持续告警，达到上限后取消真实回合并失败。, 每 60s（测试压缩为 0.1s）无事件发一次 diagnostic.warning，节流可预期。 (+20 more)

### Community 77 - "V0.3.9 B03 仅聊天补全测试"
Cohesion: 0.13
Nodes (28): command(), EventLog, _isolate_dialogue_env(), Any, DesktopCommand, MonkeyPatch, Path, B-03（V0.3.9）：产品只支持 OpenAI Chat Completions 兼容端点。 复测证据… (+20 more)

### Community 78 - "边车入口与信号处理"
Cohesion: 0.09
Nodes (24): build_parser(), _detect_lan_ip(), _install_sigint_stop(), main(), ArgumentParser, Namespace, 尽力探测本机在局域网中的源地址（UDP connect 不发包）。 返回 None 表示探测失败（如实暴露，不伪造可达地址）：调用方不得上报…, 决定启动接线，返回 ``(demo, 来源)``。 V039-S4-002：接线只由显式声明决定，不按账号是否配置过供应商做启发式… (+16 more)

### Community 79 - "Codex 登录状态测试"
Cohesion: 0.12
Nodes (24): make_service(), MonkeyPatch, Path, V0.2 M3：Codex 登录状态服务（方案 §M3-4，账号隔离）。, M3.4：重复 start_login 必须先终止并等待旧登录进程，再创建新进程。, M3.4：.cmd/.bat 登录命令对含空格路径使用 Windows 正确引用。, M3.4：waiting 只在完整 token 可读且登录进程终态明确后清除。, M3.4：auth.json 经同目录临时文件原子替换，不残留半写临时文件。 (+16 more)

### Community 80 - "SQLite 存储与 schema 迁移"
Cohesion: 0.11
Nodes (31): _old_schema_connection(), Connection, Path, 构造 O4.3 迁移前的旧库（user_version=0 的 v0 结构）。 与历史 schema.sql 一致：projects 无…, O4.3：新库由 schema.sql 一次建全，直接标记 SCHEMA_VERSION。, O4.3：旧库（user_version=0）打开时逐级升级，数据保持可用。 迁移前：projects 无…, F6：聊天归属账号——创建写入 account_id，列表按账号过滤。, M3.3：批量配置/密钥写入任一条失败时整批回滚。 (+23 more)

### Community 81 - "Tauri 后端状态类型"
Cohesion: 0.11
Nodes (25): Arc, AtomicBool, AtomicU64, Child, ChildStdin, ChildStdout, BackendState, backoff_delay() (+17 more)

### Community 82 - "世界书条目编辑器"
Cohesion: 0.15
Nodes (28): WorldBookEntryEditor(), WorldBookEntryEditorProps, asStringList(), collectEntryNotRunFields(), DEFAULT_DEPTH, DEFAULT_ROLE, displayPositionRaw(), ENTRY_NOT_RUN_KEYS (+20 more)

### Community 83 - "千问流式识别测试"
Cohesion: 0.11
Nodes (26): QwenStreamingRecognizer, qwen-audio-3.0-asr-flash-streaming 流式识别。 ``api_key`` / ``ws_url``…, factory(), _events(), fake_sdk(), fake_tts_sdk(), FakeResult, fixture (+18 more)

### Community 84 - "存储批量写入"
Cohesion: 0.09
Nodes (11): Project, _now(), 更新聊天最近持久化业务变化时间（列表排序用，契约第 1 节）。 批量刷盘时整批只调用一次/会话，避免每条消息都写一次。, 一个事务写入多条消息（导入/迁移/测试），顺序按入参顺序。, 一个事务写入多条工具记录，顺序按入参顺序。, 一个事务写入若干行；每个受影响聊天只更新一次 updated_at。, 记录最近打开项目，并返回更新后的项目对象。, 按规范化目录查找项目，避免同一目录重复创建项目记录。 M4.5：必须检查所有项目（含已归档），否则再次选择已归档目录会 静默创建第二条同根记录。 (+3 more)

### Community 85 - "ACP 引擎测试"
Cohesion: 0.13
Nodes (29): asyncio, V0.2 M3：DeepSeek 编程助手（Reasonix ACP）适配器（方案 §M3-5）。 用内存 JSONL 连接模拟 ``reasonix…, prompt 响应先到时，短暂延后的工具回执仍进入事件流。, codec 兼容分支：snake_case 字段、dict 结果文本、rejected → failed。, 按脚本改写 session/prompt 响应：指定 stopReason、去掉它或注入 error。…, V039-S4-009：工具与正文全部成功后 stopReason=error，终态仍必须是 failed。…, stopReason=cancelled 是协议终态，既不是 failed 也不伪装成 completed。, max_turn_requests 等非成功终态如实上报失败，并带上协议原始取值。 (+21 more)

### Community 86 - "PWA 静态资源路由"
Cohesion: 0.09
Nodes (20): Response, add_static_routes(), index(), _not_found(), Application, Path, Request, 装配 PWA 静态路由。 - static_root 为 None 时，GET / 及任意静态路径统一返回 404，如实报错、不合成页面； -… (+12 more)

### Community 87 - "摘要事件载荷与身份"
Cohesion: 0.11
Nodes (19): ``summary.started/completed/failed`` 事件载荷（契约 §2）。 失败事件额外携带…, summary_event_payload(), _message_index(), 消息展示标签（摘要输入用；只用于上下文呈现，不做语义改写）。, 按 message_id 找消息下标；不存在返回 None（真实失败由调用方处理）。, 摘要记录的 covers 区间在 messages 中的消息窗口（role 消息）。 区间端点必须是最终落库的真实消息；端点不存在返回空元组（调用方按…, 模型返回的 JSON 对象 → 存储层 content 文本（JSON 序列化，不改写内容）。, summary.regenerate：对真实失败记录或用户显式请求重新生成摘要。 契约 §2：仍调用配置的真实模型；生成失败保留真实失败状态并广播… (+11 more)

### Community 88 - "移动端连接提示与设备列表"
Cohesion: 0.13
Nodes (19): ChatStatusHint(), ChatStatusHintProps, CONNECTION_HINTS, ConnectionBannerProps, DeviceListPanel(), DeviceListPanelProps, formatLocalDateTime(), deviceText() (+11 more)

### Community 89 - "Codex 鉴权服务"
Cohesion: 0.10
Nodes (13): CodexAuthService, Path, 启动 Codex 官方浏览器 OAuth；未传可执行文件时只进入等待态。 重复调用会先终止并等待旧登录进程退出，再创建新进程，避免多个 OAuth…, OpenAI API Key 登录：写 auth.json（保留现有 chatgpt token）。, 同目录临时文件写入后原子替换，避免 auth.json 半写。, 终止旧登录进程并等待其退出；普通 terminate 无效时强制结束。, 取消 waiting 态（浏览器流程放弃后回到 logged_out）。, 读取 auth.json；解析失败时返回空 dict 和保留的错误说明。 (+5 more)

### Community 90 - "审批代理"
Cohesion: 0.09
Nodes (13): ApprovalBroker, 把 Orchestrator 的异步审批等待桥接成桌面事件与命令。 V0.3.2 M4：``request`` 显式接收 conversation_id 与…, 已决终态记录（未决或未知返回 None）。, 标记该终态的 approval.resolved 已广播（引擎路径去重用）。, 取消指定会话未决的审批并发出 resolved 事件。 Turn 取消时调用：把正在等待用户裁决的审批按 DENY 结清，让编排器…, V0.3.2 M4：只拒绝目标任务的未决审批（并发聊天互不影响）。, 记录终态（首个终态获胜）并按需广播 approval.resolved。 V0.3.9 契约…, EventEmitter (+5 more)

### Community 91 - "Codex 审批流集成测试"
Cohesion: 0.14
Nodes (23): FakeCodexAppServer, drive_approval_turn(), make_transport(), asyncio, O3.1：审批体系统一 —— 适配器层全链路测试。 场景：orchestrator 经 CodexAppServerEngine 跑真实传输协议， app-…, 完全允许运行：引擎仍发起请求时直接回复 accept，无需用户交互。, O3.1：open_session 预留策略映射位置——thread/start 参数携带 approvalPolicy / sandbox /…, 默认 None 不发送策略字段，保持既有协议形态。 (+15 more)

### Community 92 - "协议契约文档节点"
Cohesion: 0.10
Nodes (28): docs 文档索引, 渐进式披露文档索引约定, 消息路由（target / origin / delegation_id）, 流式输出与推理独立通道, 配对 URL 支持 IPv6 且不伪造回环地址, 手机事件按 stream_id + sequence 单一归并, D4 首次配对停留（auth_failed 等待缺口）, 配对与连接竞态修复 (+20 more)

### Community 93 - "回合指标存储"
Cohesion: 0.10
Nodes (15): BaseModel, 回合/任务指标行（契约第 5 节）。 未观测或供应商不提供的字段保持 None，键始终存在；真实零值使用 0。 禁止用字符数估算 token——需要真实…, metrics.query 的存储层过滤条件（契约第 5 节）。 limit 默认 50、上限 200；cursor 是不透明游标，由…, 一页指标结果；next_cursor 为 None 表示没有更多。, _Record, TurnMetric, TurnMetricPage, TurnMetricQuery (+7 more)

### Community 94 - "语音试听声源校验测试"
Cohesion: 0.15
Nodes (21): command(), DesktopCommand, V0.3.3：试听只放行角色侧声源；助手侧说话人声源一律拒绝 assistant_tts_disabled。, test_voice_preview_allows_character_but_rejects_assistant_speakers(), _make_service(), PausingEngine, asyncio, V0.3.2 M4：后端多聊天并发的服务级验收。 并发单位是 conversation：不同聊天的提交立即运行、A/B 事件互不串线；… (+13 more)

### Community 95 - "基础信息表单与头像"
Cohesion: 0.12
Nodes (17): AVATAR_FILTER, SUPPORTED_AVATAR_TYPES, AlertCircleIcon(), ChevronDownIcon(), ChevronRightIcon(), CloseIcon(), PlusIcon(), TrashIcon() (+9 more)

### Community 96 - "对话供应商配置"
Cohesion: 0.09
Nodes (15): _duration_ms(), _legacy_engine_notice(), _nullable_int(), _provider_unavailable(), 非负整数取值，否则 None（契约 §5：未观测保持 null，不用 0 顶替）。, ISO 时间差（毫秒）；任一端不可解析时保持 None。 同一时刻差值为真实 0，不用 None 顶替。, 把回合终态写为 TurnMetric（幂等：同 turn 重复终态以首次写入为准）。 契约 §5：未观测或供应商不提供的字段为 null 且键仍存在，真实零值…, 不受支持的供应商（当前只有历史 OpenAI OAuth）→ 可定位原因；支持则 None。 (+7 more)

### Community 97 - "回合调度与终态"
Cohesion: 0.09
Nodes (16): _on_done(), _failure_reason(), BaseException, RuntimeError, Task, 失败原因文本（V039-S4-015 回合路径 / V039-R2-001 探测路径）。 只拼装真实可得的信息：异常自述优先；自述为空时回落到类型名与结构化…, 登记后台回合，并在结束时清除对应会话的忙碌标记。 M1.1：同一会话已有未完成任务时禁止覆盖旧引用；done callback…, 创建并登记 Turn（accepted 态），返回 payload。 V0.3.9 §5：来源身份随 Turn payload 落到运行态记录，终态指标从… (+8 more)

### Community 98 - "配对级长期记忆存储"
Cohesion: 0.12
Nodes (16): MemoryScope, PairMemory, 长期记忆作用域（契约第 1 节）。 五个分量必须全部非空：项目为空的日常聊天不读写长期记忆； assistant_identity 是当前权威搭档配置的…, 配对级长期记忆（契约第 1/2 节）。 content 由模型负责；存储层只校验结构与作用域。status 为 active|deleted，…, PairMemory, 写入或更新一条长期记忆（同作用域同内容幂等）。 作用域五个分量必须全部非空，否则 ValueError——项目为空的日常…, 更新记忆内容或状态；未传字段保持原值。 可选传入 scope 校验并锁定作用域（含 assistant_identity），不匹配报…, 软删除：status 置 deleted 并持久化（真实状态，不物理删除）。 (+8 more)

### Community 99 - "角色卡 PNG 命令测试"
Cohesion: 0.10
Nodes (26): command(), DesktopCommand, fixture, Path, card.peek_import / card.import_png / card.export_png 命令测试（V0.3.7 集成波）。…, 签名为 PNG 但内容损坏：如实报 card_import_failed 且 message 非空。, import_png 全链路：落库 + 头像资产真实入库 + hsr.avatar_asset 回写。, as_duplicate=True 名称追加「（副本）」；不查重不改名（契约 §1.2）。 (+18 more)

### Community 100 - "审批终态测试"
Cohesion: 0.14
Nodes (21): test_approval_double_resolution_reports_first_outcome(), wait_until(), _engine_resolved(), _operation(), asyncio, V0.3.9 L11：审批统一终态（契约归档正文 .archive/v0.3.9-dual-track-backup-2026-09-10/logic-…, 迟到点击拿到真实终态（timeout），不再是无信息的 not_found。, timeout 是服务端专属终态：客户端提交按 invalid_decision 拒绝。 (+13 more)

### Community 101 - "世界书与注入契约"
Cohesion: 0.08
Nodes (26): 世界书预算诊断分量口径, depth 注入 splice 语义, 数据宏契约 {{char}}/{{user}}, 存而不运行清单, runtime_trigger 确定性触发, SillyTavern v1.18.0 world-info.js 语义参照, token 近似计数算法, 两段式装配（基座 + 回合） (+18 more)

### Community 102 - "模型输出解析"
Cohesion: 0.09
Nodes (21): _is_placeholder_speech(), Path, ValueError, 公开共享解析入口：解析并应用委派纠偏标记。 供 OpenAI 兼容流与 Codex 对话适配器共用，覆盖空正文/截断 JSON…, 把模型输出解析为 CharacterTurn。 整体或结尾 JSON 对象 → 结构化（speech + delegation）； 解析失败或 speech…, 剥离疑似 JSON 输出残块。 仅当输出以 ``{`` 开头（模型明显在输出 JSON 但格式损坏），或台词 尾部含 speech/delegation…, 角色输出不可用（空输出/JSON 截断/占位标点）。 ``category`` 区分失败形态，供流式适配器决定是否对真实模型做有界重试： -…, 解析可选的 memory 字段（V039-S4-003）。 只做协议一致性检查，不猜语义：字段是否存在由调用点判定，缺省即本轮… (+13 more)

### Community 103 - "全局引擎状态"
Cohesion: 0.14
Nodes (13): ActiveTurn, BusyTurnError, GlobalEngineState, InvalidTaskTransition, RuntimeError, V0.3.2 M4：并发单位是 conversation。 - 不同聊天的任务同时 active，互不阻塞（同一账号内）； -…, V0.3.2 M4：当前全部活动任务（快照/事件用）。, TaskLifecycle (+5 more)

### Community 104 - "控制租约测试"
Cohesion: 0.16
Nodes (25): _cancel_sweeper(), claim(), claim_command(), ping(), ping_command(), asyncio, DesktopCommand, fixture (+17 more)

### Community 105 - "角色音色页面"
Cohesion: 0.14
Nodes (21): CharacterCardSource, CharacterCardState, CharacterVoiceState, CharacterCardVoicePageViewModel, CardDetail, CharacterVoiceSection(), CharacterVoiceSectionProps, ConfirmAction (+13 more)

### Community 106 - "V0.2.0 旧版设计文档"
Cohesion: 0.14
Nodes (25): M0 基线记录, 14 项实际使用问题基线, 协议字段冻结（供 M4 视觉 AI）, v0.2.0 时代文档索引, V0.2.0 视觉线最终交付文档, 待强逻辑 AI 接线的接口点, 视觉与交互设计方案 v1, 与强逻辑 AI 的接口清单 (+17 more)

### Community 107 - "助手装配断言测试"
Cohesion: 0.14
Nodes (24): assert_single_assistant_markdown(), AssistantInstructionError, ValueError, 助手提示词装配断言失败：重复注入或混入非助手内容。, V0.3.3 装配断言：助手上下文恰好注入一个助手 Markdown。 正常上下文与未来（V0.3.9）压缩后重建的上下文都必须满足： 注入文本与…, command(), DesktopCommand, V0.3.3 批 3 接线测试：card.* / remote.* 命令与助手提示词装配断言。 (+16 more)

### Community 108 - "千问音频实网测试"
Cohesion: 0.11
Nodes (22): chunked_audio(), collect(), _collect_tts(), live_qwen_env(), live_voice_id(), asyncio, fixture, Path (+14 more)

### Community 109 - "V0.3.8 会话幂等测试"
Cohesion: 0.17
Nodes (24): command(), _bound_conversation(), _conversation_count(), asyncio, V0.3.8 T6：会话创建幂等与 mode 漂移修复的回归测试（真机验收 C6）。 覆盖（docs/plans/V0.3.8-修复实施计划.md §2…, 无角色卡的普通会话不参与复用（契约 §14.2）：始终新建。, chat.submit 缺省 mode 不改写会话 last_mode（“委派”标签漂移根因）。, 显式携带 mode 的提交仍按请求持久化会话模式。 (+16 more)

### Community 110 - "移动端语音采集"
Cohesion: 0.10
Nodes (10): MobileVoiceAvailability, ActiveVoiceInputMode, buildDisabledReason(), useVoiceCapture(), VoiceCaptureStatus, VoiceInputMode, createVoiceCaptureEngine(), dbToLinear() (+2 more)

### Community 111 - "表单控件工具"
Cohesion: 0.19
Nodes (17): NumberField(), NumberFieldProps, clone(), deepFreeze(), entryOf(), makeHarness(), RICH_BOOK, renderRichHarness() (+9 more)

### Community 112 - "角色卡数据契约文档"
Cohesion: 0.18
Nodes (23): 酒馆字段与 HSR 扩展字段映射表, 固定模型与导入卡边界, mufy 模板板块归置规则, 角色卡数据契约（hsr schema 1.0）, hsr.avatar_asset 头像资产, 不执行导入内容原则, 不做语义猜测原则, character_book 世界书模型 (+15 more)

### Community 113 - "架构决策文档节点"
Cohesion: 0.14
Nodes (23): 数据库结构版本 6, 局域网直连默认关闭, 配对码与设备令牌是真正防线, assert_single_assistant_markdown 装配断言, 角色卡持久化交付（迁移 9 + CharacterCardRepository）, V0.3.3 强逻辑轨道 A/B/C/D 交付分工, V0.3.3 真机与真实网络验收（2026-08-22）, 手机委派经真实 Reasonix 引擎执行链路 (+15 more)

### Community 114 - "音色创建 CLI"
Cohesion: 0.17
Nodes (22): _api_key(), build_parser(), _client(), cmd_adopt(), cmd_clone(), cmd_design(), concat_wavs(), data_uri_for() (+14 more)

### Community 115 - "音色绑定与参考音"
Cohesion: 0.09
Nodes (16): ``data.extensions.hsr.voice_profile``：角色与音色的绑定数据。 永远不保存明文 API Key；Key…, VoiceProfile, assistant_speaker_ids(), load_reference_voice_manifest(), Path, RuntimeError, 运行时从配对目录推导全部助手侧说话方 id 集合（V0.3.3）。 助手永不使用 TTS。provision / preview 对助手侧说话方的拒绝判定以…, manifest 缺失、结构不符或本地素材文件缺失。 (+8 more)

### Community 116 - "语音播放队列"
Cohesion: 0.11
Nodes (10): 待朗读语音队列（V0.3.9 契约 §6：单调 epoch）。 playing 表示正在播放；播放期间暂停 VAD，停止或播完后恢复。…, 队首待播条目的 message_id（无待播项时 None）。, 中断：epoch 递增、清空队列、复位 playing，返回新 epoch。, 跳过当前句：epoch 递增，待播项改挂新 epoch（不清空队列）。, 停止播放并清空队列，VAD 随之恢复（等价于一次中断）。, SpeechQueue, _request(), test_playback_state_pauses_and_resumes_vad() (+2 more)

### Community 117 - "控制租约"
Cohesion: 0.10
Nodes (10): _ControlLease, 回收已过期租约并广播 remote.control_changed，返回回收条数。, 确保存在周期回收任务（最晚 60s 回收过期租约并广播事件）。, 广播 remote.control_changed（契约 §6）。, 契约 §5.3：连接断开时取消该连接全部未完成语音会话（静默）。 V0.3.9 契约 §6：断连不立即释放控制租约——给持有者 15s 重连宽限，…, 手机端声明/续租远程控制权（V0.3.9 契约 §6）。 按 device_key 独立记录：重复认领只续租不发事件；首次认领抢占桌面 本地朗读（epoch…, 手机端释放自己的控制租约（恢复桌面播放资格）。 V0.3.9 契约 §6：只回收该 device_key，不误释放其他设备。, 一条远程控制租约（V0.3.9 契约 §6，按 device_key 独立记录）。 TTL 45s 由持有者的 ping/claim 刷新；断连后额外宽限… (+2 more)

### Community 118 - "配对与鉴权服务"
Cohesion: 0.15
Nodes (7): PairingService, 返回所有审计条目。 条目格式：{"at": iso时间, "event": "connect|auth_failed|command", "detail":…, 配对与鉴权服务。 实现 RemoteAuthenticator Protocol，供 WSServerMode 鉴权门调用。 纯逻辑：不碰网络、SQLite…, remote.pair 无 token 应放行，device_name 为空。, remote.pair 带有效 token 应放行并记录设备名。, TestAuthorize, TestRevoke

### Community 119 - "并发入口测试"
Cohesion: 0.15
Nodes (19): AwaitingDialogueModel, _chat_round_indices(), _make_orchestrator(), PausingEngine, asyncio, Event, O2.5：编排器入口并发防护测试。 同一会话的入口按 asyncio.Lock 串行化：聊天轮（用户消息+角色台词）…, M4：切换聊天时，执行中的任务继续使用发起聊天的上下文。 (+11 more)

### Community 120 - "Tauri 边车启动与日志"
Cohesion: 0.17
Nodes (21): AppHandle, ChildStderr, configured_env_file(), drain_sidecar_stderr(), launch_sidecar(), log_rotates_into_numbered_backups_when_over_the_limit(), open_session_log(), open_sidecar_log() (+13 more)

### Community 121 - "桌面端依赖清单"
Cohesion: 0.09
Nodes (21): jsdom, react, react-dom, @tanstack/react-virtual, @tauri-apps/api, @testing-library/jest-dom, @testing-library/react, @types/react (+13 more)

### Community 122 - "官网文案规范"
Cohesion: 0.16
Nodes (22): 官网文案规则, AI 广告的带货能力, AI 擅长做加法，人懂得做减法, AI 建站工具默认占位文案, AI 味, arXiv AI 广告说服策略实验, arXiv 大模型创意同质化研究, 标题与正文的语义重复率 (+14 more)

### Community 123 - "Codex 事件编解码"
Cohesion: 0.17
Nodes (17): CodexCodec, EventBinding, Any, Map native app-server notifications to stable Pair Harness events.…, 校验原生审批请求的 approval_id 必须是数字。 M1.5：缺失或非数字 id 在 codec 阶段就变成可见协议失败，而不是等到…, binding(), M6.1：原生 turn/completed status=cancelled 映射为取消回执，不能 failed。, M1.5：缺失/非数字 approval_id 在 codec 阶段即协议失败。 (+9 more)

### Community 124 - "Codex app-server 引擎"
Cohesion: 0.12
Nodes (12): CodexAppServerEngine, Any, V0.3.8 T4（契约 §14.6）：回合无进展结构化告警。 app-server 静默重试（模型供给误配、网络停摆）期间客户端此前零感知；…, O3.1：回复 app-server 挂起的审批请求（requestApproval）。 ``approval_id`` 是服务端请求的 JSON-RPC…, 设置 GPT-5.6 Sol 的真实 reasoning effort。, 打开（或恢复）app-server 线程。…, parametrize, configure_reasoning 的真实归一化：auto → medium（F5 档位语义）。 (+4 more)

### Community 125 - "数据宏展开"
Cohesion: 0.14
Nodes (19): expand_data_macros(), find_macros(), MacroExpansionResult, 数据宏展开纯模块（V0.3.7 契约 §5）。 白名单宏 ``{{char}}`` / ``{{user}}`` 在装配渲染时单遍展开；白名单之外的 宏…, 数据宏展开结果。 - ``text``：展开后的文本； - ``unexpanded``：出现过但未展开的宏 token（含花括号原文，去重保序）。, 单遍展开数据宏 ``{{char}}`` / ``{{user}}``。 白名单之外（含大小写变体、首尾空白形式与未知宏）一律原样保留并 记录到…, 返回文本中的全部 ``{{...}}`` token（含花括号原文，去重保序）。 供 codec 导入扫描复用（契约 §5.3：非白名单宏写入兼容报告）。, 数据宏展开纯模块测试（V0.3.7 契约 §5、§12）。 (+11 more)

### Community 126 - "会话仓储"
Cohesion: 0.10
Nodes (12): Conversation, ConversationSnapshot, _dt(), _parse_content_field(), datetime, 按 (created_at, message_id) 稳定顺序读取一页消息（升序返回）。 before_message_id 给定时返回它之前的 limit…, 摘要 content 文本解析回对象；空串/非对象返回 None（不伪造结构）。, 列出项目下的会话；``account_id`` 给定时按账号过滤。 账号是完整隔离边界：即使会话挂到了不属于当前账号的项目， 带账号过滤的列表也不会泄露。 (+4 more)

### Community 127 - "增量 JSON 解析测试"
Cohesion: 0.16
Nodes (20): json_delta_chunks(), make_request(), asyncio, MockTransport, V0.2 M2：增量 JSON 解析器与对话流式事件序列（问题 10）。 - speech.delta 只含干净台词（不再闪烁 JSON 键名/引号）； -…, 裸裁决 JSON（无 speech 字段）：不上屏增量，完整输出留待 review 复用。, JSON 流：speech.delta 只含干净台词；speech.completed 携带完整 raw。, reasoning_content 走独立通道：started → delta → completed。 (+12 more)

### Community 128 - "子进程启动与终止"
Cohesion: 0.11
Nodes (11): Process, main(), call(), request(), 最近 stderr 行拼接（idle 超时等场景携带底层原因，不吞原文）。, 返回子进程退出码和最近的 stderr，避免只暴露泛化 EOF。, 强制结束整个子进程树。 Windows 上 .cmd/.bat shim 只作为 cmd.exe 启动的包装，直接 kill 可能 只结束 cmd 而留下真实…, 把裸命令名解析为可启动的可执行文件路径。 B1 联调发现：npm 全局安装的 codex-cli 在 Windows 上是 ``codex.cmd`` 批处理… (+3 more)

### Community 129 - "提示词装配诊断"
Cohesion: 0.10
Nodes (15): _assembly_empty_label(), _core_memory(), _diagnostics_label(), _json_load(), PairMemory, 诊断值转单行显示文本（列表/对象逐项展开；只做展示包装不改写含义）。, 装配诊断为空的真实原因（V039-S4-011：区分未绑定与空装配）。, storage 层 PairMemory（扁平分量）→ core 装配用 ``PairMemory``。 作用域五分量与 core 同构（契约… (+7 more)

### Community 130 - "V0.3.9 指标与诊断测试"
Cohesion: 0.15
Nodes (19): Any, command(), DesktopCommand, Path, V0.3.9 P05/P06：metrics.query 与 diagnostics.prompt_assembly 命令链路。 契约出处：归档正文…, metrics.query 走存储层过滤；未观测字段为 null，真实零值用 0。, status 过滤生效；白名单外命令（如 memory.create）被拒绝。, prompt_assembly 返回模块名/字符范围/hash/summary/memory 注入； 默认不含… (+11 more)

### Community 131 - "移动端语音输入测试"
Cohesion: 0.16
Nodes (12): CONVERSATION, emitEvent(), FakeStreamTrack, FakeWebSocket, FakeWorkletNode, findSentFrame(), lastInstance(), respond() (+4 more)

### Community 132 - "音色 CLI 测试"
Cohesion: 0.12
Nodes (13): extract_voice_id(), 从成功响应提取 ``output.voice_id``；缺失即真实失败，不得合成。, _make_wav(), Path, create_qwen_voice.py 纯函数测试（不触网）。, test_concat_wavs_inserts_silence_and_preserves_params(), test_concat_wavs_mismatched_params_raises(), test_data_uri_rejects_unknown_audio_extension() (+5 more)

### Community 133 - "src: WsAddressInput.tes…"
Cohesion: 0.17
Nodes (15): validateWsAddress(), WsAddressInput(), WsAddressInputProps, WsAddressValidation, useShellEnvironment(), getStoredDeviceName(), BarcodeDetectorConstructor, BarcodeDetectorInstance (+7 more)

### Community 134 - "src: appendTtsChunk()"
Cohesion: 0.18
Nodes (10): appendTtsChunk(), selectMobileActiveMemories(), CONVERSATION, emitTtsChunk(), FakeWebSocket, lastInstance(), lastSentFrame(), openConv() (+2 more)

### Community 135 - "tsconfig.json: tsconfig.json"
Cohesion: 0.11
Nodes (18): compilerOptions, baseUrl, isolatedModules, jsx, lib, module, moduleResolution, noEmit (+10 more)

### Community 136 - "tauri.conf.json: tauri.conf.json"
Cohesion: 0.11
Nodes (18): app, security, windows, build, beforeBuildCommand, beforeDevCommand, devUrl, frontendDist (+10 more)

### Community 137 - "tsconfig.app.json: tsconfig.app.json"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, allowSyntheticDefaultImports, esModuleInterop, forceConsistentCasingInFileNames, isolatedModules, jsx, lib (+10 more)

### Community 138 - "desktop_backend: DiagnosticCallback"
Cohesion: 0.15
Nodes (18): DiagnosticCallback, ProviderKind, Enum, str, build_coding_engine(), _provider_env(), 编程助手引擎工厂——V0.2 M3（方案 §M3-4/§M3-5）。 B-03（V0.3.9）：产品只支持 OpenAI Chat Completions…, TOML basic string 严格转义，防止引号/换行/反斜杠破坏配置。 (+10 more)

### Community 139 - "adapters: incremental_json.p…"
Cohesion: 0.13
Nodes (10): IncrementalJsonSpeechParser, Any, 增量 JSON 解析：从 DeepSeek 流式输出中提取干净的 speech 字段（V0.2 M2）。 角色适配器的流式输出是 JSON…, 扫描 speech 字符串值；只返回已确认属于值的字符。, 流式 JSON 输出中的增量 speech 提取器。, 喂入一段 content 分片，返回新增的干净 speech 文本。, parametrize, 非 JSON 输出（角色卡降级/纯台词）：整段增量作为台词。 (+2 more)

### Community 140 - "core: sandbox.py"
Cohesion: 0.19
Nodes (14): ProjectSandbox, Path, RuntimeError, 目录级沙箱：限制文件与命令操作在项目根目录之内。 设计偏差说明（O4.6）：本类只是“路径约束”，不是执行沙箱—— - 对 shell…, 校验并解析写操作目标路径。 规则： - 相对路径拼接到项目根目录； - 绝对路径保持原样； - 使用 :meth:`Path.resolve` 展开…, 校验命令执行工作目录。``None`` 返回项目根目录。, SandboxViolation, test_absolute_path_inside_root_is_allowed() (+6 more)

### Community 141 - "desktop_backend: _extract_frame_id(…"
Cohesion: 0.14
Nodes (10): _extract_frame_id(), Any, Request, 从已解析的帧里提取请求 id；解析失败或非对象时返回 None。, 管理一条远端 WS 连接：上行队列 + 扇出订阅 + 下行写任务。, 消费下行队列并把每个 envelope 编码成 WS 文本帧下发。, 同步入队（作为 dispatch reply_sink 与 fanout 订阅写回调共用）。, 同步退订并停写（幂等）：撤销联动时立即切断事件下发。 (+2 more)

### Community 142 - "test_sounddevice_io.py: test_sounddevice_i…"
Cohesion: 0.20
Nodes (18): _chunk(), AudioPlayer 长生命周期输出流测试（V0.2 M2-4）。 以假 sounddevice 模块驱动播放器，不触真实音频设备：验证输出流…, 输出流惰性创建：线程空闲时不建流，首块写入才创建。, 缓冲上限钳制生产节奏：慢消费下批量入队被阻塞，且不丢块。, stop 立即清空缓冲并关闭流（丢弃积压）；下次播放惰性重建新流。, shutdown 后写入为无操作：不抛错、不重启线程、不建流。, 空 PCM 块（final 标记）不写入缓冲。, ms 毫秒 @ 16 kHz 单声道 int16 的静音块。 (+10 more)

### Community 143 - "test_v039_s4_voice_tts.py: EventLog"
Cohesion: 0.12
Nodes (10): EventLog, Any, fixture, 事件订阅器（event_sink）：按事件名过滤 payload。, service(), _install_relay_prerequisites(), V0.3.9（S4）语音侧离线回归：V039-S4-012（适配器侧）/ V039-S4-018（中继侧）。 本文件全部离线：DashScope…, V039-S4-018 反向断言：真实供应商失败仍必须上报失败事件。 (+2 more)

### Community 144 - "test_v039_prompt_assembly_seams.py: test_v039_prompt_a…"
Cohesion: 0.16
Nodes (18): _bind_card_conversation(), _call(), _insert_completed_summary(), _publish_card(), Any, V0.3.9 提示词装配接缝：摘要与 active 记忆必须真正进入角色 system 提示词。 三个经审查确认的缺陷都落在…, 直接落库一条 completed 摘要（覆盖区间取会话内真实消息）。, 按会话权威作用域直接落库一条 active 记忆（content 为 JSON 文本）。 (+10 more)

### Community 145 - "test_v039_turn_metric_seams.py: test_v039_turn_met…"
Cohesion: 0.21
Nodes (16): command(), _completed_metric(), _metric_for(), asyncio, DesktopCommand, Path, V0.3.9 回合指标接缝：来源身份、失败回执与首事件时间。 三条缺陷： - 手机回合指标恒显示 desktop（origin/device…, 桌面入口提交仍是 desktop，且不带设备字段。 (+8 more)

### Community 146 - "test_deepseek_request_shape.py: AsyncClient"
Cohesion: 0.29
Nodes (15): AsyncClient, _capturing_transport(), handler(), make_request(), asyncio, MockTransport, B1：DeepSeek 请求体形态（离线，用 MockTransport 断言请求字段）。 验证 MVP 计划 §5 B1.1：识别…, 结构化角色回合按配置采样温度，不再固定为确定式采样。 (+7 more)

### Community 147 - "adapters: OutputStream"
Cohesion: 0.16
Nodes (7): OutputStream, AudioPlayer, 长生命周期输出流播放器（V0.2 M2-4：连续音频输出流）。 持有单一 sounddevice.OutputStream，惰性创建、设备异常/被 stop…, 立即停止播放：清空缓冲、丢弃在途块并关闭流（流下次重建）。, 把一块 PCM 写入缓冲；缓冲满时阻塞等待（防止 TTS 超速）。, 写流并按块时长近似节奏播放；设备异常时重建流，不中断线程。, 惰性创建输出流；创建失败返回 None（本块静默丢弃，下块重试）。

### Community 148 - "adapters: 距离下一次可起始还需等待的秒数（<=…"
Cohesion: 0.13
Nodes (10): 距离下一次可起始还需等待的秒数（<=0 表示现在即可起始）。, 占用一个起始时隙，返回本次尝试的序号（用于成功/失败归账）。, 记一次失败：下一次起始至少等一个（更长的）退避间隔。, 记一次完整成功（上游 complete 终态）并清除失败退避。 只有比最近一次失败更新的尝试才算数：更早尝试的迟到成功不清除较新 失败的退避。只出了部分…, 相邻两次上行合成起始的最小间隔（进程共享、线程安全）。 ``wait_s()`` 只读不占位，``mark_started()`` 在真正起始时占用时隙，…, _SynthesisPacer, 连续失败按 4/8/16s 增长（真实常量），未被“部分成功”提前压回 4s。, 复核确证1：旧尝试的迟到成功不得清掉较新失败的退避（按尝试时序归账）。 (+2 more)

### Community 149 - "test_v039_assembler_summary_memory.py: test_v039_assemble…"
Cohesion: 0.24
Nodes (16): _card(), _hsr_with_trigger(), _memory(), MemoryScope, PairMemory, V0.3.9 契约 §2：角色装配顺序中的聊天摘要与配对记忆模块。 契约出处：``.archive/v0.3.9-dual-track-…, 摘要与记忆只进角色 system 段；本模块不产出助手文本。, _scope() (+8 more)

### Community 150 - "src: ChatListPage.tsx"
Cohesion: 0.25
Nodes (11): ChatListPage(), formatDateTime(), ConversationBadgeRow(), ConversationBadgeRowProps, TERMINAL_LABELS, initialStoreState, BadgeStoreExtensions, ConversationBadges (+3 more)

### Community 151 - "adapters: AcpCodec"
Cohesion: 0.20
Nodes (9): AcpCodec, Any, ACP 通知 → EngineEvent 映射（reasonix v1.24 实测形状）。 reasonix 把消息/思考/工具/计划统一封装为…, message/thought chunk 的纯文本。, 从 usage 对象里取第一个存在的整数 token 值；无则返回 None（不估算）。, tool_call_update 的 content（结果文本）提取。 兼容 dict / 文本数组两种形状；失败型工具可能携带 stderr/error/…, 从 tool_call / request_permission 的 rawInput 提取门控字段。 映射到编排器 PendingOperation…, V0.3.3：失败工具回执附带命令摘要与 stderr/error 文本，诊断不再 只有退出码（真实 Reasonix 失败只给 "command… (+1 more)

### Community 152 - "desktop_backend: ._account_exists()"
Cohesion: 0.17
Nodes (5): AccountRecord 快照（不含密码派生结果与密钥）。, 注册并登录：新账号成为当前账号（账号级数据从此隔离）。, 退出当前账号：回到默认账号（登录页状态），数据不删除。, 免密切换（本地信任的多账号切换；登录仍走 _account_login）。, V0.2 M4：首次引导完成标记——引导只在注册后由前端显式触发， 登录/注册命令本身不自动置位。

### Community 153 - "storage: records.py"
Cohesion: 0.21
Nodes (14): MemoryStatus, MetricStatus, ProjectionKind, datetime, Enum, str, V0.3.9 存储层记录类型（contract-v1 第 1/2/4/5 节）。 本模块只定义持久化记录的结构与结构性校验，不含任何语义判断： -…, 摘要状态（契约第 2 节：idle|running|completed|failed）。 (+6 more)

### Community 154 - "test_accounts_store.py: test_accounts_stor…"
Cohesion: 0.13
Nodes (14): make_store(), Path, V0.2 M3：本地账号与账号级配置的存储层（方案 §M3）。, 模拟 v4 旧库：projects 无 account_id 列 → 升级后归入默认账号。, 旧库升级：自动创建默认账号，未设置密码（空密码可登录）。, F6：密码本地派生——存储值必须不是明文，且同密码不同账号不同散列。 ``get_account`` 刻意不暴露派生字段，这里直查库表验证存储值： 若…, test_account_config_and_secret_roundtrip(), test_change_password_requires_old_password() (+6 more)

### Community 155 - "test_acp_engine.py: engine_and_server(…"
Cohesion: 0.15
Nodes (8): engine_and_server(), FakeAcpServer, LegacyShapedServer, OutOfSandboxServer, fixture, ACP 服务端脚本（reasonix v1.24 实测形状：session/update 封装）。, 真实联调出现的兼容形状：snake_case 字段、dict 结果文本、rejected 状态。, 工具目标路径在项目目录之外——触发编排器 TOOL_STARTED 分支的沙箱 break。

### Community 156 - "test_pairing.py: _FakeClock"
Cohesion: 0.15
Nodes (5): _FakeClock, 刚好在 TTL 边界内（≤ TTL）应成功。, 可手动推进的假时钟，用于测试 TTL 过期。, 过期码在 issue_code 时被清理，claim 应报 invalid。, TestClaim

### Community 157 - "test_v035_codex_fixes.py: test_v035_codex_fi…"
Cohesion: 0.15
Nodes (10): asyncio, V0.3.5 Codex Review 修复的回归测试（P1×6、P2×2 中的可离线验证项）。 覆盖： - Codex P1 #1：remote-only…, Codex P1 #1：remote-only 事件必须消费序号，与 emit 交错仍单调不重复。, Codex P1 #5：复制卡必须真实复制受管理资产；删除原卡后副本头像仍在。, Codex P1 #7：卡引用头像但资产文件损坏时如实失败，不合成 avatar:null。, Codex P1 #9：TTS 供应商失败必须发 voice.mobile_tts_failed，手机端不能停在 buffering。, test_card_duplicate_copies_shared_assets(), test_card_get_avatar_asset_corruption_raises() (+2 more)

### Community 158 - "test_v038_t4_delegation_chain.py: _HangingTransport"
Cohesion: 0.15
Nodes (5): _HangingTransport, Any, next_notification 永久挂起的 fake transport（模拟 app-server 静默）。, _SilentAcpSubscription, _SilentAcpTransport

### Community 159 - "test_v039_summary_memory_commands.py: test_v039_summary_…"
Cohesion: 0.20
Nodes (15): command(), DesktopCommand, Path, V0.3.9 遗留闭环：P02 复用作用域与 summary/memory 四命令。 契约出处：归档正文 ``.archive/v0.3.9-dual-…, summary.regenerate 对不存在的摘要 ID 以真实错误失败（不伪造成功）。, memory.update/delete 真实持久化并广播（契约 §2：修改与删除必须生效）。, 构造不存在记忆的 update/delete 报 memory_not_found（越作用域真实报错）。, reuse_active 只复用在同项目+同卡+同搭档的活跃会话；跨搭档不复用。 直接验证 find_active_conversation 的… (+7 more)

### Community 160 - "AGENTS.md: AGENTS.md 仓库协作准则"
Cohesion: 0.18
Nodes (15): AGENTS.md 仓库协作准则, Android arm64 APK 打包与 versionCode 派生, Let It Go（充分信任大语言模型）, 首次运行状态重置为打包必需步骤, 主动推进（智能体行为约定）, 子代理委派, 严禁重复造轮子（Reasonix 复用准则）, HSR Partner Harness README (+7 more)

### Community 161 - "web-prototype: 角色快速创建页面"
Cohesion: 0.14
Nodes (15): 角色快速创建页面, 草稿每 30 秒自动保存, 角色卡实时预览, 快速创建与高级编辑模式切换不清空字段, 名称必填校验, 角色库页面, 归档与恢复状态, Bento 角色卡片网格与悬停操作 (+7 more)

### Community 162 - "手机远程语音说明.md: 删除语音赞助二维码与作者承担费用承诺"
Cohesion: 0.16
Nodes (15): 删除语音赞助二维码与作者承担费用承诺, 语音 BYOK（用户自填 DashScope Key）, 只有角色回复会朗读, Cloudflare Tunnel 公网 HTTPS 接入, 手机远程语音说明, 控制操作只在电脑本机生效, 不运营发布方服务器, 不内置自签证书方案 (+7 more)

### Community 163 - "test_pair_config.py: adopt_voice_id()"
Cohesion: 0.30
Nodes (14): adopt_voice_id(), PairConfigError, RuntimeError, 把 ``voice_id`` 写回 pair YAML 的 character/assistant 块，只改那一行。 保留文件其余内容与换行符原样（不经过…, test_adopt_voice_id_force_rebuilds_real_id(), test_adopt_voice_id_missing_section_raises(), test_adopt_voice_id_preserves_crlf(), test_adopt_voice_id_refuses_to_overwrite_real_id_without_force() (+6 more)

### Community 164 - "test_v038_t2_device_mutex.py: test_v038_t2_devic…"
Cohesion: 0.20
Nodes (12): asyncio, parametrize, V0.3.8 D2：桌面与手机播放设备互斥与控制权链路测试。 覆盖： 1. remote.claim_control 登记活跃控制器； 2.…, 手机端发起的 voice.mobile_tts_stop 联动停止桌面本地播放器。, remote.claim_control 和 release_control 正确切换控制器活跃状态。, test_device_mutex_claim_and_release(), test_mobile_tts_stop_also_stops_desktop_player(), test_remote_control_blocks_explicit_desktop_audio() (+4 more)

### Community 165 - "test_v038_t4_delegation_chain.py: _FakeCodexAuth"
Cohesion: 0.13
Nodes (13): _FakeCodexAuth, Path, DeepSeek 端点保持既有（真机已通过）的 Reasonix 配置形态不变。, 诊断回调从装配方透传到 ACP 引擎（契约 §14.6）。, build_coding_engine 只需要 base_dir/account_id 与 env_overrides。, 任意 http(s) 兼容端点（含不可解析域名）都装配 AcpCodingEngine。 B-03：不再有 Responses 校验，也不再有 Codex…, OpenAI 官方端点同样走 ACP 引擎（不存在 codex app-server 分支）。, 通用端点必须真的写入 Reasonix 配置，而不是删掉校验后仍走别的引擎。 依据（本机 reasonix 二进制内嵌文档 §3.1）：``kind =… (+5 more)

### Community 166 - "test_v039_r2_application_fixes.py: test_v039_r2_appli…"
Cohesion: 0.22
Nodes (13): command(), Any, DesktopCommand, Exception, MonkeyPatch, Path, V0.3.9 R2 复测批次：服务商探测失败原因不得为空。 V039-R2-001：``config.test_connection``…, 构造真实模式探测场景：账号配置指向本机不可达端点，HTTP 层如实失败。 (+5 more)

### Community 167 - "ui: helpers.tsx"
Cohesion: 0.33
Nodes (6): BLOCK_KEYS, clone(), deepFreeze(), makeHarness(), RICH_HSR, renderRichHarness()

### Community 168 - "tsconfig.node.json: tsconfig.node.json"
Cohesion: 0.14
Nodes (13): compilerOptions, allowImportingTsExtensions, lib, module, moduleDetection, moduleResolution, noEmit, skipLibCheck (+5 more)

### Community 169 - "v0.3.4-acceptance.md: 前节交谈、后节执行的双空间联动"
Cohesion: 0.14
Nodes (14): 前节交谈、后节执行的双空间联动, 独立聊天模式, 本地账号与配置中心, 账号切换原子清空账号级状态, CI 纳入手机端测试与生产构建, V0.3.4 验收记录, V0.3.4 验证命令门禁, conversation.open 请求代次 (+6 more)

### Community 170 - "adapters: sounddevice_io.py"
Cohesion: 0.15
Nodes (11): _input_device_candidates(), callback(), 返回默认输入及可尝试的真实麦克风设备，优先 Windows WDM-KS。, 把 RawInputStream 的 int16 帧降为目标采样率的单声道 PCM。, _resample_input(), F7/兼容：输入设备候选——默认设备居首、WDM-KS 麦克风优先。 覆盖 ``_input_device_candidates``（Windows…, 默认输入不可用时回退 None（只列候选），不抛错。, F7/兼容：int16 帧降混 + 重采样（``_resample_input`` 核心路径）。 (+3 more)

### Community 171 - "adapters: Predictable rolepl…"
Cohesion: 0.18
Nodes (11): Predictable roleplay adapter used by Plan A demos and tests., 确定性摘要：demo/测试用，不做语义判断、不改写消息原文。, ScriptedDialogueModel, _desktop_command(), asyncio, DesktopCommand, Path, O2.2：restore_conversation 回填消息历史与 EngineSessionRef。 恢复后再发消息：角色模型收到的近期上下文包含历史消息；… (+3 more)

### Community 172 - "desktop_backend: _atomic_write_text…"
Cohesion: 0.22
Nodes (13): _atomic_write_text(), ensure_reasonix_home(), _normalize_reasonix_effort(), Path, 同目录临时文件写入后原子替换（.env/config.toml 共用）。, 把角色模型配置的档位归一化为 Reasonix 支持的 effort 值。 Reasonix 的 provider ``effort`` 接受…, 为账号准备 reasonix 配置目录（``REASONIX_HOME/config.toml`` + ``.env``）。 reasonix…, Path (+5 more)

### Community 173 - "test_text_loop_live.py: test_text_loop_liv…"
Cohesion: 0.23
Nodes (13): live_env(), _live_orchestrator(), asyncio, CompletedProcess, fixture, Path, B1 真实联调：DeepSeek 对话 + codex app-server 全链路（live marker）。…, 固定三场景重复两轮：闲聊、委派、失败结果均遵守职责边界。 (+5 more)

### Community 174 - "test_application_service.py: __init__()"
Cohesion: 0.15
Nodes (5): __init__(), test_voice_commands_only_exchange_state_with_attached_runtime(), __init__(), stop_speaking(), stop_speaking_async()

### Community 175 - "src: BackendMode"
Cohesion: 0.46
Nodes (12): BackendMode, cli_mode_request(), detect_backend_mode(), env_content_flag(), env_content_mode_request(), env_file_mode_request(), env_flag(), env_mode_request() (+4 more)

### Community 176 - "web-prototype: 角色高级编辑器页面"
Cohesion: 0.17
Nodes (13): 角色高级编辑器页面, 编辑自动保存状态指示, 分区面包屑与常驻整体预览, 只读原始数据 JSON 视图, 高级编辑十七分区树, 结构化时间线事件编辑, 声明式面板（保留但不运行）, mufy 高级字段 (+5 more)

### Community 177 - "V0.3.3-V0.4.0-Plan.md: 纯 JSON/PNG 编解码模块"
Cohesion: 0.24
Nodes (13): 纯 JSON/PNG 编解码模块, 并行双 AI 计划（强逻辑 AI）, 开发计划索引, 双轨并行开发方式, V0.4.0 最终产品状态, V0.4.0 发布门槛, V0.3.3—V0.4.0 收敛路线图, V0.3.5 双轨实施计划 (+5 more)

### Community 178 - "v0.2.0-release-notes.md: 持久化会话队列 conversati…"
Cohesion: 0.15
Nodes (13): 持久化会话队列 conversation_inbox, v0.2.0 发布说明, 错误分级与连接恢复, GPT-5.6 Sol 编程助手, M0 基线 14 项问题, 消息真实回执, 语音合成失败保持 failed 态等待重播, 统一运行模型（一次提交 = 一个 Turn） (+5 more)

### Community 179 - "adapters: customization_endp…"
Cohesion: 0.24
Nodes (7): customization_endpoint(), CustomizationResult, QwenVoiceCustomizationClient, Qwen-Audio-TTS 音色 customization 客户端（同步 urllib，可注入传输）。, 创建成功的结果：真实响应中的 voice_id 与原始 payload。, fake_clone(), fake_design()

### Community 180 - "src: ApprovalCard.tsx"
Cohesion: 0.23
Nodes (10): ACTOR_LABELS, actorLabel(), ApprovalCard(), ApprovalCardProps, DECISION_LABELS, decisionLabel(), RESOLVED_BY_LABELS, resolvedByLabel() (+2 more)

### Community 181 - "package.json: devDependencies"
Cohesion: 0.17
Nodes (12): devDependencies, jsdom, @tauri-apps/cli, @testing-library/jest-dom, @testing-library/react, @types/qrcode, @types/react, @types/react-dom (+4 more)

### Community 182 - "adapters: DemoSpeechRecogniz…"
Cohesion: 0.23
Nodes (6): DemoSpeechRecognizer, AsrEvent, SpeechRecognizer, Protocol, 与 ``qwen_asr.QwenStreamingRecognizer`` 真实接口对齐的端口。…, RecognizerPort

### Community 183 - "adapters: qwen_voice_customi…"
Cohesion: 0.21
Nodes (10): build_clone_payload(), build_design_payload(), normalize_prefix(), Any, Qwen-Audio-TTS 音色 customization 客户端（V0.3.2 M6）。 供…, 固定声音设计 payload：与复刻同一 customization 契约，改传描述文本。, 校验并规范 prefix：只允许小写字母/数字，最长 10 字符。, 固定复刻 payload，支持服务端 URL 与本地音频 data URI。 (+2 more)

### Community 184 - "desktop_backend: pairing.py"
Cohesion: 0.17
Nodes (8): DeviceInfo, PairingError, RuntimeError, 配对码与 token 鉴权纯逻辑模块。 实现 RemoteAuthenticator Protocol，处理配对码生成/验证、token 签发/鉴权/撤销，…, 配对码操作错误。 code 取值： - "expired"：配对码已过期 - "used"：配对码已被使用 - "invalid"：配对码不存在或格式错误, 返回所有已签发 token 的设备元数据。 不含 token 明文。, 已签发 token 的设备元数据（不含 token 明文）。, TypedDict

### Community 186 - "test_application_service.py: 角色流不走 coding busy，…"
Cohesion: 0.14
Nodes (6): 角色流不走 coding busy，也必须阻止同一聊天并发生成两轮。, V0.2 M2：一次提交 = 一个 Turn——提交返回 turn_id，后台推进 turn.started(running) →…, V0.2 M2（问题 9）：忙碌时提交先入队返回 queue_item；回合完成后 自动派发队列项（成为真实用户消息），队列消费后清空。, test_busy_submit_enqueues_then_auto_dispatches_after_turn(), test_chat_submit_registers_turn_with_lifecycle_events(), test_role_turn_same_conversation_is_queued_while_streaming()

### Community 187 - "test_v039_s4_application_fixes.py: MonkeyPatch"
Cohesion: 0.17
Nodes (6): MonkeyPatch, V039-S4-018 收尾：begin 抛错必须走同一失败上报路径，不再无人观察地结束。, V039-S4-018：抢占/停止是正常控制流，不得广播 voice.mobile_tts_failed。, test_mobile_tts_begin_failure_is_reported_not_swallowed(), explode(), test_mobile_tts_preemption_is_not_reported_as_failure()

### Community 188 - "risk_rules.yaml: 高风险操作判定规则表"
Cohesion: 0.18
Nodes (11): 高风险操作判定规则表, high_risk_tool_kinds 文件工具高风险类型, patch_max_files 批量修改阈值, sensitive_paths 敏感路径匹配, shell.delete 删除类命令, shell.git_destructive git 破坏性命令, shell.network 网络访问命令, shell.package 依赖安装与环境变更 (+3 more)

### Community 189 - "package.json: scripts"
Cohesion: 0.18
Nodes (11): scripts, build, build:sidecar, dev, reset:first-run, tauri, tauri:build, tauri:dev (+3 more)

### Community 190 - "src: chat_window_title(…"
Cohesion: 0.22
Nodes (11): chat_window_title(), ChatWindowMeta, civil_from_days(), encode_query_component(), open_chat_window(), random_uuid_v4(), stream_id_value(), utc_timestamp() (+3 more)

### Community 191 - "web-prototype: V0.4.0 角色卡系统 UI 原型…"
Cohesion: 0.35
Nodes (11): V0.4.0 角色卡系统 UI 原型强视觉交付文档, 首轮审计 9 处缺口与修复, 原型与正式代码零耦合, DESIGN-HANDOFF 实现交接契约, 视觉保真契约（冲突时以导出像素与行为为准）, 数据字段与后端能力清单（交付物 12）, 原型为纯前端演示无真实逻辑, 固定语音模型只读契约（qwen-audio-3.0-asr / tts） (+3 more)

### Community 192 - "index.html: Tauri 2 + Python S…"
Cohesion: 0.24
Nodes (11): Tauri 2 + Python Sidecar + 编程执行后端三段架构, 多搭档动态主题令牌, 无 Key 演示模式, 流萤 × 萨姆, HSR Partner Harness 官网营销落地页, 三月七 × 第四面镜, 搭档目录与选择, 白厄 × 神秘的古代机械 (+3 more)

### Community 193 - "V0.3.5-契约冻结.md: 助手永久禁用 TTS"
Cohesion: 0.18
Nodes (11): 助手永久禁用 TTS, 角色负责对话、助手负责工具, 手机语音传输定案（JSON 文本帧 + base64）, 卡音色命令族 voice.card_*, 卡音色状态机 CharacterVoiceState, 手机音频传输契约（待定案）, C2 移动端朗读播放即黑屏, tts_ready 可朗读契约 (+3 more)

### Community 194 - "v0.3.5-visual-ai-acceptance.md: PTT 测试竞态修复（vad.ses…"
Cohesion: 0.20
Nodes (11): PTT 测试竞态修复（vad.sessions 单调计数）, 按住说话与实时转写, AppShell 未传 actions 致音色服务死链, 手机审批发非法决策值 approve, V0.3.5 交付分工（F0 / D1 / D2 / D3 / M）, 视觉证据界限：mock 状态不得作为真实链路证据, CharacterVoiceSection 测试事序竞态, PTT 启动必炸（startVoiceCapture 未返回结果） (+3 more)

### Community 195 - "repro_sidecar_process.py: repro_sidecar_proc…"
Cohesion: 0.22
Nodes (3): FrontendStore, main(), 进程级复现：启动真实 sidecar 进程，用真实 stdin/stdout JSONL 协议 驱动 bootstrap → register →…

### Community 196 - "desktop_backend: ._audit_log()"
Cohesion: 0.22
Nodes (5): 使用配对码换取 token。 Parameters ---------- code : str 配对码。 device_name : str 设备名称。…, 鉴权单条请求。 token 有效且未撤销 → allowed=True； method 在 ``UNAUTHENTICATED_METHODS`` 白名单内…, 恒定时间查找 token（hmac.compare_digest 比较）。, 撤销指定 token。 撤销后 ``authorize`` 立即拒绝，并通知所有撤销监听器（如 WS 服务器 断开该 token 的已建立连接）。…, _TokenEntry

### Community 197 - "test_sounddevice_io.py: FakeOutputStream"
Cohesion: 0.18
Nodes (6): FakeOutputStream, 记录写入块与关闭状态的假 OutputStream。, write(), close(), __init__(), write()

### Community 198 - "test_voice_runtime.py: DrainPlayer"
Cohesion: 0.18
Nodes (4): DrainPlayer, FakeOrchestrator, Event, 等待真实输出设备排空后再允许播放状态收尾。

### Community 199 - "PHILOSOPHY.md: Let It Fail（真实失败必须…"
Cohesion: 0.29
Nodes (10): Let It Fail（真实失败必须暴露）, HSR Partner Harness 设计哲学, 裁决而非复述（Verdict, Not Paraphrase）, 关系系统的持久化（关系阶段门控）, 三个时间尺度写同一本书, 随身搭档（PC 是唯一大脑）, 在场节拍（In-turn Beats）, 证据白盒可查 (+2 more)

### Community 200 - "README.md: 古代机器音色提示词"
Cohesion: 0.22
Nodes (10): 古代机器音色提示词, 音色自然语言描述要素, 设计与调研索引, ACP 助手引擎选型依据, 千问语音 API 参考（阿里云百炼）, 角色卡数据契约, 千问声音复刻 creation_mode: clone, 千问声音设计 creation_mode: design (+2 more)

### Community 201 - "v0.3.2-release-notes.md: v0.3.2-patch1 为当前产…"
Cohesion: 0.24
Nodes (10): v0.3.2-patch1 为当前产品基线, 发布说明索引, 跨聊天并发测试竞态修复, v0.3.2-patch1 发布说明, rustfmt 格式导致的 CI 失败修复, v0.3.2 发布说明, 固定语音模型（qwen-audio-3.0-asr/tts-flash）, 参考音频 data URI 提交方式 (+2 more)

### Community 202 - "adapters: PostJson"
Cohesion: 0.24
Nodes (8): PostJson, audio_file_to_data_uri(), Path, RuntimeError, 把本地 WAV/MP3/M4A 转为已实测可用的 ``input.url`` data URI。, customization 请求失败；保留真实 HTTP 状态与 DashScope 错误信息。, VoiceCustomizationError, test_clone_payload_accepts_remote_and_local_data_uri()

### Community 203 - "repro_onboarding_flow.py: FrontendStore"
Cohesion: 0.22
Nodes (5): command(), FrontendStore, main(), DesktopCommand, 复刻 desktop/src/stores/desktopStore.ts 的序号与账号状态逻辑。

### Community 204 - "smoke_serve_mode.py: smoke_serve_mode.p…"
Cohesion: 0.27
Nodes (6): free_port(), main(), send_stdin(), ws_phase(), V0.3.3 批 4 真实进程冒烟：--serve 模式下真实 Sidecar 进程全链路。 验证点（对照 workplan 第 7 节与计划文档…, _safe_json()

### Community 205 - "verify_qwen_reference_v035.py: verify_qwen_refere…"
Cohesion: 0.33
Nodes (9): clone_payload(), data_uri_of(), design_payload(), _load_dotenv(), main(), post(), Path, V0.3.5 参考音频能力增补真实验证（强逻辑 AI L9）。 补齐《千问参考音频能力验证记录》2026-08-16 未实测项： P1. MP3 本地文件转… (+1 more)

### Community 206 - "adapters: AbstractEventLoop"
Cohesion: 0.33
Nodes (9): AbstractEventLoop, Event, Queue, on_complete(), on_data(), on_error(), _put(), executor 线程：提交文本 → 发 finish request → 等 FINISHED → 收尾。 真实服务在收到 finish… (+1 more)

### Community 207 - "test_codex_transport_robustness.py: test_codex_transpo…"
Cohesion: 0.33
Nodes (8): make_transport(), asyncio, O1.3：读循环遇到坏 JSON 行只跳过，后续正常响应仍被解析。, O1.3：服务端不响应时请求超时，抛出可识别异常。, O1.3：构造级 request_timeout 作为默认超时生效。, test_bad_json_line_is_skipped_and_loop_continues(), test_constructor_request_timeout_applies_by_default(), test_request_timeout_raises_recognizable_error()

### Community 208 - "test_v035_wiring.py: install_fake_qwen_…"
Cohesion: 0.24
Nodes (9): install_fake_qwen_client(), create_cloned_voice(), create_designed_voice(), _respond(), Event, Exception, MonkeyPatch, 替换 DashScope 音色定制客户端（供应商 HTTP 边界），记录全部调用参数。 (+1 more)

### Community 209 - "dashscope: 本地模型目录说明"
Cohesion: 0.28
Nodes (9): 本地模型目录说明, Silero VAD v5 本地模型, 千问实时语音识别（Qwen-ASR Realtime）, 客户端重连与心跳容错, 连接池/对象池高并发与预热, 语音情感识别, 热词与上下文增强, VAD 断句与交互模式（turn_detection） (+1 more)

### Community 210 - "千问参考音频能力验证记录.md: 千问参考音频能力验证记录"
Cohesion: 0.25
Nodes (9): 千问参考音频能力验证记录, 本地音频转 Base64 data URI 提交, 音频 10MB 与 60 秒边界（Audio.FileSizeExceed）, 参考音频公网可达性（GitHub raw 失败 / jsDelivr 可用）, 音色复刻固定契约（voice-enrollment / create_voice）, 声音设计（voice_prompt + preview_text ≥15 字符）, 角色卡文档索引, V0.3.7 SillyTavern 双向交换联调记录 (+1 more)

### Community 211 - "V0.4.0关键产品级决策.md: 手机远程架构八原则"
Cohesion: 0.25
Nodes (9): 手机远程架构八原则, 手机远程主线, D1 Cloudflare Tunnel 公网接入, D2 监听面默认收窄到回环, D3 配对码失败限流, D5 设备令牌生命周期, D6 控制面只限回环, D7 隧道 URL 不是秘密 (+1 more)

### Community 212 - "V0.3.9-续作计划.md: V0.3.9 验收记录"
Cohesion: 0.31
Nodes (9): V0.3.9 验收记录, V0.3.9 续作计划（单轨）, 真机验收前停止边界, V0.3.9 真机验证需求, V0.3.9 S4 真机验证执行要求, 问题记录强制格式与固定句, V0.3.9 问题与修复台账, INFO 全量日志落盘要求 (+1 more)

### Community 213 - "test_application_service.py: V0.2 M2-4：voice.tt…"
Cohesion: 0.25
Nodes (4): V0.2 M2-4：voice.tts_play 按 message_id 重播、tts_skip 跳过、preview 试听入队。, test_voice_tts_play_skip_and_preview_commands(), skip_playing(), skip_playing_async()

### Community 214 - "test_pairing.py: test_pairing.py"
Cohesion: 0.22
Nodes (4): 配对与鉴权纯逻辑模块测试。 覆盖 workplan 4.3 全部场景：配对码一次性、过期、错误码、 token 撤销后立即拒绝、list_devices…, 连续签发多个码不应重复（概率极低，运行多次验证）。, TestIntegration, TestIssueCode

### Community 215 - "test_pairing.py: export_state 不含 AP…"
Cohesion: 0.22
Nodes (4): export_state 不含 API Key 相关字段。, export → load → authorize 行为一致。, export_state 可 JSON 序列化。, TestStateRoundtrip

### Community 216 - "test_v032_m6_voice.py: test_v032_m6_voice…"
Cohesion: 0.25
Nodes (7): V0.3.2 M6 语音契约测试。 这些测试只覆盖本地 manifest、请求 payload、响应解析和错误映射；不访问…, test_customization_client_redacts_key_in_dashscope_error(), test_customization_client_sends_auth_and_returns_server_voice_id(), transport(), test_design_payload_uses_same_fixed_enrollment_contract(), test_extract_voice_id_does_not_invent_missing_result(), test_fixed_voice_models_and_manifest_order()

### Community 217 - "package.json: dependencies"
Cohesion: 0.25
Nodes (8): dependencies, qrcode, react, react-dom, @tanstack/react-virtual, @tauri-apps/api, @tauri-apps/plugin-dialog, zustand

### Community 218 - "web-prototype: 头像设置三步弹层页面"
Cohesion: 0.29
Nodes (8): 头像设置三步弹层页面, 头像占位策略（首字符 / 几何色块）, 头像三步弹层（选择 / 裁切 / 确认）, screen-file-first 路由契约, 原型总览入口页 index.html, 页面状态覆盖矩阵（交付物 11）, 十页原型页面清单, 零角色空库与筛选无结果两态拆分

### Community 219 - "web-prototype: 角色导入流程页面"
Cohesion: 0.32
Nodes (8): 角色导入流程页面, 导入五态流转演示, 禁止保留设计过程标注与 Open Design chrome, 失败错误摘要透传不用默认角色掩盖, 扩展识别分级（随导入启用 / 已保留但暂未运行）, 导入解析在本地完成文件不上传, 名称冲突副本导入策略, 样例数据虚线标识系统

### Community 220 - "web-prototype: 参考音频公网 URL 要求"
Cohesion: 0.25
Nodes (8): 参考音频公网 URL 要求, 参考音频要求（WAV/MP3 · 10–60 秒 · 单一人声）, 语音五态状态机, 角色语音创建页面, 语音页角色选择器（四角色四状态）, 参考音频选择与试听, 音色状态机演示区, 重新创建与解除绑定确认

### Community 221 - "V0.3.5-契约冻结.md: 审批仲裁与命令来源 origin"
Cohesion: 0.25
Nodes (8): 审批仲裁与命令来源 origin, CharacterAssetService 头像资产服务, V0.3.5 契约冻结, 对话绑定角色卡（迁移 v10）, 角色提示词装配器, V0.3.5 六大缺口盘点, resolver 静默丢失缺陷, PNG 命令族 card.import_png / card.export_png

### Community 222 - "verify_qwen_reference_audio.py: verify_qwen_refere…"
Cohesion: 0.43
Nodes (7): clone_payload(), head_status(), _load_dotenv(), main(), post(), 固定千问 TTS 模型参考音频能力真实验证脚本（V0.4.0 逻辑底座，一次性诊断）。 只做真实请求并原样打印响应，不写回任何配置、不生成 mock 结果。…, _redact()

### Community 223 - "adapters: .close()"
Cohesion: 0.25
Nodes (3): MicrophoneCapture, 停止播放线程并关闭输出流（shutdown 时调用）。, 采集 16 kHz 单声道 int16 PCM 的麦克风流。 Windows 的 MME 默认输入设备经常拒绝 16 kHz 或阻塞式输入；这里优先…

### Community 224 - "core: available_input_me…"
Cohesion: 0.36
Nodes (7): available_input_methods(), InputMethod, Enum, str, 输入矩阵：对角色说话提供 VAD；直接交给助手不提供 VAD。 聊天模式与协作模式的"对角色说"一致，都包含 VAD、按键说话和文字；…, test_assistant_target_omits_vad(), test_character_target_provides_vad_ptt_text()

### Community 226 - "tauri.android.conf.json: tauri.android.conf…"
Cohesion: 0.29
Nodes (6): build, frontendDist, bundle, resources, identifier, $schema

### Community 227 - "web-prototype: 角色导出流程页面"
Cohesion: 0.29
Nodes (7): 角色导出流程页面, 导出前检查清单, 等待 V0.3.2 完成后接入清单, 导出格式 v3 JSON 与 v3 PNG, 导入导出能力契约, 12 条待后端确认的开放问题, 世界书条目字段契约

### Community 228 - "web-prototype: 助手永远不使用 TTS"
Cohesion: 0.33
Nodes (7): 助手永远不使用 TTS, 新用户十三步引导页面, 助手选择（助手无 TTS 不适用音色）, DashScope 账号配置步骤, 角色 × 助手配对, 十三步引导主路径, 角色卡到配对对话的入口表达

### Community 229 - "并行双AI计划_强视觉AI.md: 角色卡数据契约与字段映射表"
Cohesion: 0.29
Nodes (7): 角色卡数据契约与字段映射表, mock 状态与真实完成状态区分, 并行双 AI 计划（强视觉 AI）, 强视觉 AI 页面范围, HSR 扩展字段 extensions.hsr, 角色卡主线, 酒馆 Character Card v3 标准字段

### Community 230 - "desktop_backend: _CodeEntry"
Cohesion: 0.29
Nodes (3): _CodeEntry, 生成一个 6 位数字配对码（000000–999999 均匀分布）。 一次性，TTL 默认 300 秒。, 从状态快照恢复。 替换当前全部状态。恢复后 ``authorize`` 行为与导出前一致。

### Community 231 - "storage: 打开数据库并完成迁移。 clock …"
Cohesion: 0.29
Nodes (4): Path, 打开数据库并完成迁移。 clock 只用于批量刷盘的 50ms 判定（默认 time.monotonic）； 注入固定时钟后测试可以确定性地断言刷新时机。, 旧库版本化迁移：按 ``PRAGMA user_version`` 逐级升级。 schema.sql 用 CREATE TABLE IF NOT…, 执行单条迁移语句；ALTER TABLE ADD/DROP COLUMN 按现状跳过。

### Community 232 - "character_cards: _generate_png_fixt…"
Cohesion: 0.38
Nodes (6): _chunk(), main(), make_avatar_png(), 生成角色卡 PNG 二进制 fixture（白厄（3.4前）.png）。 用途：契约 §12 规定 PNG fixture 由「白厄 JSON +…, 构造单个 PNG 块（长度 + 类型 + 数据 + CRC）。, 合成最小但真实可解码的 PNG 头像（64x64、RGB、8-bit）。

### Community 235 - "capabilities: default.json"
Cohesion: 0.33
Nodes (5): description, identifier, permissions, $schema, windows

### Community 236 - "强视觉AI-角色卡样例数据与状态枚举.md: 失败保持失败（CardImportE…"
Cohesion: 0.60
Nodes (6): 失败保持失败（CardImportError / PngCardError）, 强视觉 AI 角色卡状态枚举与样例数据, CharacterCardState 状态枚举, CharacterVoiceState 状态枚举, 角色库样例.json（hsr.character_library_sample/1.0）, 两组状态正交约定

### Community 237 - "web-prototype: 设计 token 前置抽取契约"
Cohesion: 0.33
Nodes (6): 设计 token 前置抽取契约, 琥珀橙强调色 token, 暗色优先双主题 OKLch token 系统, 线性 SVG 图标系统（统一不用 emoji）, 严禁蓝紫配色硬性约束, 警告状态图标加文字双编码

### Community 238 - "repro_v037_visual_contracts.py: repro_v037_visual_…"
Cohesion: 0.40
Nodes (3): check(), main(), V0.3.7 视觉轨集成探针：真实 Sidecar 上验证冻结 §1/§10 四个新命令的真实 payload 与视觉轨 TS…

### Community 239 - "test_desktop_sidecar_loop.py: StreamReader"
Cohesion: 0.47
Nodes (5): StreamReader, asyncio, Path, _read_json_line(), test_demo_sidecar_survives_bad_json_and_processes_valid_requests()

### Community 241 - "test_codex_transport.py: EofConnection"
Cohesion: 0.33
Nodes (3): EofConnection, 立即 EOF 的连接，用于制造旧 reader 的失败并结束旧代次。, factory()

### Community 246 - "test_pairing.py: 验证配对模块使用 hmac.comp…"
Cohesion: 0.33
Nodes (3): 验证配对模块使用 hmac.compare_digest 而非 == 比较 token。, 验证整个模块使用 secrets 而非 random。, TestSecurity

### Community 249 - "repro_full_flow.py: repro_full_flow.py"
Cohesion: 0.40
Nodes (3): main(), cmd(), 完整端到端复现：真实后端 + DeepSeek 引擎。 用户消息 → 角色回复（含委派）→ 古代机器（reasonix acp）执行 → 角色汇报结果。…

### Community 251 - "core: .normalize_unicode…"
Cohesion: 0.60
Nodes (4): _normalize_unicode(), Any, field_validator, 把字符串中的孤立 UTF-16 代理字符替换为 Unicode replacement character。

### Community 254 - "test_v035_wiring.py: DesktopCommand"
Cohesion: 0.40
Nodes (3): DesktopCommand, V0.3.9 §5：手机语音转写提交保留传输层注入的来源与设备。, test_mobile_ptt_stop_carries_remote_origin_to_chat_submit()

### Community 255 - "test_v038_t4_delegation_chain.py: _binding()"
Cohesion: 0.40
Nodes (5): _binding(), 未识别 method 首次结构化 WARNING（协议漂移痕迹），同 method 不刷屏。, native_turn_id 不匹配是正常过滤（别的回合的事件），不产生告警。, test_codec_mismatched_turn_id_stays_silent(), test_codec_warns_once_per_unknown_method()

### Community 256 - "test_v039_s4_voice_tts.py: V039-S4-018：抢占旧合成不…"
Cohesion: 0.40
Nodes (3): V039-S4-018：抢占旧合成不得产生 voice.mobile_tts_failed。 复刻现场时序：旧中继挂在…, test_preempted_relay_is_not_reported_as_failure(), synthesize()

### Community 257 - "index.html: 搭档手机端 HTML 入口"
Cohesion: 0.50
Nodes (4): 搭档手机端 HTML 入口, interactive-widget=resizes-content 软键盘适配, 保留用户缩放能力, viewport-fit=cover 安全区适配

### Community 259 - "V0.3.7-验收记录.md: V0.3.7 验收记录（§6.1 矩…"
Cohesion: 0.50
Nodes (4): V0.3.7 验收记录（§6.1 矩阵台账）, V0.3.8 增补段（六项语义冻结）, V0.3.7 真机验收发现与问题清单, V0.3.8 修复实施计划

### Community 260 - "V0.3.9-复测计划.md: C4 委派链卡死"
Cohesion: 0.50
Nodes (4): C4 委派链卡死, T4 引擎供给断点, 进程级网络沙盒, 五点产品级决策 B-01–B-05

### Community 265 - "test_v032_baselines.py: _jsonl()"
Cohesion: 0.50
Nodes (3): _jsonl(), M3 目标：subscribe_session 按 params.sessionId 路由通知。 0.3.1…, test_transport_routes_session_notifications_by_session_id()

### Community 266 - "test_v033_wiring.py: service()"
Cohesion: 0.50
Nodes (4): fixture, Path, service(), test_pairing_state_persisted_across_service_restart()

### Community 269 - "并行双AI计划_强逻辑AI.md: 千问参考音频能力验证"
Cohesion: 0.67
Nodes (3): 千问参考音频能力验证, 固定 ASR/TTS 模型, BYOK 语音边界

### Community 270 - "V0.3.7-验收记录.md: 电源提示双向翻转实测"
Cohesion: 0.67
Nodes (3): 电源提示双向翻转实测, power.get_status / power.status_changed, 电源保障与休眠提示

### Community 271 - "V0.3.9-验收记录.md: A10/A11 最终记录"
Cohesion: 0.67
Nodes (3): A10/A11 最终记录, 2026-09-11 三条裁决, Android 浏览器等效认定

### Community 272 - "repro_out.txt: 复现脚本输出 repro_out.t…"
Cohesion: 1.00
Nodes (3): 复现脚本输出 repro_out.txt, unknown_method: account.onboarding_complete, store 异常 'sequence'

### Community 273 - "test_acp_engine.py: V0.3.3：消费方在 TOOL_S…"
Cohesion: 0.67
Nodes (3): V0.3.3：消费方在 TOOL_STARTED 后 aclose() 回合，订阅槽位必须归还。 编排器用 contextlib.aclosing 包裹…, test_aclose_releases_session_subscription_after_mid_turn_break(), break_after_tool_started()

### Community 274 - "test_sounddevice_io.py: _fresh_streams()"
Cohesion: 0.67
Nodes (3): _fresh_streams(), fixture, 每个用例独立统计创建的流实例，并还原可能被替换的慢写流。

### Community 275 - "test_v039_s4_application_fixes.py: V039-S4-015：异常自述为空…"
Cohesion: 1.00
Nodes (3): V039-S4-015：异常自述为空时回落到类型名与结构化字段，不产出空壳。, test_failure_reason_never_returns_empty_shell(), __init__()

## Ambiguous Edges - Review These
- `白厄 × 神秘的古代机械 配对配置` → `千问声音设计（Voice Design）`  [AMBIGUOUS]
  config/pairs/phainon_ancient_machine.yaml · relation: conceptually_related_to

## Knowledge Gaps
- **547 isolated node(s):** `name`, `private`, `version`, `type`, `dev` (+542 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 2834 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **42 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `白厄 × 神秘的古代机械 配对配置` and `千问声音设计（Voice Design）`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `DesktopApplicationService` connect `桌面后端应用服务` to `规划式评审测试夹具`, `复现脚本与 ACP 链路`, `对话上下文与消息模型`, `ACP 编码引擎`, `会话编排器`, `提示词装配诊断`, `角色卡模型与 HSR 扩展`, `Codex 对话模型`, `角色卡编解码与兼容报告`, `Demo 服务与队列测试`, `委派与契约模型`, `存储增量缓冲与刷盘`, `移动端音频与 ASR 会话`, `桌面协议编解码测试`, `desktop_backend: ._account_exists()`, `语音运行时接线`, `语音播放与采集控制`, `角色上下文窗口与摘要`, `长期记忆与身份`, `桌面后端角色卡命令`, `世界书深度注入激活`, `角色卡仓库`, `后端引导与快照解析`, `adapters: Predictable rolepl…`, `Demo 语音合成`, `千问语音合成适配器`, `电源状态采集`, `adapters: customization_endp…`, `PNG 角色卡读写`, `desktop_backend: pairing.py`, `边车协议解析`, `摘要与投影存储校验`, `角色资产服务`, `记忆命令处理`, `adapters: PostJson`, `边车入口与信号处理`, `千问流式识别测试`, `摘要事件载荷与身份`, `Codex 鉴权服务`, `审批代理`, `回合指标存储`, `对话供应商配置`, `回合调度与终态`, `配对级长期记忆存储`, `音色绑定与参考音`, `控制租约`, `配对与鉴权服务`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `CodexAuthService` connect `Codex 鉴权服务` to `子进程启动与终止`, `复现脚本与 ACP 链路`, `ACP 编码引擎`, `test_v038_t4_delegation_chain.py: _FakeCodexAuth`, `后端引导与快照解析`, `desktop_backend: DiagnosticCallback`, `desktop_backend: _atomic_write_text…`, `Codex 登录状态测试`, `桌面后端应用服务`, `语音运行时接线`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `SQLiteStore` connect `存储增量缓冲与刷盘` to `规划式评审测试夹具`, `复现脚本与 ACP 链路`, `对话上下文与消息模型`, `ACP 编码引擎`, `角色卡编解码与兼容报告`, `委派与契约模型`, `桌面后端应用服务`, `storage: records.py`, `test_accounts_store.py: test_accounts_stor…`, `V0.3.9 存储测试`, `角色卡仓库`, `后端引导与快照解析`, `adapters: Predictable rolepl…`, `摘要与投影存储校验`, `角色资产服务`, `SQLite 存储与 schema 迁移`, `存储批量写入`, `回合指标存储`, `配对级长期记忆存储`, `storage: 打开数据库并完成迁移。 clock …`, `会话仓储`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Are the 58 inferred relationships involving `DesktopApplicationService` (e.g. with `QwenStreamingRecognizer` and `QwenSpeechSynthesizer`) actually correct?**
  _`DesktopApplicationService` has 58 INFERRED edges - model-reasoned connections that need verification._
- **Are the 53 inferred relationships involving `SQLiteStore` (e.g. with `CharacterAssetService` and `CharacterCardRepository`) actually correct?**
  _`SQLiteStore` has 53 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `ConversationOrchestrator` (e.g. with `ApprovalManager` and `ApprovalRequired`) actually correct?**
  _`ConversationOrchestrator` has 70 INFERRED edges - model-reasoned connections that need verification._