# B2 详细设计：Silero VAD 与 Qwen 流式 ASR/TTS

- 日期：2026-08-11
- 上游计划：`docs/plans/2026-08-10-mvp-implementation-plan.md` §5 B2
- 设计依据：`docs/specs/2026-08-10-roleplay-coding-harness-design.md` §7（语音链路）、§10（复用边界）、§13（最小错误处理）
- 参考文档：`docs/referances/千问声音复刻文档.md`、`docs/referances/千问声音设计文档.md`、`docs/referances/千问语音识别文档.md`
- 当前状态：计划 A 已全部落地（A1–A7），本文档把 B2 展开为可执行设计

## 1. 范围与目标

### 1.1 目标

把 A7 的测试语音闭环替换为真实链路，保持 `core/ports.py` 三个语音接口不变：

```text
麦克风 16 kHz 单声道 PCM
→ 本地 Silero VAD（onnxruntime）
→ qwen-audio-3.0-asr-flash-streaming（流式识别）
→ 最终非空转写自动发给白厄
→ 角色/助手自然语言消息
→ qwen-audio-3.0-tts-flash（复刻音色 + 设计音色）
→ 本地播放，可打断
```

### 1.2 已具备的外部条件

| 条件 | 现状 |
|---|---|
| `DASHSCOPE_API_KEY` | 已有，经环境变量注入 |
| API Host | `llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com`（华北2 北京，专属业务空间端点） |
| DashScope HTTP 地址 | `https://llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com/api/v1` |
| WebSocket 地址 | 按文档规则推导为 `wss://llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference`（联调验证点 R5） |
| 白厄参考语音 | `assets/reference_voices/白厄/` 下 3 段 WAV，均为 48 kHz / 16 bit / 单声道，时长 7.9 s / 9.7 s / 5.1 s |
| 神秘古代机械音色 | 无参考语音，使用声音设计（voice_prompt）创建 |

### 1.3 计划 A 已落地的可复用件（不重复建设）

| 组件 | 位置 | B2 中的角色 |
|---|---|---|
| `AsrEvent` / `AudioChunk` / `SpeechRequest` / `VadEvent` | `core/contracts.py` | 契约不变，适配器照此产出 |
| `SpeechRecognizer` / `SpeechSynthesizer` / `VoiceActivityDetector` | `core/ports.py` | 接口不变，新增真实实现 |
| `SpeechQueue` | `core/audio.py` | 播放队列原样复用 |
| `is_tts_eligible` / `available_input_methods` | `core/voice_policy.py` | 静音规则不变；补充 Markdown 拆分函数 |
| `MicrophoneCapture` / `AudioPlayer` | `adapters/audio/sounddevice_io.py` | 采集与播放原样复用 |
| `AudioControls`、输入区 PTT 信号 | `ui/audio_controls.py`、`ui/input_bar.py` | UI 控件已有，B2 只做接线 |
| `voice` extras（`onnxruntime`、`dashscope`）与 `live_qwen` marker | `pyproject.toml` | 依赖声明已就位，B2 首次安装 |
| 角色/助手 `voice_id` 字段 | `config/pairs/*.yaml`、`config/pairs.py` | 当前是 `demo-*` 占位，由脚本写回真实 ID |

### 1.4 明确不做

- 不复制旧项目浏览器 TypeScript/WASM 链路（只复制 Silero 的 `.onnx` 模型文件与参数语义）。
- 不接 AOQ 协议、不接 Qwen3-ASR-Flash-Realtime（realtime 链路），只用 `qwen-audio-3.0-asr-flash-streaming` 的 duplex WebSocket。
- 不实现热词、上下文增强、情感识别、敏感词过滤、字级时间戳。
- 不保存原始麦克风录音（设计文档 §8 不变）。
- 不做 B3 的另外两套搭档音色（脚本结构预留，配置后续复用）。

## 2. 总体架构

### 2.1 新增组件一览

| 组件 | 文件 | 职责 |
|---|---|---|
| `SileroVoiceActivityDetector` | `adapters/audio/silero_vad.py` | 本地 VAD 状态机，产出 `VadEvent` |
| `QwenStreamingRecognizer` | `adapters/audio/qwen_asr.py` | dashscope ASR 回调 → `AsrEvent` 异步流，含增量合并 |
| `QwenSpeechSynthesizer` | `adapters/audio/qwen_tts.py` | `SpeechRequest` → `AudioChunk` 异步流，可打断 |
| `VoiceRuntime` | `core/voice_runtime.py` | 上行/下行唯一协调器（新增，详见 §5） |
| `extract_speech_segments` | `core/voice_policy.py` 内新增 | 助手 Markdown 拆块，只留自然语言段落 |
| `scripts/create_qwen_voice.py` | 仓库根 `scripts/` | 一次性创建/登记音色并写回 pair YAML |

