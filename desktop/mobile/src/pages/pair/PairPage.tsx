import { useEffect, useRef, useState } from "react";
import {
  RemoteCommandError,
  getStoredDeviceName,
  getStoredWsUrl,
  parseWsAddress,
  saveWsUrl,
} from "../../lib/wsClient";
import { useMobileStore } from "../../lib/mobileStore";
import { useShellEnvironment } from "../../lib/shellCapabilities";
import { WsAddressInput } from "../../components/WsAddressInput";
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

interface PairingPayload {
  code: string;
  /** 二维码带的桌面端服务地址（已规范化）；裸配对码时为 null。 */
  wsUrl: string | null;
}

/**
 * 解析二维码内容。桌面端二维码是带 ?code= 的接入地址，服务地址取 ?ws= 参数，
 * 没有 ?ws= 时（如公网隧道地址）由页面地址本身推出；不是 URL 的内容按裸配对码处理。
 */
function parsePairingPayload(raw: string): PairingPayload {
  const trimmed = raw.trim();
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return { code: trimmed, wsUrl: null };
  }
  const code = url.searchParams.get("code")?.trim();
  if (!code) throw new Error(`二维码地址里没有配对码：${trimmed}`);
  const address = parseWsAddress(url.searchParams.get("ws") ?? trimmed);
  if (!address.ok) throw new Error(`二维码里的桌面端地址无效：${address.error ?? trimmed}`);
  return { code, wsUrl: address.url };
}

const PAIRING_ERROR_COPY: Record<string, { message: string; hint: string }> = {
  pairing_invalid_code: {
    message: "配对码无效或已被新码作废",
    hint: "请在电脑桌面端查看当前有效的 6 位配对码或重新生成。",
  },
  pairing_expired_code: {
    message: "配对码已过期，请在电脑端重新生成",
    hint: "配对码有效时长有限，请在电脑端重新生成新配对码后再试。",
  },
  pairing_code_exhausted: {
    message: "配对码输错次数过多，已作废",
    hint: "请在电脑桌面端「设置 → 远程设备」重新生成配对码后再试。",
  },
};

