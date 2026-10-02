import { useId } from "react";

/** 记忆内容的解析结果：协议只要求 content 是 JSON 对象。 */
export type MemoryContentParseResult =
  | { ok: true; content: Record<string, unknown> }
  | { ok: false; error: string };

/** 解析记忆内容文本；非法输入返回 JSON.parse 的错误信息。 */
export function parseMemoryContent(text: string): MemoryContentParseResult {
  const trimmed = text.trim();
  if (!trimmed) return { ok: false, error: "记忆内容不能为空" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (error) {
    return { ok: false, error: `内容不是合法 JSON：${(error as SyntaxError).message}` };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: "记忆内容必须是 JSON 对象，形如 {\"键\": \"值\"}" };
  }
  return { ok: true, content: parsed as Record<string, unknown> };
}

interface MemoryContentEditorProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  testId: string;
  ariaLabel: string;
}

/** 记忆内容编辑器：等宽文本框加实时结构校验，未填写时给中性提示。 */
export function MemoryContentEditor({
  value,
  onChange,
  disabled,
  testId,
  ariaLabel,
}: MemoryContentEditorProps) {
  const hintId = useId();
  const parsed = parseMemoryContent(value);
  const untouched = value.trim() === "";
  return (
    <div className="field">
      <textarea
        data-testid={testId}
        aria-label={ariaLabel}
        aria-describedby={hintId}
        rows={4}
        style={{ fontFamily: "monospace", fontSize: "12px" }}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      <p
        id={hintId}
        className={untouched || parsed.ok ? "field-note" : "field-error"}
        data-testid={`${testId}-status`}
        role={untouched || parsed.ok ? "status" : "alert"}
      >
        {untouched ? "请输入 JSON 对象内容" : parsed.ok ? "内容为合法 JSON 对象" : parsed.error}
      </p>
    </div>
  );
}