### 2.2 上行数据流（语音输入）

```text
MicrophoneCapture (20 ms / 640 B 块)
        │  VoiceRuntime 持有唯一采集流，逐块分发（tee）
        ├─► SileroVoiceActivityDetector.detect(队列桥接的 pcm_stream)
        │       内部重分帧 20 ms → 32 ms（512 样本）
        │       产出 VadEvent: listening / speech_started / speech_ended / false_trigger
        │
        └─► 语音段缓冲（8 块 pre-roll 环形缓冲 + 说话期间全部块）
                │  speech_started：开 QwenStreamingRecognizer 会话并补发 pre-roll
                │  说话中：实时转发
                │  speech_ended：recognizer.stop()，等待服务端收尾
                ▼
        AsrEvent partial → 输入区中转写回显
        AsrEvent final（合并后、非空）→ ConversationOrchestrator.handle_character_input(...)
        AsrEvent final 为空 → 丢弃，不发消息（误触发与空转写不提交）
```

要点：

- VAD 只做触发与切段，不做识别；ASR 会话的生命周期严格等于一个语音段。
- 采集天然限速（实时流），转发给 ASR 不再人为 sleep。
- `VoiceActivityDetector.detect` 只输出事件（端口契约不变），语音段音频由 VoiceRuntime 自己用 tee 方案保留，**不修改契约、不给 `VadEvent` 加 payload 字段**。
- 按键说话复用同一 ASR 通路：按下 = `speech_started`（无 pre-roll 缓冲，按下即开始攒帧），松开 = `speech_ended`。

### 2.3 下行数据流（语音输出）

```text
ConversationOrchestrator._message() 持久化完成后
        │  新增消息监听回调（见 §5.4）
        ▼
VoiceRuntime.on_message(message)
        │  is_tts_eligible(source, kind) 过滤 —— 命令、路径、代码、工具、审批、系统消息一律静音
        ├─ character.speech          → 全文入队
        └─ assistant.natural_language → extract_speech_segments(text) 后逐段入队
        ▼
SpeechQueue（FIFO，A7 原样）
        ▼
QwenSpeechSynthesizer.synthesize(SpeechRequest{text, voice_id, message_id})
        │  voice_id 按消息来源取当前 pair 的 character/assistant 音色
        ▼
AudioChunk 流 → AudioPlayer（按 TTS 实际采样率构造）
```

打断规则（与设计文档 §7.3 一致）：

- 播放期间 `SpeechQueue.playing == True`，VoiceRuntime 暂停向 VAD 喂帧（采集继续，帧丢弃），播放结束恢复。
- 按下说话键或点“停止语音”：先 `SpeechQueue.stop()` 清空待播、中断当前合成与播放，再开始录音。
- TTS 失败：文字消息已正常显示，只记一条静音 `system` 消息，不阻塞会话（设计文档 §13）。

## 3. 配置设计

### 3.1 `Settings` 扩展（`src/pair_harness/settings.py`）

```python
@dataclass(frozen=True)
class Settings:
    codex_bin: str = "codex"
    dialogue_base_url: str | None = None
    dialogue_api_key: str | None = None
    dialogue_model: str | None = None
    # —— B2 新增 ——
    dashscope_api_key: str | None = None          # DASHSCOPE_API_KEY
    dashscope_host: str = "llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com"
    dashscope_ws_url: str | None = None           # 覆盖项；默认由 host 推导
    dashscope_http_url: str | None = None         # 覆盖项；默认由 host 推导
    qwen_asr_model: str = "qwen-audio-3.0-asr-flash-streaming"
    qwen_tts_model: str = "qwen-audio-3.0-tts-flash"

    @property
    def resolved_ws_url(self) -> str:
        return self.dashscope_ws_url or f"wss://{self.dashscope_host}/api-ws/v1/inference"

    @property
    def resolved_http_url(self) -> str:
        return self.dashscope_http_url or f"https://{self.dashscope_host}/api/v1"
```

环境变量：

```text
DASHSCOPE_API_KEY                     必填（真实语音模式启动时校验，缺失给出明确错误）
PAIR_HARNESS_DASHSCOPE_HOST           可选，默认上文专属端点
PAIR_HARNESS_DASHSCOPE_WS_URL         可选覆盖（联调验证点 R5 失败时使用）
PAIR_HARNESS_DASHSCOPE_HTTP_URL       可选覆盖
```

约束（沿用 B1 原则）：密钥只经环境变量进入进程，配置文件与日志永不出现密钥；`voice_id` 不是密钥，允许写入 `config/pairs/*.yaml`。

### 3.2 依赖安装

