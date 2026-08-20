import { useEffect, useRef, useState } from "react";
import { RemoteCommandError, getStoredDeviceName } from "../../lib/wsClient";
import { useMobileStore } from "../../lib/mobileStore";
import "./PairPage.css";

interface BarcodeDetectorInstance {
  detect: (source: HTMLVideoElement | ImageBitmapSource) => Promise<Array<{ rawValue: string }>>;
}

interface BarcodeDetectorConstructor {
  new (options?: { formats: string[] }): BarcodeDetectorInstance;
  getSupportedFormats?: () => Promise<string[]>;
}

declare global {
  interface Window {
    BarcodeDetector?: BarcodeDetectorConstructor;
  }
}

function extractPairCode(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";

  // 尝试解析为 URL（桌面端二维码常见格式：http://ip:port/?ws=...&code=123456）
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://") || trimmed.includes("?")) {
    try {
      const url = new URL(trimmed, typeof window !== "undefined" ? window.location.href : "http://localhost");
      const wsParam = url.searchParams.get("ws");
      const codeParam = url.searchParams.get("code");
      if (wsParam && typeof window !== "undefined") {
        window.localStorage.setItem("phm.wsUrl", wsParam);
      }
      if (codeParam) return codeParam.trim();
    } catch {
      // 忽略 URL 解析异常
    }
  }

  // 尝试解析为 JSON
  if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
    try {
      const obj = JSON.parse(trimmed) as Record<string, unknown>;
      if (typeof obj.ws === "string" && typeof window !== "undefined") {
        window.localStorage.setItem("phm.wsUrl", obj.ws);
      }
      if (typeof obj.code === "string") return obj.code.trim();
    } catch {
      // 忽略 JSON 解析异常
    }
  }

  return trimmed;
}

export function PairPage() {
  const pair = useMobileStore((state) => state.pair);

  // 从 URL 查询参数 ?code= 预填配对码
  const [code, setCode] = useState(() => {
    if (typeof window === "undefined") return "";
    const params = new URLSearchParams(window.location.search);
    return params.get("code") || "";
  });

  const [deviceName, setDeviceName] = useState(() => {
    return getStoredDeviceName() || "我的手机";
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorInfo, setErrorInfo] = useState<{ code?: string; message: string } | null>(null);

  // 扫码相关状态
  const isBarcodeSupported = typeof window !== "undefined" && typeof window.BarcodeDetector !== "undefined";
  const [isScanning, setIsScanning] = useState(false);
  const [scannerError, setScannerError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanIntervalRef = useRef<number | null>(null);

  const stopScanning = () => {
    if (scanIntervalRef.current !== null && typeof window !== "undefined") {
      window.clearInterval(scanIntervalRef.current);
      scanIntervalRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    setIsScanning(false);
  };

  useEffect(() => {
    return () => {
      stopScanning();
    };
  }, []);

  const startScanning = async () => {
    if (!isBarcodeSupported) return;
    setScannerError(null);
    setIsScanning(true);

    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("当前环境不支持摄像头访问");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        try {
          const playPromise = videoRef.current.play?.();
          if (playPromise && typeof playPromise.catch === "function") {
            await playPromise.catch(() => {});
          }
        } catch {
          // 忽略在无 UI 或受限环境下的播放异常
        }
      }

      const DetectorClass = window.BarcodeDetector!;
      const detector = new DetectorClass({ formats: ["qr_code"] });

      scanIntervalRef.current = window.setInterval(async () => {
        if (!videoRef.current) return;
        try {
          const barcodes = await detector.detect(videoRef.current);
          if (barcodes && barcodes.length > 0) {
            const detected = barcodes[0].rawValue;
            const parsedCode = extractPairCode(detected);
            if (parsedCode) {
              setCode(parsedCode);
              stopScanning();
            }
          }
        } catch {
          // 单帧探测异常忽略，等待下一帧
        }
      }, 100);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setScannerError(msg);
      stopScanning();
      setIsScanning(true); // 保留扫码卡片展示错误
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedCode = code.trim();
    const trimmedDevice = deviceName.trim();
    if (!trimmedCode || !trimmedDevice || isSubmitting) return;

    setIsSubmitting(true);
    setErrorInfo(null);

    try {
      await pair(trimmedCode, trimmedDevice);
    } catch (err: unknown) {
      if (err instanceof RemoteCommandError) {
        setErrorInfo({ code: err.code, message: err.message });
      } else if (err instanceof Error) {
        setErrorInfo({ message: err.message });
      } else {
        setErrorInfo({ message: String(err) });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="page" data-testid="pair-page">
      <div className="pair-container">
        <header className="pair-header">
          <h1 className="page-title">配对桌面端</h1>
          <p className="hint">
            在电脑桌面端「设置 → 远程设备」查看配对码或二维码，输入后即可连接。
          </p>
        </header>

        {/* 扫码区域：支持 BarcodeDetector 才提供扫码入口，不支持则如实说明 */}
        <section className="scan-card" data-testid="scan-section">
          <h2 className="scan-title">扫码填入</h2>
          {isBarcodeSupported ? (
            !isScanning ? (
              <button
                type="button"
                className="scan-btn"
                onClick={startScanning}
                data-testid="btn-start-scan"
              >
                扫码填入配对码
              </button>
            ) : (
              <div className="scanner-viewfinder" data-testid="scanner-viewfinder">
                <video
                  ref={videoRef}
                  className="scanner-video"
                  autoPlay
                  playsInline
                  muted
                  data-testid="scanner-video"
                />
                {scannerError && (
                  <p className="field-error" data-testid="scanner-error">
                    摄像头启动失败：{scannerError}
                  </p>
                )}
                <button
                  type="button"
                  className="scanner-cancel-btn"
                  onClick={stopScanning}
                  data-testid="btn-cancel-scan"
                >
                  取消扫码
                </button>
              </div>
            )
          ) : (
            <p className="hint" data-testid="scan-unsupported-hint">
              当前浏览器不支持原生扫码，请使用下方手动输入配对码。
            </p>
          )}
        </section>

        {/* 手动输入表单 */}
        <form className="pair-form" onSubmit={handleSubmit} data-testid="pair-form">
          <div className="form-group">
            <label htmlFor="pair-code-input" className="form-label">
              配对码 (6 位)
            </label>
            <input
              id="pair-code-input"
              type="text"
              className="form-input code-input"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="如 123456"
              maxLength={12}
              required
              data-testid="input-pair-code"
              autoComplete="off"
            />
          </div>

          <div className="form-group">
            <label htmlFor="device-name-input" className="form-label">
              本设备名称
            </label>
            <input
              id="device-name-input"
              type="text"
              className="form-input"
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              placeholder="如 我的手机"
              required
              data-testid="input-device-name"
            />
          </div>

          {errorInfo && (
            <div className="card field-error-card" role="alert" data-testid="pair-error">
              <div className="error-title">配对失败</div>
              <div className="error-message">
                {errorInfo.code ? `[${errorInfo.code}] ${errorInfo.message}` : errorInfo.message}
              </div>
              <div className="error-hint">请核对配对码或检查桌面端是否在线，并重新尝试。</div>
            </div>
          )}

          <button
            type="submit"
            className="primary pair-submit-btn"
            disabled={isSubmitting || !code.trim() || !deviceName.trim()}
            data-testid="btn-submit-pair"
          >
            {isSubmitting ? "正在配对…" : "开始配对"}
          </button>
        </form>
      </div>
    </main>
  );
}
