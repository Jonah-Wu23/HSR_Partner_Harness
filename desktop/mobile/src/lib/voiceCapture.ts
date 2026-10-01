/**
 * 手机端语音采集引擎。
 *
 * 协议：getUserMedia → 16kHz AudioContext（浏览器负责重采样与抗混叠）+ AudioWorklet
 * 量化为 s16le mono PCM → base64 → 按约 160 ms 分片经 WS 上行（voice.mobile_audio_chunk）。
 *
 * 自动检测模式在 Worklet 内做 RMS 静音检测：检测到说话之后才开始计静音，
 * 连续静音达到阈值后回调主线程停止。停止时先把尾部不足一片的样本发出，
 * 等全部分片上行完成再返回，调用方随后才发 voice.mobile_ptt_stop。
 */

const TARGET_SAMPLE_RATE = 16000;
const DEFAULT_CHUNK_DURATION_MS = 160;
const DEFAULT_SILENCE_THRESHOLD_DB = -45;
const DEFAULT_SILENCE_HOLD_MS = 1200;
/** AudioWorkletProcessor.process 每次处理的渲染量子帧数（Web Audio 规范固定值）。 */
const RENDER_QUANTUM_FRAMES = 128;
/** 停止时等待 Worklet 交回尾部样本的上限。 */
const FLUSH_TIMEOUT_MS = 1000;

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
    this.chunkSize = 2560;
    this.silenceThreshold = 0.0056;
    this.silenceHoldFrames = 0;
    this.silenceCounter = 0;
    this.speechStarted = false;
    this.port.onmessage = (event) => {
      const data = event.data;
      if (data.type === "start") {
        this.active = true;
        this.chunkSize = data.chunkSize;
        this.silenceThreshold = data.silenceThreshold;
        this.silenceHoldFrames = data.silenceHoldFrames;
        this.buffer = [];
        this.silenceCounter = 0;
        this.speechStarted = false;
      } else if (data.type === "stop") {
        this.active = false;
        this.buffer = [];
      } else if (data.type === "flush") {
        this.active = false;
        if (this.buffer.length > 0) this.postChunk(this.buffer);
        this.buffer = [];
        this.port.postMessage({ type: "flushed" });
      }
    };
  }

  postChunk(samples) {
    const int16 = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      const v = Math.max(-1, Math.min(1, samples[i]));
      int16[i] = Math.round(v * 32767);
    }
    this.port.postMessage({ type: "chunk", samples: int16.buffer }, [int16.buffer]);
  }

  process(inputs) {
    if (!this.active) return true;
    const input = inputs[0] && inputs[0][0];
    if (!input || input.length === 0) return true;

    for (let i = 0; i < input.length; i++) this.buffer.push(input[i]);

    let energy = 0;
    for (let i = 0; i < input.length; i++) {
      energy += input[i] * input[i];
    }
    const rms = Math.sqrt(energy / input.length);
    if (rms >= this.silenceThreshold) {
      this.speechStarted = true;
      this.silenceCounter = 0;
    } else if (this.speechStarted) {
      this.silenceCounter++;
      if (this.silenceCounter >= this.silenceHoldFrames) {
        this.port.postMessage({ type: "silence" });
        this.silenceCounter = 0;
      }
    }

    while (this.buffer.length >= this.chunkSize) {
      this.postChunk(this.buffer.slice(0, this.chunkSize));
      this.buffer = this.buffer.slice(this.chunkSize);
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
  /** 接管 stream：启动失败时引擎自行停掉麦克风轨道再抛出。 */
  start(stream: MediaStream): Promise<void>;
  /** 交出尾部样本、等全部分片上行完成，再释放麦克风与音频上下文。 */
  stop(): Promise<void>;
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
  let moduleUrl: string | null = null;
  let seq = 0;
  let active = false;
  /** 首个分片上行失败后不再产出新分片，错误只经 onError 报告一次。 */
  let failed = false;
  let onFlushed: (() => void) | null = null;
  let stopping: Promise<void> | null = null;
  const inFlight = new Set<Promise<void>>();

  const chunkSize = Math.round((TARGET_SAMPLE_RATE * chunkDurationMs) / 1000);
  const silenceThreshold = dbToLinear(silenceThresholdDb);

  const sendChunk = (samples: ArrayBuffer): void => {
    if (failed) return;
    const currentSeq = seq;
    seq += 1;
    const sending = (async () => {
      try {
        await onChunk(currentSeq, int16ArrayToBase64(new Int16Array(samples)));
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        if (failed) {
          console.error("语音分片上行失败", currentSeq, error);
          return;
        }
        failed = true;
        workletNode?.port.postMessage({ type: "stop" });
        onError(error);
      }
    })();
    inFlight.add(sending);
    void sending.finally(() => inFlight.delete(sending));
  };

  /** 请 Worklet 交出尾部不足一片的样本；它回 flushed 之前的分片都已进入 inFlight。 */
  const flushWorklet = (node: AudioWorkletNode): Promise<void> =>
    new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        onFlushed = null;
        reject(new Error(`语音采集收尾超时（${FLUSH_TIMEOUT_MS}ms 内未收到尾部样本）`));
      }, FLUSH_TIMEOUT_MS);
      onFlushed = () => {
        clearTimeout(timer);
        onFlushed = null;
        resolve();
      };
      node.port.postMessage({ type: "flush" });
    });

  const release = (): void => {
    active = false;
    if (workletNode) {
      workletNode.port.onmessage = null;
      workletNode.disconnect();
    }
    sourceNode?.disconnect();
    mediaStream?.getTracks().forEach((track) => track.stop());
    const context = audioContext;
    const url = moduleUrl;
    audioContext = null;
    sourceNode = null;
    workletNode = null;
    mediaStream = null;
    moduleUrl = null;
    context?.close().catch((error: unknown) => {
      console.error("关闭语音采集音频上下文失败", error);
    });
    if (url) URL.revokeObjectURL(url);
  };

  return {
    async start(stream) {
      if (active) return;
      mediaStream = stream;
      try {
        if (typeof AudioContext === "undefined") {
          throw new Error("当前环境不支持 AudioContext");
        }
        // 上下文直接跑在 16kHz：重采样与抗混叠滤波交给浏览器。
        audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
        if (!audioContext.audioWorklet) {
          throw new Error("当前浏览器不支持 AudioWorklet");
        }

        const blob = new Blob([CAPTURE_PROCESSOR_CODE], { type: "application/javascript" });
        moduleUrl = URL.createObjectURL(blob);
        await audioContext.audioWorklet.addModule(moduleUrl);

        sourceNode = audioContext.createMediaStreamSource(stream);
        workletNode = new AudioWorkletNode(audioContext, "voice-capture-processor");
        workletNode.port.onmessage = (event) => {
          const data = event.data as { type?: string; samples?: ArrayBuffer };
          if (data.type === "chunk" && data.samples) {
            sendChunk(data.samples);
          } else if (data.type === "flushed") {
            onFlushed?.();
          } else if (data.type === "silence" && enableSilenceDetection) {
            onSilence?.();
          }
        };

        sourceNode.connect(workletNode);
        // 接到 destination 才会进入渲染循环；Worklet 不产生输出，扬声器无声。
        workletNode.connect(audioContext.destination);

        await audioContext.resume();

        seq = 0;
        failed = false;
        workletNode.port.postMessage({
          type: "start",
          chunkSize,
          silenceThreshold,
          silenceHoldFrames: Math.ceil(
            (silenceHoldMs * audioContext.sampleRate) / 1000 / RENDER_QUANTUM_FRAMES,
          ),
        });
        active = true;
      } catch (error) {
        release();
        throw error;
      }
    },

    stop() {
      if (stopping) return stopping;
      stopping = (async () => {
        const node = workletNode;
        let flushError: unknown = null;
        if (active && !failed && node) {
          try {
            await flushWorklet(node);
          } catch (error) {
            flushError = error;
          }
        }
        await Promise.all(inFlight);
        release();
        if (flushError) throw flushError;
      })();
      return stopping;
    },

    isActive() {
      return active;
    },
  };
}