`pyproject.toml` 的 `voice` extras 已含 `onnxruntime>=1.18`、`dashscope>=1.20`，首次执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ui,voice,dev]"
```

不新增第三方依赖；`websocket-client`、音频解码库等均不需要（WebSocket 由 dashscope SDK 持有；TTS 直接请求 PCM，见 §4.3）。

## 4. 适配器详细设计

### 4.1 Silero VAD（`adapters/audio/silero_vad.py`）

**模型文件**：从旧项目复制 `E:\AI\二次元情感陪伴助手\web\public\vad-web\silero_vad_v5.onnx` 到 `assets/models/silero_vad_v5.onnx`，并在 `assets/models/` 附 `README.md` 注明来源（Silero VAD 上游仓库，MIT License）与用途。只复制模型权重文件，不复制 `vad.worklet.bundle.min.js` 等浏览器代码。

**参数**（沿用旧项目 `web/src/lib/audio/vad-config.ts` 的语义，帧长按 Silero v5 在 16 kHz 下的 512 样本 = 32 ms 换算）：

| 参数 | 值 | 含义 |
|---|---:|---|
| `threshold` | 0.45 | 语音概率判定阈值 |
| `pre_speech_pad_frames` | 8（≈256 ms） | 开口前保留的帧数（pre-roll，补发给 ASR） |
| `redemption_frames` | 18（≈576 ms） | 结束等待：连续低于阈值达到该帧数才判 `speech_ended` |
| `min_speech_frames` | 4（≈128 ms） | 最短有效语音，不足判 `false_trigger` |

**状态机**：

```text
listening ──prob ≥ threshold──► speech_started（开始累积语音帧计数）
speech_started ──prob < threshold 且未满 redemption──► 保持（短暂停顿不打断）
speech_started ──prob ≥ threshold（redemption 内恢复）──► 清零静音计数，继续
speech_started ──连续静音满 18 帧──► 帧数 ≥ 4 → speech_ended
                                  └ 帧数 < 4 → false_trigger（缓冲丢弃，不触发 ASR）
speech_ended / false_trigger ──► 回到 listening
```

**实现要点**：

- 内部维护 onnxruntime `InferenceSession` 与 v5 模型的循环状态张量（`state`，形状 `(2, 1, 128)`；输入 `input` `(1, 512)` float32、`sr`=16000）。每个 `detect()` 会话开始时重置状态。
- **重分帧器**：输入是任意大小的 PCM 块（实际为 20 ms / 640 B），内部按 512 样本（1024 B）切帧，不足一帧的尾部留存与下一块拼接。int16 字节流转 float32 归一化（`/32768.0`）后送入模型。
- 单次推理耗时毫秒级，直接在异步迭代器内同步调用，不进线程池（注释说明理由，避免过度设计）。
- 模型文件缺失或 onnxruntime 不可导入时，构造阶段抛 `VadUnavailableError`；VoiceRuntime 捕获后按设计文档 §7.2 退回按键说话，并在 UI 给出明确提示。

```python
class SileroVoiceActivityDetector(VoiceActivityDetector):
    def __init__(self, model_path: Path, *, threshold: float = 0.45,
                 pre_speech_pad_frames: int = 8, redemption_frames: int = 18,
                 min_speech_frames: int = 4) -> None: ...

    async def detect(self, pcm_stream: AsyncIterable[bytes]) -> AsyncIterator[VadEvent]:
        # 进入即产出 listening；之后按状态机产出事件
        ...
```

### 4.2 Qwen 流式 ASR（`adapters/audio/qwen_asr.py`）

**SDK 用法**：`dashscope.audio.asr.Recognition`，半双工 WebSocket。参数：

```python
Recognition(
    model=settings.qwen_asr_model,       # qwen-audio-3.0-asr-flash-streaming
    format="pcm",
    sample_rate=16000,
    semantic_punctuation_enabled=False,  # 保持默认断句行为；客户端以本地 VAD 断句为主
    callback=...,
)
dashscope.base_websocket_api_url = settings.resolved_ws_url
```

**线程桥**：SDK 回调运行在 SDK 自有线程。回调内只做一件事——`loop.call_soon_threadsafe(queue.put_nowait, ...)` 把原始事件塞进 `asyncio.Queue`；适配器的异步迭代器从队列取出并映射为 `AsrEvent`。这与旧项目 `FunASRRealtimeSession` 的回调→队列模式一致，只是队列换成 asyncio 版本。

**事件映射**：

| SDK 回调 | 条件 | 产出 |
|---|---|---|
| `on_event` | `sentence_end=False` 且文本非空 | `AsrEvent("partial", text=合并后的当前转写)` |
| `on_event` | `sentence_end=True` | 沉淀进稳定段，同时产出一次 `partial` 更新显示 |
| `stop()` 后 SDK 收尾完成 | 合并结果非空 | `AsrEvent("final", text=合并结果)` |
| 同上 | 合并结果为空 | 不产出任何事件（空转写不发送） |
| `on_error` | — | `AsrEvent("error", error=消息)` |

**增量合并**：把旧项目 `server/app/services/asr/fun_asr_realtime_client.py` 中 `_merge_result_events` 的语义移植为纯函数（计划明确“参考旧项目的 ASR 增量合并”）：

```python
def merge_asr_segments(events: list[_RawSentence]) -> str:
    """stable 段 + 当前 partial 合并。

    规则（与旧项目一致）：
    - sentence_end 的文本沉淀为 stable 段；
    - 新段与上一段做包含判断与最长后缀-前缀重叠去重；
    - partial 之间取信息更全者（前缀包含关系取长者，否则按重叠拼接）；
    - 全部为空时返回空串（调用方据此抑制 final）。
    """
