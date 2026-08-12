# assets/models：本地模型

本目录存放随项目分发的本地推理模型。

## silero_vad_v5.onnx

- 用途：16 kHz 单声道语音活动检测（VAD v5），由 `pair_harness.adapters.audio.silero_vad.SileroVoiceActivityDetector` 加载。
- 来源：Silero VAD v5（https://github.com/snakers4/silero-vad ），onnx 导出模型。
- 许可：MIT License（与 Silero VAD 项目一致）。模型文件只包含推理参数，VAD 推理在本地完成。
- 获取方式：本文件从旧项目 `E:/AI/二次元情感陪伴助手/web/public/vad-web/silero_vad_v5.onnx` 复制（哈希一致），也可从 Silero VAD 官方仓库自行下载后覆盖。
- 校验：sha256 见下方（复制后由 CI/构建脚本核对）。

```
sha256  2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f  silero_vad_v5.onnx
```

- 运行时依赖：onnxruntime（`pip install -e ".[voice]"` 自动安装）。VAD 资源与依赖齐备时启用语音检测；其余环境使用按键说话（PTT）模式，其他功能照常运行。
