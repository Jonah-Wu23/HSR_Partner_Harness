import { PlusIcon } from "../icons";

export interface StringListEditorProps {
  items: string[];
  onChange: (next: string[]) => void;
  readOnly?: boolean;
  testIdPrefix: string;
  ariaLabel: string;
}

export function StringListEditor({ items, onChange, readOnly = false, testIdPrefix, ariaLabel }: StringListEditorProps) {
  const updateAt = (index: number, text: string) => {
    const next = [...items];
    next[index] = text;
    onChange(next);
  };

  const removeAt = (index: number) => {
    onChange(items.filter((_, i) => i !== index));
  };

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    const moved = next[index];
    next[index] = next[target];
    next[target] = moved;
    onChange(next);
  };

  return (
    <div className="mufy-list">
      {items.map((item, index) => (
        <div className="mufy-list-row" key={index}>
          <input
            className="char-create-input"
            value={item}
            onChange={(event) => updateAt(index, event.target.value)}
            disabled={readOnly}
            aria-label={`${ariaLabel} 第 ${index + 1} 项`}
            data-testid={`${testIdPrefix}-${index}`}
          />
          {!readOnly ? (
            <div className="mufy-row-actions">
              <button
                type="button"
                className="char-btn char-btn-ghost mufy-btn-xs"
                onClick={() => move(index, -1)}
                disabled={index === 0}
                aria-label="上移"
                data-testid={`${testIdPrefix}-${index}-up`}
              >
                ↑
              </button>
              <button
                type="button"
                className="char-btn char-btn-ghost mufy-btn-xs"
                onClick={() => move(index, 1)}
                disabled={index === items.length - 1}
                aria-label="下移"
                data-testid={`${testIdPrefix}-${index}-down`}
              >
                ↓
              </button>
              <button
                type="button"
                className="char-btn char-btn-ghost mufy-btn-xs mufy-danger"
                onClick={() => removeAt(index)}
                aria-label="删除"
                data-testid={`${testIdPrefix}-${index}-remove`}
              >
                删除
              </button>
            </div>
          ) : null}
        </div>
      ))}
      {items.length === 0 && readOnly ? <p className="mufy-empty-line">（空列表）</p> : null}
      {!readOnly ? (
        <button
          type="button"
          className="char-btn char-btn-ghost mufy-btn-sm mufy-add-item"
          onClick={() => onChange([...items, ""])}
          data-testid={`${testIdPrefix}-add`}
        >
          <PlusIcon width={12} height={12} />
          添加一项
        </button>
      ) : null}
    </div>
  );
}