```

`qwen_asr.py` 内定义轻量 `_RawSentence(text, sentence_end)` 作为输入，合并函数不依赖 SDK 类型，保证可离线单测。

**生命周期约束**：一个 `stream_transcribe` 调用对应一次 `Recognition.start()/stop()`；`stop()` 后等待 `on_complete` 或 `on_error` 收尾（带 5 s 超时，超时按 error 处理），随后关闭迭代器。会话不复用，避免跨语音段的状态污染。

### 4.3 Qwen TTS（`adapters/audio/qwen_tts.py`）

**SDK 用法**：`dashscope.audio.tts_v2.SpeechSynthesizer`：

```python
SpeechSynthesizer(
    model=settings.qwen_tts_model,   # qwen-audio-3.0-tts-flash，与音色创建时的 target_model 必须一致
    voice=request.voice_id,
    format="pcm",                    # 直接要 PCM，避免引入音频解码依赖
    sample_rate=24000,               # 联调验证点 R3：以 SDK 实际支持为准
    callback=...,                    # on_data 收增量音频
)
```

**事件映射**：`on_data(二进制)` → `AudioChunk(pcm=..., sample_rate=24000, channels=1)`；`on_complete` → 最后一个 `AudioChunk(final=True)`（无音频也要发，作为播放结束信号）；`on_error` → 抛 `QwenTtsError`，由 VoiceRuntime 降级为静音 system 消息。

**打断**：`synthesize` 迭代器被关闭（aclose）时调用 SDK 的关闭方法断开 WebSocket，未播完的块直接丢弃。VoiceRuntime 在 `SpeechQueue.stop()` 时触发。

**风险与降级**（联调验证点 R3）：若该模型不支持 `format="pcm"`，按以下顺序降级——`"wav"`（剥 44 字节头后按 PCM 处理）→ 报错并给出“请检查模型音频格式支持”的明确提示。**不引入 mp3 解码依赖**。`AudioPlayer` 按协商采样率构造（`AudioPlayer(sample_rate=24000)`），A7 的实现已支持参数化，无需修改。

### 4.4 音色创建脚本（`scripts/create_qwen_voice.py`）

一次性脚本，应用运行时只消费 `voice_id`。用法：

```powershell
# 白厄：声音复刻（参考语音 → voice_id）
.\.venv\Scripts\python.exe scripts\create_qwen_voice.py clone `
    --pair phainon_ancient_machine --speaker character `
    --audio-dir "assets\reference_voices\白厄" --prefix phainon

# 神秘古代机械：声音设计（voice_prompt → voice_id）
.\.venv\Scripts\python.exe scripts\create_qwen_voice.py design `
    --pair phainon_ancient_machine --speaker assistant `
    --prefix ancient-machine --prompt-file config\voices\ancient_machine_prompt.txt

# 已在控制台手动创建时：直接登记
.\.venv\Scripts\python.exe scripts\create_qwen_voice.py adopt `
    --pair phainon_ancient_machine --speaker character --voice-id <已有ID>
```

**clone 子命令**：

1. 预处理：扫描音频目录，按千问声音复刻文档的音频要求校验（WAV/MP3/M4A、≥16 kHz、≤10 MB、≤60 s）。当前三段素材为 48 kHz / 16 bit / 单声道（满足采样率），单段最长 9.7 s。选段策略：默认取最长单段（9.7 s）；`--concat` 时按给定顺序拼接两段、中间补 0.5 s 静音得到约 18 s 样本（停顿 ≤2 s 符合要求），拼接产物写到 `assets/reference_voices/processed/`，不上传原始目录之外的内容。
2. 创建音色：`POST {resolved_http_url}/services/audio/tts/customization`，`model="voice-enrollment"`，`input.action="create_voice"`，`target_model="qwen-audio-3.0-tts-flash"`，`prefix="phainon"`。
3. 音频上传（联调验证点 R1）：文档示例的 `url` 字段要求可访问地址。脚本按序尝试——`--url` 显式给定 > 本地文件 base64 data URI（参照 Qwen-TTS 复刻的 `audio.data` 形态，需联调确认 voice-enrollment 是否接受）> 提示用户在百炼控制台手动创建后用 `adopt` 登记。**脚本不自动把音频传到任何第三方存储。**
4. 成功后把返回的 `voice_id` 写回 `config/pairs/phainon_ancient_machine.yaml` 的 `character.voice_id`。

