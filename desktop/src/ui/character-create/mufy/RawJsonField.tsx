import { useEffect, useState } from "react";
import { jsonToText } from "./mufyValues";

export interface RawJsonFieldProps {
  value: unknown;
  onChange: (next: unknown) => void;
  readOnly?: boolean;
  testId?: string;
  ariaLabel?: string;
}

/**
 * 逐键 raw JSON 编辑兜底：解析失败时如实报错且不产生任何改动（Let It Fail）。
 */
export function RawJsonField({ value, onChange, readOnly = false, testId, ariaLabel }: RawJsonFieldProps) {
  const [draft, setDraft] = useState(() => jsonToText(value));
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) setDraft(jsonToText(value));
  }, [value, dirty]);

  const apply = () => {
    try {
      const parsed = JSON.parse(draft) as unknown;
      setError(null);
      setDirty(false);
      onChange(parsed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const revert = () => {
    setDraft(jsonToText(value));
    setDirty(false);
    setError(null);
  };

  return (
    <div className="mufy-raw">
      <textarea
        className="char-create-textarea mufy-raw-textarea"
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          setDirty(true);
        }}
        disabled={readOnly}
        spellCheck={false}
        aria-label={ariaLabel ?? "以 JSON 编辑"}
        data-testid={testId}
      />
      {error ? (
        <p className="mufy-raw-error" role="alert" data-testid={testId ? `${testId}-error` : undefined}>
          JSON 解析失败：{error}
        </p>
      ) : null}
      {!readOnly ? (
        <div className="mufy-raw-actions">
          <button
            type="button"
            className="char-btn char-btn-secondary mufy-btn-sm"
            onClick={apply}
            disabled={!dirty}
            data-testid={testId ? `${testId}-apply` : undefined}
          >
            应用 JSON
          </button>
          <button
            type="button"
            className="char-btn char-btn-ghost mufy-btn-sm"
            onClick={revert}
            disabled={!dirty}
            data-testid={testId ? `${testId}-revert` : undefined}
          >
            还原
          </button>
          {dirty ? <span className="mufy-raw-dirty-hint">修改仅在点击「应用 JSON」后生效</span> : null}
        </div>
      ) : null}
    </div>
  );
}
