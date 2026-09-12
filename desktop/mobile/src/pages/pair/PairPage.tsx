import { useEffect, useRef, useState } from "react";
import { RemoteCommandError, getStoredDeviceName, normalizeWsUrl } from "../../lib/wsClient";
import { useMobileStore } from "../../lib/mobileStore";
import { useShellEnvironment } from "../../lib/shellCapabilities";
import { WsAddressInput, validateWsAddress } from "../../components/WsAddressInput";
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

  // 尝试解析为 URL（桌面端二维码常见格式：https://.../?ws=...&code=123456 或 https://xxx.trycloudflare.com/?code=123456）
  if (
    trimmed.startsWith("http://") ||
    trimmed.startsWith("https://") ||
    trimmed.startsWith("ws://") ||
    trimmed.startsWith("wss://") ||
    trimmed.includes("?")
  ) {
    try {
      const url = new URL(trimmed, typeof window !== "undefined" ? window.location.href : "http://localhost");
      const wsParam = url.searchParams.get("ws");
      const codeParam = url.searchParams.get("code");
      if (wsParam && typeof window !== "undefined") {
        window.localStorage.setItem("phm.wsUrl", normalizeWsUrl(wsParam));
      } else if (
        trimmed.startsWith("http://") ||
        trimmed.startsWith("https://") ||
        trimmed.startsWith("ws://") ||
        trimmed.startsWith("wss://")
      ) {
        if (typeof window !== "undefined") {
          window.localStorage.setItem("phm.wsUrl", normalizeWsUrl(trimmed));
        }
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
        window.localStorage.setItem("phm.wsUrl", normalizeWsUrl(obj.ws));
      }
      if (typeof obj.code === "string") return obj.code.trim();
    } catch {
      // 忽略 JSON 解析异常
    }
  }

  return trimmed;
}