**design 子命令**：

1. `voice_prompt` 定稿（存 `config/voices/ancient_machine_prompt.txt`，≤500 字符，可随时改写后重建）。设计依据角色卡原文：“年头很久，性情克制，话少，声音像新铸的青铜，沉稳，听不出什么情绪”“语气倒也不冷”“句子要写完整，让人一遍听明白”：

   > 中年男性声音，音调偏低，音色浑厚圆润，带新铸青铜般的金属共鸣，干净不沙哑。语速中速偏慢，吐字清晰，字字分明。语气平稳克制，几乎听不出情绪起伏，但不觉冷漠。适合语音助手的工作汇报与旁白。

   逐条对照角色卡：
   - 写“新铸青铜般的金属共鸣，干净不沙哑”，不写沙哑、磨损、老旧——卡面是新铸的青铜，不是生锈的老机械；
   - 不写低语、耳语——它的台词全是执行汇报，要求一遍听明白，耳语损失清晰度；
   - 不写“冷静、神秘”这类情绪色彩——卡面要求听不出情绪，平稳克制即可；
   - 补“但不觉冷漠”——对应“语气倒也不冷”，防止生成过于生硬的机器腔；
   - 用途写“工作汇报与旁白”，不写科幻配音——搭档主题是古希腊色彩的新铸青铜金，不是科幻路线。

2. `preview_text` 用角色卡自带的回执口径，试听即工作场景效果：“任务完成。文档已生成，存放在项目目录。”
3. 请求形态（联调验证点 R2）：千问声音设计文档标明 Qwen-Audio-TTS 支持声音设计但未给出该模型系列的请求示例，脚本按 CosyVoice 示例的同构形态发送（`voice-enrollment` + `voice_prompt` + `preview_text` + `target_model="qwen-audio-3.0-tts-flash"`）。若服务端拒绝，**不改用其他合成模型**（音色绑定 target_model，跨模型不可用），降级路径：在百炼控制台用声音设计创建后 `adopt`，或改用 `qwen-audio-3.0-tts-flash` 预置音色中接近设定的一个。
4. 返回预览音频时保存到 `assets/reference_voices/processed/ancient_machine_preview.wav` 供试听，确认后写回 YAML。

**通用约束**：目标 speaker 已是非 `demo-*` 的 voice_id 时默认跳过并打印现状，`--force` 才重建；写回 YAML 只改 `voice_id` 一个字段，其余内容与注释保持原样（用 PyYAML  round-trip 之外的保守做法：按行文本替换 `voice_id:` 值，避免重排整个文件）。

## 5. VoiceRuntime：上行/下行协调器（`core/voice_runtime.py`）

计划 B2 原文只列了三个适配器，但 A 阶段没有任何运行时组件把麦克风、VAD、ASR、TTS、Orchestrator 串起来（`SpeechQueue` 与 demo 适配器仅被测试消费）。B2 必须新增这一层，否则真实适配器无处可挂。它放在 `core/`（不碰供应商 SDK，只做编排），三个语音端口、采集、播放全部依赖注入，UI 与 demo 环境可以注入假实现。

### 5.1 职责与状态

```python
class VoiceRuntime:
    def __init__(
        self,
        *,
        orchestrator: ConversationOrchestrator,
        recognizer: SpeechRecognizer,
        synthesizer: SpeechSynthesizer,
        vad: VoiceActivityDetector | None,      # None 表示退回纯按键说话
        capture_factory: Callable[[], MicrophoneCapture],
        player: AudioPlayer,
        queue: SpeechQueue,
        pair_config: PairConfig,
        on_vad_state: Callable[[str], None] = lambda s: None,      # UI 状态回调
        on_asr_partial: Callable[[str], None] = lambda t: None,    # 输入区回显
        on_error: Callable[[str], None] = lambda m: None,          # 静音 system 提示
    ) -> None: ...

    async def start_listening(self) -> None: ...   # 打开麦克风，进入 VAD 循环
    async def stop_listening(self) -> None: ...
    async def push_to_talk_start(self) -> None: ...  # 先停 TTS，再开 ASR 直录
    async def push_to_talk_stop(self) -> None: ...   # 收尾识别并发送
    def stop_speaking(self) -> None: ...             # 停 TTS + 清空队列
    def on_message(self, message: Message) -> None:  # 下行 TTS 入口
    async def run_playback_loop(self) -> None: ...   # 消费 SpeechQueue
```

