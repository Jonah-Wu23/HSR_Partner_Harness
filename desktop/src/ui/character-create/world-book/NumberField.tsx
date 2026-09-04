import { useState } from "react";

export interface NumberFieldProps {
  /** 当前值；undefined/null 显示为空。 */
  value: unknown;
  /** 提交数字；留空提交 undefined（由父级删键回缺省）。无法解析的中间输入不提交。 */
  onValueChange: (next: number | undefined) => void;
  readOnly?: boolean;
  testId: string;
  ariaLabel: string;
  placeholder?: string;
}

export function NumberField({
  value,
  onValueChange,
  readOnly = false,
  testId,
  ariaLabel,
  placeholder,
}: NumberFieldProps) {
  const toText = (v: unknown) => (v == null || v === "" ? "" : String(v));
  const [text, setText] = useState(toText(value));
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) {
    setPrevValue(value);
    setText(toText(value));
  }

  const handleChange = (raw: string) => {
    setText(raw);
    const trimmed = raw.trim();
    if (trimmed === "") {
      onValueChange(undefined);
      return;
    }
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed)) onValueChange(parsed);
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      className="char-create-input wb-input-num"
      value={text}
      placeholder={placeholder}
      disabled={readOnly}
      aria-label={ariaLabel}
      onChange={(event) => handleChange(event.target.value)}
      data-testid={testId}
    />
  );
}