export function PairPage() {
  const pair = useMobileStore((state) => state.pairDevice);

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

  const authFailureCode = useMobileStore((state) => state.authFailureCode);
  const isTokenExpired = authFailureCode === "expired_token" || authFailureCode === "token_expired";

  const [lockoutCountdown, setLockoutCountdown] = useState<number>(0);
  const countdownTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (lockoutCountdown <= 0) {
      if (countdownTimerRef.current !== null && typeof window !== "undefined") {
        window.clearInterval(countdownTimerRef.current);
        countdownTimerRef.current = null;
      }
      return;
    }

    countdownTimerRef.current = window.setInterval(() => {
      setLockoutCountdown((prev) => {
        if (prev <= 1) {
          if (countdownTimerRef.current !== null && typeof window !== "undefined") {
            window.clearInterval(countdownTimerRef.current);
            countdownTimerRef.current = null;
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (countdownTimerRef.current !== null && typeof window !== "undefined") {
        window.clearInterval(countdownTimerRef.current);
        countdownTimerRef.current = null;
      }
    };
  }, [lockoutCountdown > 0]);

  // V0.3.7 Android 壳内的桌面端服务地址输入（冻结 §9.1）：壳没有浏览器地址栏，
  // 二维码 ?ws= 无法随链接带入。输入建立在既有 phm.wsUrl localStorage 机制之上
  // （resolveWsUrl 与扫码 extractPairCode 写入同一键），PWA 下不渲染本区、体验不变。
  // 判定必须订阅式：壳 internals 注入与首帧 render 存在竞态（真机实证），一次性
  // 求值会在注入未就位时把壳误判为 PWA 且不再恢复。
  const inAndroidShell = useShellEnvironment() === "android_shell";
  const [wsAddress, setWsAddress] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem("phm.wsUrl") ?? "";
  });
  const [wsAddressSaved, setWsAddressSaved] = useState(false);
  const wsAddressValid = validateWsAddress(wsAddress).valid;

  const handleSaveAddress = () => {
    const trimmed = wsAddress.trim();
    if (!validateWsAddress(trimmed).valid) return;
    const normalized = normalizeWsUrl(trimmed);
    window.localStorage.setItem("phm.wsUrl", normalized);
    setWsAddressSaved(true);
    // 立即用新地址重连：连不上会由顶部 ConnectionBanner 如实显示，不伪造成功。
    useMobileStore.getState().reconnect();
  };

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
    if (!trimmedCode || !trimmedDevice || isSubmitting || lockoutCountdown > 0) return;

    setIsSubmitting(true);
    setErrorInfo(null);

    try {
      await pair(trimmedCode, trimmedDevice);
    } catch (err: unknown) {
      if (err instanceof RemoteCommandError) {
        setErrorInfo({ code: err.code, message: err.message });
        if (err.code === "pairing_rate_limited" || err.code === "rate_limited") {
          const retryAfter =
            typeof err.details?.retry_after_s === "number" && err.details.retry_after_s > 0
              ? Math.round(err.details.retry_after_s)
              : 60;
          setLockoutCountdown(retryAfter);
        }
      } else if (err instanceof Error) {
        setErrorInfo({ message: err.message });
      } else {
        setErrorInfo({ message: String(err) });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  let errorMessage = errorInfo?.message ?? "";
  let errorHint = "请核对配对码或检查桌面端是否在线，并重新尝试。";

  if (errorInfo?.code === "pairing_invalid_code" || errorInfo?.code === "invalid_code") {
    errorMessage = "配对码无效或已被新码作废";
    errorHint = "请在电脑桌面端查看当前有效的 6 位配对码或重新生成。";
  } else if (errorInfo?.code === "pairing_expired_code" || errorInfo?.code === "expired_code") {
    errorMessage = "配对码已过期，请在电脑端重新生成";
    errorHint = "配对码有效时长有限，请在电脑端重新生成新配对码后再试。";
  } else if (
    errorInfo?.code === "pairing_rate_limited" ||
    errorInfo?.code === "rate_limited" ||
    lockoutCountdown > 0
  ) {
    errorMessage =
      lockoutCountdown > 0
        ? `请求过于频繁已被限流封锁，请在 ${lockoutCountdown} 秒后重试`
        : "限流封锁已解除，可重新尝试配对";
    errorHint =
      lockoutCountdown > 0
        ? `连续尝试失败次数过多，来源已被封锁，倒计时剩余 ${lockoutCountdown} 秒。`
        : "封锁期已结束，请确认配对码无误后重新提交。";
  } else if (errorInfo?.code) {
    errorMessage = `[${errorInfo.code}] ${errorInfo.message}`;
  }

  return (
    <main className="page" data-testid="pair-page">
      <div className="pair-container">
        <header className="pair-header">
          <h1 className="page-title">配对桌面端</h1>
          <p className="hint">
            在电脑桌面端「设置 → 远程设备」查看配对码或二维码，输入后即可连接。
          </p>
        </header>

        {/* D5: 令牌过期引导重新扫码配对 */}
        {isTokenExpired && (
          <section className="card field-error-card" role="alert" data-testid="expired-token-alert">
            <div className="error-title">登录令牌已过期</div>
            <div className="error-message">
              登录令牌已过期（最长30天或7天未使用），请重新配对。
            </div>
            <div className="error-hint">请在电脑桌面端「设置 → 远程设备」重新扫码或输入新配对码。</div>
          </section>
        )}

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

        {/* V0.3.7 壳内桌面端地址输入：仅 Android 壳渲染；PWA 保持既有扫码/手动配对流程 */}
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
              disabled={!wsAddressValid}
              data-testid="btn-save-ws-address"
            >
              保存并重连
            </button>
            {wsAddressSaved ? (
              <p className="hint" data-testid="ws-address-saved">
                地址已保存，正在用新地址连接桌面端；若连接失败，顶部横幅会如实提示。
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
            disabled={isSubmitting || !code.trim() || !deviceName.trim() || lockoutCountdown > 0}
            data-testid="btn-submit-pair"
          >
            {lockoutCountdown > 0
              ? `限流等待中 (${lockoutCountdown}s)`
              : isSubmitting
              ? "正在配对…"
              : "开始配对"}
          </button>
        </form>
      </div>
    </main>
  );
}