状态集合：`idle / listening / speech_started / speech_ended / false_trigger / playing`，与 `AudioControls._VAD_LABELS` 已有键一一对应，经 `on_vad_state` 回调驱动 UI。按键说话不新增状态键：录音期间显示 `speech_started`，松开等待识别期间显示 `speech_ended`。

### 5.2 关键行为

- **TTS 暂停 VAD**：播放循环 `begin_playback` 期间停止向 VAD 队列喂帧（采集块直接丢弃）；`end_playback` 或 `stop()` 后恢复，并向 VAD 迭代器补一次状态重置（重开 detect 会话，避免把播放尾音误判为说话）。
- **按键说话优先**：`push_to_talk_start` 先 `stop_speaking()`，再挂起 VAD 通路，直接开 ASR 会话录音；松开后等待 final，非空才提交。
- **提交目标**：VAD/PTT 产出的最终文本交给 `orchestrator.handle_character_input(...)`；目标为助手的场景 UI 不提供 VAD（`available_input_methods` 已保证），PTT 提交走 `handle_direct_input`。
- **voice_id 选择**：`message.source == CHARACTER` 用 `pair_config.character.voice_id`，助手自然语言用 `pair_config.assistant.voice_id`。
- **失败降级**：
  - VAD 构造失败（`VadUnavailableError`）→ `vad=None` 运行，UI 提示“VAD 不可用，已切换为按键说话”；
  - ASR error → 保留输入状态，提示可改文字输入（设计文档 §13）；
  - TTS error → 该条 `SpeechRequest` 丢弃，记静音 system 提示，继续播后续队列。

### 5.3 助手 Markdown 拆分（`core/voice_policy.py` 新增）

```python
def extract_speech_segments(text: str) -> list[str]:
    """助手自然语言消息 → 可朗读段落。

    剔除围栏代码块、行内代码、纯命令/路径行（以 `$`、`>` 开头或形如
    文件路径的行）；剩余按空行分段，去掉纯标点段；保持原有顺序。
    """
```

A7 计划要求“助手 Markdown 按块拆分，只有自然语言段落入队”，但 A 阶段只实现了消息级过滤，本函数补齐该行为并配独立单测。

### 5.4 Orchestrator 消息监听（最小改动）

`ConversationOrchestrator` 新增：

```python
def add_message_listener(self, callback: Callable[[Message], None]) -> None:
    """消息持久化完成后同步调用。供 VoiceRuntime 挂接 TTS。"""
```

在 `_message()` 内消息写入 store 之后逐个调用监听器。不引入事件总线，不改任何现有方法的签名与返回值；UI 的 `qt_bridge` 不受影响。

### 5.5 UI 接线（`ui/app.py`、`ui/main_window.py`、`ui/input_bar.py`）

- `app.py` 新增 `--real-voice` 开关：构造 `Settings.from_environment()`，校验 `dashscope_api_key` 存在；用真实三件套替换 demo 音频适配器，创建 `VoiceRuntime` 并启动监听与播放循环。B1 的 `--real` 落地后隐含 `--real-voice`；此前语音链路可用 `--demo --real-voice` 与脚本引擎组合做半真实联调。
- `main_window.py`：把 `input_bar.push_to_talk_pressed/released`、`audio_controls.stop_requested` 连到 VoiceRuntime 对应方法（经 `qt_bridge` 的单向桥，不反向依赖）。
- `input_bar.py` 新增 `set_asr_interim(text: str)` 方法：partial 转写以占位样式显示在输入框内，final 提交后清空。除此方法外不改动输入区既有行为。

## 6. 测试设计

### 6.1 单元测试（离线，不触网）

| 文件 | 用例要点 |
|---|---|
| `tests/unit/test_vad_state.py` | 用合成 PCM（静音块 / 恒定幅度噪声块模拟语音）驱动状态机：listening→speech_started；短突发 <4 帧判 `false_trigger`； redemption 内恢复不结束；连续静音 18 帧判 `speech_ended`；20 ms 块跨块重分帧为 512 样本帧；模型文件缺失抛 `VadUnavailableError`。模型推理本身 mock 掉（注入概率序列），不依赖 onnx 文件 |
| `tests/unit/test_asr_merge.py` | 移植旧项目 `test_fun_asr_result_merge` 的用例语义：stable 段拼接、后缀-前缀重叠去重、partial 择优（前缀包含取长者）、尾段 partial 兜底、全空返回空串 |
| `tests/unit/test_qwen_event_mapping.py` | mock SDK 回调对象喂事件：`sentence_end=False`→partial、`stop` 收尾→final、空合并→无 final、`on_error`→error；TTS 侧 `on_data`→AudioChunk、`on_complete`→`final=True`、迭代器关闭触发 SDK 关闭 |
| `tests/unit/test_speech_segments.py` | 代码块/行内代码/命令行/路径行被剔除；多段落顺序保持；全代码消息返回空列表 |
| `tests/unit/test_voice_runtime.py` | 注入假 recognizer/synthesizer/vad：播放中暂停 VAD 喂帧；PTT 按下先停 TTS；空 final 不调用 orchestrator；tts_eligible 消息按来源选 voice_id；VAD 不可用时 PTT 通路仍可用 |