export function PairPage() {
  const pair = useMobileStore((state) => state.pairDevice);

  // 地址栏 ?code= 预填配对码
  const [code, setCode] = useState(
    () => new URLSearchParams(window.location.search).get("code") ?? "",
  );
  const [deviceName, setDeviceName] = useState(() => getStoredDeviceName() ?? "我的手机");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorInfo, setErrorInfo] = useState<{ code?: string; message: string } | null>(null);

  const isTokenExpired = useMobileStore((state) => state.authFailureReason === "expired_token");

  // Android 壳没有浏览器地址栏，二维码的 ?ws= 无法随链接带入，因此壳内提供服务地址输入。
  // 壳判定用订阅式 hook：壳注入的全局对象可能晚于首帧渲染就位。
  const inAndroidShell = useShellEnvironment() === "android_shell";
  const [wsAddress, setWsAddress] = useState(() => getStoredWsUrl() ?? "");
  const [wsAddressSaved, setWsAddressSaved] = useState(false);
  const parsedAddress = parseWsAddress(wsAddress);

  const handleSaveAddress = () => {
    if (!parsedAddress.ok) return;
    saveWsUrl(parsedAddress.url);
    setWsAddressSaved(true);
    // 立即用新地址重连，连接结果由顶部 ConnectionBanner 展示。
    useMobileStore.getState().reconnect();
  };

  // 扫码相关状态
  const isBarcodeSupported = window.BarcodeDetector !== undefined;
  const [isScanning, setIsScanning] = useState(false);
  const [scannerError, setScannerError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanIntervalRef = useRef<number | null>(null);

  const stopScanning = () => {
    if (scanIntervalRef.current !== null) {
      window.clearInterval(scanIntervalRef.current);
      scanIntervalRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setIsScanning(false);
  };

  /** 扫码失败：停掉摄像头，保留扫码卡片展示错误原文。 */
  const failScanning = (err: unknown) => {
    console.error("扫码失败", err);
    stopScanning();
    setScannerError(err instanceof Error ? err.message : String(err));
    setIsScanning(true);
  };

  useEffect(() => stopScanning, []);

  const applyScannedPayload = (raw: string) => {
    const parsed = parsePairingPayload(raw);
    setCode(parsed.code);
    if (parsed.wsUrl) {
      // 二维码带服务地址：保存并带入壳内地址框，立即用新地址重连。
      saveWsUrl(parsed.wsUrl);
      setWsAddress(parsed.wsUrl);
      setWsAddressSaved(false);
      useMobileStore.getState().reconnect();
    }
    stopScanning();
  };

  const startScanning = async () => {
    const Detector = window.BarcodeDetector;
    if (!Detector) return;
    setScannerError(null);
    setIsScanning(true);
    try {
      if (!navigator.mediaDevices) throw new Error("当前环境不支持摄像头访问");
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      const detector = new Detector({ formats: ["qr_code"] });
      scanIntervalRef.current = window.setInterval(() => {
        if (!videoRef.current) return;
        detector
          .detect(videoRef.current)
          .then((barcodes) => {
            // 视频尚无画面时 detect 返回空列表，等下一帧。
            if (barcodes.length > 0) applyScannedPayload(barcodes[0].rawValue);
          })
          .catch(failScanning);
      }, 100);
    } catch (err: unknown) {
      failScanning(err);
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

  const knownError = errorInfo?.code ? PAIRING_ERROR_COPY[errorInfo.code] : undefined;
  const errorMessage =
    knownError?.message ??
    (errorInfo?.code ? `[${errorInfo.code}] ${errorInfo.message}` : (errorInfo?.message ?? ""));
  const errorHint = knownError?.hint ?? "请核对配对码或检查桌面端是否在线，并重新尝试。";

  return (
    <main className="page" data-testid="pair-page">
      <div className="pair-container">
        <header className="pair-header">
          <h1 className="page-title">配对桌面端</h1>
          <p className="hint">
            在电脑桌面端「设置 → 远程设备」查看配对码或二维码，输入后即可连接。
          </p>
        </header>

        {isTokenExpired && (
          <section className="card field-error-card" role="alert" data-testid="expired-token-alert">
            <div className="error-title">登录令牌已过期</div>
            <div className="error-message">
              登录令牌已过期（最长30天或7天未使用），请重新配对。
            </div>
            <div className="error-hint">请在电脑桌面端「设置 → 远程设备」重新扫码或输入新配对码。</div>
          </section>
        )}

        {/* 浏览器提供 BarcodeDetector 时才有扫码入口 */}
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
                    扫码失败：{scannerError}
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

        {/* 桌面端地址输入只在 Android 壳内渲染 */}
        {inAndroidShell ? (
          <section className="card ws-address-card" data-testid="ws-address-section">
            <h2 className="scan-title">桌面端连接地址</h2>
            <p className="hint">
              扫码填入会自动带上服务地址；若扫码不可用或地址未带入，请在此输入电脑端
              「设置 → 远程设备」显示的服务地址（形如 ws://192.168.1.50:8765/ws）。
            </p>
            <WsAddressInput
              value={wsAddress}
              onChange={(value) => {
                setWsAddress(value);
                setWsAddressSaved(false);
              }}
            />
            <button
              type="button"
              className="primary ws-address-save-btn"
              onClick={handleSaveAddress}
              disabled={!parsedAddress.ok}
              data-testid="btn-save-ws-address"
            >
              保存并重连
            </button>
            {wsAddressSaved ? (
              <p className="hint" data-testid="ws-address-saved">
                地址已保存，正在用新地址连接桌面端。
              </p>
            ) : null}
          </section>
        ) : null}

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
              <div className="error-message" data-testid="pair-error-message">
                {errorMessage}
              </div>
              <div className="error-hint">{errorHint}</div>
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
