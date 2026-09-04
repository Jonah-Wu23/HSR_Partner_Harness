import { isPlainObject, jsonToText } from "./mufyValues";

export interface RuntimeTriggerCardProps {
  trigger: unknown;
  onChange: (next: unknown) => void;
  readOnly?: boolean;
  testIdPrefix: string;
}

/**
 * runtime_trigger 保留字段（冻结契约 §6）：
 * - kind === "turn"：显示「第 N 回合触发」徽章，turn / once 可编辑，其余键原样保留；
 * - 其余值（time 等）：显示「存而不运行」，只读呈现原始 JSON，绝不改写成 turn。
 */
export function RuntimeTriggerCard({ trigger, onChange, readOnly = false, testIdPrefix }: RuntimeTriggerCardProps) {
  if (isPlainObject(trigger) && trigger.kind === "turn") {
    const turn =
      typeof trigger.turn === "number" && Number.isInteger(trigger.turn) && trigger.turn >= 1 ? trigger.turn : null;
    const onceChecked = trigger.once !== false;
    const inputTurn = turn !== null ? String(turn) : typeof trigger.turn === "number" ? String(trigger.turn) : "";

    return (
      <div className="mufy-trigger-card" data-testid={`${testIdPrefix}-card`}>
        <div className="mufy-trigger-head">
          <span className="mufy-trigger-badge" data-testid={`${testIdPrefix}-badge`}>
            {turn !== null ? `第 ${turn} 回合触发` : "回合触发（未声明有效回合数）"}
          </span>
          <span className="mufy-trigger-note">保留字段 runtime_trigger：命中回合时该条目会注入角色侧提示词。</span>
        </div>
        {!readOnly ? (
          <div className="mufy-trigger-editors">
            <label className="mufy-trigger-field">
              回合
              <input
                type="number"
                min={1}
                step={1}
                className="char-create-input mufy-input-num"
                value={inputTurn}
                onChange={(event) => {
                  const raw = event.target.value;
                  if (raw.trim() === "") return;
                  const parsed = Number(raw);
                  if (Number.isFinite(parsed)) onChange({ ...trigger, turn: parsed });
                }}
                data-testid={`${testIdPrefix}-turn`}
              />
            </label>
            <label className="mufy-trigger-field mufy-trigger-once">
              <input
                type="checkbox"
                checked={onceChecked}
                onChange={(event) => onChange({ ...trigger, once: event.target.checked })}
                data-testid={`${testIdPrefix}-once`}
              />
              仅该回合（once）
            </label>
          </div>
        ) : null}
        <p className="mufy-trigger-hint">once 开启时仅在该回合注入；关闭后从该回合起每回合注入。</p>
      </div>
    );
  }

  return (
    <div className="mufy-trigger-card mufy-trigger-dormant" data-testid={`${testIdPrefix}-card`}>
      <div className="mufy-trigger-head">
        <span className="mufy-trigger-badge mufy-trigger-badge-dormant" data-testid={`${testIdPrefix}-badge`}>
          存而不运行
        </span>
        <span className="mufy-trigger-note">
          runtime_trigger 不是回合声明（kind 缺失或非 turn），本版本不会执行它；数据原样保存。
        </span>
      </div>
      <pre className="char-create-json-view mufy-trigger-json" data-testid={`${testIdPrefix}-raw`}>
        {jsonToText(trigger)}
      </pre>
    </div>
  );
}