### 6.2 集成测试（真实服务，默认跳过）

`tests/integration/test_qwen_audio_live.py`，`live_qwen` marker + `RUN_LIVE_QWEN=1` 双重门槛：

- ASR：把白厄参考语音（48 kHz WAV 重采样为 16 kHz PCM，脚本内用 numpy 做线性插值，不新增解码依赖）按 100 ms / 3200 B 节奏推入 `QwenStreamingRecognizer`，断言合并后的 final 包含素材文本中的连续关键词（如“回头见”）。
- TTS：用已创建的 voice_id 合成“你好，我是白厄。”，断言产出总时长 >0.5 s 的 PCM，写入 `.tmp/` 供人工试听。
- 音色脚本：`adopt` 路径写回 YAML 的往返测试（mock HTTP 即可，不真实创建）。

### 6.3 UI 测试

`tests/ui/test_voice_controls_live.py`（offscreen）：`--real-voice` 装配下 VAD 状态回调驱动 `AudioControls` 文案；ASR partial 出现在输入区并被 final 清空；停止按钮触发 `stop_speaking`。

## 7. 实施顺序

按依赖关系分六步，每步跑通验收再推进，单独 commit：

1. **B2.1 配置与依赖**：`Settings` 扩展、安装 voice extras、复制 VAD 模型文件与许可说明。验收：`pip install` 成功，`python -c "import onnxruntime, dashscope"` 通过。
2. **B2.2 Silero VAD**：`silero_vad.py` + `test_vad_state.py`。验收：`pytest -q tests\unit\test_vad_state.py`。
3. **B2.3 Qwen ASR**：`qwen_asr.py`（含合并函数）+ `test_asr_merge.py` + `test_qwen_event_mapping.py` 的 ASR 部分。验收：三个单测文件通过。
4. **B2.4 Qwen TTS**：`qwen_tts.py` + `test_qwen_event_mapping.py` 的 TTS 部分 + `test_speech_segments.py`。验收：单测通过。
5. **B2.5 音色脚本**：`create_qwen_voice.py` + 联调验证点 R1/R2，产出两个真实 `voice_id` 并写回 pair YAML。验收：`adopt` 往返测试 + 人工试听预览音频。
6. **B2.6 VoiceRuntime 与 UI 接线**：`voice_runtime.py`、Orchestrator 监听、输入区回显、`--real-voice`。验收：全部单测/UI 测试 + live 集成测试 + 人工验收清单。

## 8. 联调验证点（按风险排序）

| 编号 | 风险 | 验证方式 | 兜底 |
|---|---|---|---|
| R1 | `voice-enrollment` 是否接受 base64 data URI 形式的音频 | B2.5 首次真实调用 | `--url` 显式传入，或控制台手动创建后 `adopt` |
| R2 | `qwen-audio-3.0-tts-flash` 的声音设计请求形态文档未给出示例 | B2.5 首次真实调用 | 控制台手动设计后 `adopt`；或改用预置音色 |
| R3 | TTS 是否支持 `format="pcm"` 及可用采样率 | B2.6 live 测试 | 降级 `wav` 剥头；绝不引入 mp3 解码 |
| R4 | dashscope SDK 回调线程与 qasync 事件循环的桥接 | B2.3/B2.4 单测（模拟跨线程回调） | 统一 `call_soon_threadsafe` 入队，SDK 对象不跨线程复用 |
| R5 | 专属端点的 WebSocket 路径推导是否正确 | B2.6 live 测试 | `PAIR_HARNESS_DASHSCOPE_WS_URL` 覆盖 |
| R6 | 48 kHz 素材的重采样质量影响复刻效果 | B2.5 试听 | 保持 48 kHz 直接上传（文档要求 ≥16 kHz） |

### 8.1 联调发现（2026-08-11 真实调用记录）

