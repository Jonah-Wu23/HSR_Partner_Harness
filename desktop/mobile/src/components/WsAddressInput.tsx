import { useEffect, useId, useRef, useState } from "react";
import "./WsAddressInput.css";

/**
 * V0.3.7 壳内 WS 地址输入（V7 前置组件，冻结 §9.1）。
 *
 * Android 壳没有 PWA 的站点 URL 机制，`?ws=` 二维码参数不可用时需要手动输入桌面端
 * 服务地址；该输入建立在配对页现有 `phm.wsUrl` localStorage 机制之上（resolveWsUrl
 * 的 localStorage 分支读取同一键），由接线阶段把合法结果写入 `phm.wsUrl`。
 *
 * 校验只做协议格式判定，不做连通性猜测：
 * - 必须是 ws:// 或 wss:// 绝对地址（与桌面端二维码中的 ?ws= 值一致，如
 *   ws://192.168.1.50:8765/ws）；
 * - 路径需以 /ws 结尾（Sidecar 远程服务的 WebSocket 入口，见 ws_server.py 的
 *   `app.router.add_get("/ws", ...)`）；
 * - 空输入 valid=false 且不算错误文案（是否允许空值由接线方决定）。
 */

export interface WsAddressValidation {
  valid: boolean;
  /** 失败文案；空输入时为 null（不计为错误，但 valid 仍为 false）。 */
  error: string | null;
}

export function validateWsAddress(raw: string): WsAddressValidation {
  const value = raw.trim();
  if (value.length === 0) {
    return { valid: false, error: null };
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return {
      valid: false,
      error: "地址不完整，请输入形如 ws://192.168.1.50:8765/ws 的完整地址",
    };
  }
  if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    return {
      valid: false,
      error: "地址需以 ws:// 或 wss:// 开头（与桌面端二维码中的 ?ws= 地址一致）",
    };
  }
  if (!url.hostname) {
    return {
      valid: false,
      error: "地址缺少主机名，请填入电脑的局域网 IP 或主机名",
    };
  }
  if (!url.pathname.endsWith("/ws")) {
    return {
      valid: false,
      error: "地址路径需以 /ws 结尾（桌面端远程服务的入口），例如 ws://192.168.1.50:8765/ws",
    };
  }
  return { valid: true, error: null };
}

export interface WsAddressInputProps {
  /** 受控值：由接线方持有并决定何时写入 phm.wsUrl。 */
  value: string;
  onChange: (value: string) => void;
  /** 校验状态回传：空输入与非法输入均为 false，接线方据此控制「保存/连接」按钮。 */
  onValidityChange?: (valid: boolean) => void;
  id?: string;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  autoFocus?: boolean;
}

export function WsAddressInput({
  value,
  onChange,
  onValidityChange,
  id,
  label = "桌面端服务地址",
  placeholder = "ws://192.168.1.50:8765/ws",
  disabled = false,
  autoFocus = false,
}: WsAddressInputProps) {
  const autoId = useId();
  const inputId = id ?? `ws-address-${autoId}`;
  const errorId = `${inputId}-error`;
  const [touched, setTouched] = useState(false);
  const validation = validateWsAddress(value);
  const showError = touched && validation.error !== null;

  const onValidityChangeRef = useRef(onValidityChange);
  useEffect(() => {
    onValidityChangeRef.current = onValidityChange;
  });
  useEffect(() => {
    onValidityChangeRef.current?.(validation.valid);
  }, [validation.valid]);

  return (
    <div className="ws-address-input">
      <label htmlFor={inputId} className="ws-address-label">
        {label}
      </label>
      <input
        id={inputId}
        type="text"
        className="ws-address-field"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => setTouched(true)}
        disabled={disabled}
        placeholder={placeholder}
        autoFocus={autoFocus}
        inputMode="url"
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="go"
        aria-invalid={showError || undefined}
        aria-describedby={showError ? errorId : undefined}
        data-testid="ws-address-input"
      />
      {showError ? (
        <p
          className="field-error"
          id={errorId}
          role="alert"
          data-testid="ws-address-error"
        >
          {validation.error}
        </p>
      ) : (
        <p className="hint" data-testid="ws-address-hint">
          与桌面端二维码中的 ?ws= 地址一致；扫码不可用时，可手动输入电脑的局域网地址。
        </p>
      )}
    </div>
  );
}
