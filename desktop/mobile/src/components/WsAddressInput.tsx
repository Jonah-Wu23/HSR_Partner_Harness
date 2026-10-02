import { useId, useState } from "react";
import { parseWsAddress } from "../lib/wsClient";
import "./WsAddressInput.css";

/**
 * Android 壳内的桌面端服务地址输入。壳没有浏览器地址栏，二维码的 ?ws= 不能随链接带入，
 * 扫码不可用时在这里手动输入。校验规则见 parseWsAddress，只检查格式，不探测连通性；
 * 失焦后才展示错误，避免打断输入。
 */

export interface WsAddressInputProps {
  /** 受控值：由配对页持有并决定何时保存。 */
  value: string;
  onChange: (value: string) => void;
}

export function WsAddressInput({ value, onChange }: WsAddressInputProps) {
  const inputId = `ws-address-${useId()}`;
  const errorId = `${inputId}-error`;
  const [touched, setTouched] = useState(false);
  const parsed = parseWsAddress(value);
  const error = parsed.ok ? null : parsed.error;
  const showError = touched && error !== null;

  return (
    <div className="ws-address-input">
      <label htmlFor={inputId} className="ws-address-label">
        桌面端服务地址
      </label>
      <input
        id={inputId}
        type="text"
        className="ws-address-field"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => setTouched(true)}
        placeholder="ws://192.168.1.50:8765/ws"
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
          {error}
        </p>
      ) : (
        <p className="hint" data-testid="ws-address-hint">
          与桌面端二维码中的 ?ws= 地址一致；扫码不可用时，可手动输入电脑的局域网地址。
        </p>
      )}
    </div>
  );
}