- **R1 通过**：`voice-enrollment`/`create_voice` 接受 base64 data URI 音频（白厄拼接音频 23.7 s，48 kHz/16 bit/单声道）。
- **R2 通过**：`qwen-audio-3.0-tts-flash` 支持 `voice-enrollment` + `create_voice` + `voice_prompt` 形态；`prefix` 经 `normalize_prefix` 去下划线并截断至 10 字符（`ancient_machine` → `ancientmac`）。
- **R3 扩展发现（适配器缺陷，已修复）**：TTS 真实服务在收到 finish request（`streaming_complete`）前**不会发送 FINISHED 消息**。原 `_run_synthesis` 在 `streaming_call` 后死等 `on_complete`（done 循环），与服务端互相等待，约 15 s 后服务端超时才收尾 → asyncio 侧 `_TAIL_TIMEOUT_S` 报"合成收尾超时"。音频帧本身在合成过程中已随流式到达（不依赖 finish）。修复：`streaming_call` 后保留 0.1 s 取消窗口（让 `aclose` 可走 `streaming_cancel`），窗口过后立即 `streaming_complete(complete_timeout_millis=20_000)` 等待服务端 FINISHED；正常合成约 2~3 s 完成。单测 Fake 原先在 `streaming_call` 内直接回 `on_complete`，掩盖了此行为差异。
- **R5 通过**：`resolved_ws_url`（`wss://{host}/api-ws/v1/inference`）对 ASR 与 TTS 均可用；ASR/TTS live 测试（`RUN_LIVE_QWEN=1 pytest -m live_qwen`）2 passed。
- **R6 通过**：ASR 对 48 kHz→16 kHz 线性插值重采样素材识别出"回头见"；复刻直接上传 48 kHz 原始拼接音频。
- 真实 voice_id：character=`qwen-audio-3.0-tts-flash-phainon-46e9bd0087cd4c4c8d29e1b9f1b5db32`（复刻），assistant=`qwen-audio-3.0-tts-flash-vd-ancientmac-a26ce26e55414e219fe00360e24b4f19`（设计）；均已 `adopt` 写回 `config/pairs/phainon_ancient_machine.yaml`。

## 9. 验收清单

### 9.1 自动验收

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_asr_merge.py tests\unit\test_vad_state.py tests\unit\test_qwen_event_mapping.py tests\unit\test_speech_segments.py tests\unit\test_voice_runtime.py
$env:RUN_LIVE_QWEN = "1"
.\.venv\Scripts\python.exe -m pytest -q -m live_qwen tests\integration\test_qwen_audio_live.py
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests\ui
.\.venv\Scripts\python.exe -m pair_harness --real
```

（最后一条与 B1 合并验收；B1 未完成前用 `--demo --real-voice` 验证语音链路。）

### 9.2 人工验收（展开计划 B2 原文五条）

1. VAD 识别完成后自动发送给白厄：说一句话停顿约 0.6 s，输入区中转写消失并作为用户消息发出；咳嗽、敲桌等短触发不产生消息。
2. 按键说话可以打断 TTS：播放角色语音途中按下说话键，播放立即停止，松开后新识别文本正常提交。
3. “直接交给助手”目标下输入区不出现 VAD 开关与指示灯。
4. 角色回应用白厄复刻音色、助手自然语言用古代机械设计音色，两者不串；切换聊天后音色跟随当前搭档配置。
5. 命令、路径、代码块、工具卡片、审批与系统消息全程静音；助手含代码块的消息只有自然语言段落被朗读。

## 10. 文件清单

新增：

- `assets/models/silero_vad_v5.onnx`（复制自旧项目，附 `assets/models/README.md` 许可说明）
- `config/voices/ancient_machine_prompt.txt`
- `scripts/create_qwen_voice.py`
- `src/pair_harness/adapters/audio/silero_vad.py`
- `src/pair_harness/adapters/audio/qwen_asr.py`
- `src/pair_harness/adapters/audio/qwen_tts.py`
- `src/pair_harness/core/voice_runtime.py`
- `tests/unit/test_vad_state.py`
- `tests/unit/test_asr_merge.py`
- `tests/unit/test_qwen_event_mapping.py`
- `tests/unit/test_speech_segments.py`
- `tests/unit/test_voice_runtime.py`
- `tests/integration/test_qwen_audio_live.py`
- `tests/ui/test_voice_controls_live.py`

修改（最小范围）：

- `src/pair_harness/settings.py`：DashScope 配置项（§3.1）
- `src/pair_harness/core/voice_policy.py`：新增 `extract_speech_segments`
- `src/pair_harness/core/orchestrator.py`：新增 `add_message_listener` 与 `_message()` 内一行调用
- `src/pair_harness/ui/app.py`：`--real-voice` 装配分支
- `src/pair_harness/ui/main_window.py`：VoiceRuntime 信号接线
- `src/pair_harness/ui/input_bar.py`：新增 `set_asr_interim`
- `config/pairs/phainon_ancient_machine.yaml`：仅由脚本改写两个 `voice_id` 字段

建议提交序列：`feat: add silero vad adapter` → `feat: add qwen streaming asr` → `feat: add qwen tts` → `feat: add voice enrollment script` → `feat: wire realtime voice runtime`。
