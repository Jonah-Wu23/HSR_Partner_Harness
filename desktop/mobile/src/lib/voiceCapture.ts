/**
 * V0.3.5 手机端语音采集引擎。
 *
 * 协议：getUserMedia → AudioContext + AudioWorklet 重采样到 16kHz s16le mono PCM
 * → base64 → 按约 160 ms 分片经 WS 上行（voice.mobile_audio_chunk）。
 *
 * 自动检测模式在 Worklet 内做 RMS 静音检测，连续静音达到阈值后回调主线程 stop。
 */

const TARGET_SAMPLE_RATE = 16000;
const DEFAULT_CHUNK_DURATION_MS = 160;
const DEFAULT_SILENCE_THRESHOLD_DB = -45;
const DEFAULT_SILENCE_HOLD_MS = 1200;

function dbToLinear(db: number): number {
  return Math.pow(10, db / 20);
}

export function int16ArrayToBase64(samples: Int16Array): string {
  const bytes = new Uint8Array(samples.buffer);
  let binary = "";
  const len = bytes.length;
  const chunkSize = 0x8000;
  for (let i = 0; i < len; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  if (typeof btoa === "function") {
    return btoa(binary);
  }
  // 兜底：测试环境可能无 btoa
  return Buffer.from(binary, "binary").toString("base64");
}

const CAPTURE_PROCESSOR_CODE = `
class VoiceCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.active = false;
    this.buffer = [];
    this.inputSampleRate = 48000;
    this.chunkSize = 2560;
    this.silenceThreshold = 0.0056;
    this.silenceHoldFrames = 0;
    this.silenceCounter = 0;
    this.port.onmessage = (event) => {
      const data = event.data;
      if (data.type === "start") {
        this.active = true;
        this.inputSampleRate = data.inputSampleRate;
        this.chunkSize = data.chunkSize;
        this.silenceThreshold = data.silenceThreshold;
        this.silenceHoldFrames = data.silenceHoldFrames;
        this.buffer = [];
        this.silenceCounter = 0;
      } else if (data.type === "stop") {
        this.active = false;
      }
    };
  }

  process(inputs, outputs, params) {
    if (!this.active) return true;
    const input = inputs[0] && inputs[0][0];
    if (!input || input.length === 0) return true;

    const ratio = this.inputSampleRate / 16000;
    let outIndex = 0;
    while (true) {
      const inputIndex = outIndex * ratio;
      if (inputIndex >= input.length - 1) break;
      const i0 = Math.floor(inputIndex);
      const frac = inputIndex - i0;
      const a = input[i0];
      const b = input[i0 + 1] !== undefined ? input[i0 + 1] : a;
      this.buffer.push(a + (b - a) * frac);
      outIndex++;
    }

    let energy = 0;
    for (let i = 0; i < input.length; i++) {
      energy += input[i] * input[i];
    }
    const rms = Math.sqrt(energy / input.length);
    if (rms < this.silenceThreshold) {
      this.silenceCounter++;
      if (this.silenceCounter >= this.silenceHoldFrames) {
        this.port.postMessage({ type: "silence" });
        this.silenceCounter = 0;
      }
    } else {
      this.silenceCounter = 0;
    }

    while (this.buffer.length >= this.chunkSize) {
      const chunkSamples = this.buffer.slice(0, this.chunkSize);
      this.buffer = this.buffer.slice(this.chunkSize);
      const int16 = new Int16Array(this.chunkSize);
      for (let i = 0; i < this.chunkSize; i++) {
        const v = Math.max(-1, Math.min(1, chunkSamples[i] || 0));
        int16[i] = Math.round(v * 32767);
      }
      this.port.postMessage({ type: "chunk", samples: int16.buffer }, [int16.buffer]);
    }

    return true;
  }
}
registerProcessor("voice-capture-processor", VoiceCaptureProcessor);
`;

export interface VoiceCaptureEngineOptions {
  onChunk(seq: number, base64: string): void | Promise<void>;
  onSilence?(): void;
  onError(error: Error): void;
  enableSilenceDetection?: boolean;
  chunkDurationMs?: number;
  silenceThresholdDb?: number;
  silenceHoldMs?: number;
}

export interface VoiceCaptureEngine {
  start(stream: MediaStream): Promise<void>;
  stop(): void;
  isActive(): boolean;
}

/**
 * 创建音频采集引擎。实际采集由 AudioWorkletProcessor 在独立线程完成，
 * 主线程只负责把回传的 Int16Array 编码成 base64 并调用 onChunk。
 */
export function createVoiceCaptureEngine(options: VoiceCaptureEngineOptions): VoiceCaptureEngine {
  const {
    onChunk,
    onSilence,
    onError,
    enableSilenceDetection = false,
    chunkDurationMs = DEFAULT_CHUNK_DURATION_MS,
    silenceThresholdDb = DEFAULT_SILENCE_THRESHOLD_DB,
    silenceHoldMs = DEFAULT_SILENCE_HOLD_MS,
  } = options;

  let audioContext: AudioContext | null = null;
  let workletNode: AudioWorkletNode | null = null;
  let sourceNode: MediaStreamAudioSourceNode | null = null;
  let mediaStream: MediaStream | null = null;
  let seq = 0;
  let active = false;
  let moduleUrl: string | null = null;

  const chunkSize = Math.round((TARGET_SAMPLE_RATE * chunkDurationMs) / 1000);
  const silenceThreshold = dbToLinear(silenceThresholdDb);
  // process 每次约 128 个输入样点；按输入采样率估算帧数
  const silenceHoldFrames = Math.ceil(
    (silenceHoldMs * 48000) / 1000 / 128,
  );

  return {
    async start(stream) {
      if (active) return;
      if (typeof AudioContext === "undefined") {
        throw new Error("当前环境不支持 AudioContext");
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("当前浏览器不支持麦克风采集");
      }

      audioContext = new AudioContext();
      if (!audioContext.audioWorklet) {
        throw new Error("当前浏览器不支持 AudioWorklet");
      }

      const blob = new Blob([CAPTURE_PROCESSOR_CODE], { type: "application/javascript" });
      moduleUrl = URL.createObjectURL(blob);
      await audioContext.audioWorklet.addModule(moduleUrl);

      mediaStream = stream;
      sourceNode = audioContext.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(audioContext, "voice-capture-processor");

      workletNode.port.onmessage = async (event) => {
        const data = event.data as { type?: string; samples?: ArrayBuffer };
        if (data.type === "chunk" && data.samples) {
          const int16 = new Int16Array(data.samples);
          const base64 = int16ArrayToBase64(int16);
          const currentSeq = seq;
          seq += 1;
          try {
            await onChunk(currentSeq, base64);
          } catch (err) {
            onError(err instanceof Error ? err : new Error(String(err)));
            this.stop();
          }
        } else if (data.type === "silence" && enableSilenceDetection) {
          onSilence?.();
        }
      };

      sourceNode.connect(workletNode);
      // 保证 Worklet 进入渲染循环
      workletNode.connect(audioContext.destination);

      await audioContext.resume();

      workletNode.port.postMessage({
        type: "start",
        inputSampleRate: audioContext.sampleRate,
        chunkSize,
        silenceThreshold,
        silenceHoldFrames,
      });
      active = true;
      seq = 0;
    },

    stop() {
      if (!active && !audioContext) return;
      active = false;
      try {
        workletNode?.port.postMessage({ type: "stop" });
      } catch {
        // ignore
      }
      try {
        sourceNode?.disconnect();
      } catch {
        // ignore
      }
      try {
        workletNode?.disconnect();
      } catch {
        // ignore
      }
      mediaStream?.getTracks().forEach((track) => track.stop());
      mediaStream = null;
      audioContext
        ?.close()
        .catch(() => {
          // ignore
        })
        .finally(() => {
          audioContext = null;
          sourceNode = null;
          workletNode = null;
        });
      if (moduleUrl) {
        URL.revokeObjectURL(moduleUrl);
        moduleUrl = null;
      }
    },

    isActive() {
      return active;
    },
  };
}

