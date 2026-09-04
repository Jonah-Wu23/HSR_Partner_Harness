import { useState } from "react";
import { ChevronDownIcon, ChevronRightIcon, PlusIcon, TrashIcon } from "../icons";
import { isPlainObject, jsonToText } from "../mufy/mufyValues";
import { WorldBookEntryEditor } from "./WorldBookEntryEditor";
import "./world-book-editor.css";
import { createEmptyEntry, positionSummary } from "./worldBookSchema";

export interface WorldBookEntryListProps {
  entries: Record<string, unknown>[];
  readOnly?: boolean;
  /** 回传完整条目数组；未触及条目原样透传。 */
  onChange: (next: Record<string, unknown>[]) => void;
}

export function WorldBookEntryList({ entries, readOnly = false, onChange }: WorldBookEntryListProps) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  const toggle = (index: number) => setExpanded((prev) => ({ ...prev, [index]: !prev[index] }));

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= entries.length) return;
    const current = entries[index];
    const neighbor = entries[target];
    const canSwapOrders = "insertion_order" in current && "insertion_order" in neighbor;
    const next = [...entries];
    next[index] = canSwapOrders ? { ...neighbor, insertion_order: current.insertion_order } : neighbor;
    next[target] = canSwapOrders ? { ...current, insertion_order: neighbor.insertion_order } : current;
    onChange(next);
  };

  const copyAt = (index: number) => {
    const copy = JSON.parse(JSON.stringify(entries[index])) as Record<string, unknown>;
    const next = [...entries];
    next.splice(index + 1, 0, copy);
    onChange(next);
  };

  const removeAt = (index: number) => {
    onChange(entries.filter((_, i) => i !== index));
  };

  const add = () => onChange([...entries, createEmptyEntry()]);

  return (
    <div className="wb-entries" data-testid="wb-entries">
      {entries.map((entry, index) => {
        const isOpen = expanded[index] === true;
        const enabled = entry.enabled !== false;
        const constant = entry.constant === true;
        const keysSummary = Array.isArray(entry.keys)
          ? entry.keys.filter((key) => typeof key === "string").join("、")
          : "";
        const comment = typeof entry.comment === "string" && entry.comment !== "" ? entry.comment : `条目 ${index + 1}`;
        return (
          <div className="wb-entry-row" data-testid={`wb-entry-row-${index}`} key={index}>
            <div className="wb-entry-head">
              <button
                type="button"
                className="wb-collapse"
                onClick={() => toggle(index)}
                aria-expanded={isOpen}
                aria-label={isOpen ? "收起条目" : "展开条目"}
                data-testid={`wb-entry-toggle-${index}`}
              >
                {isOpen ? <ChevronDownIcon width={14} height={14} /> : <ChevronRightIcon width={14} height={14} />}
              </button>
              <div className="wb-entry-summary">
                <span className={`wb-tag ${enabled ? "wb-tag-on" : "wb-tag-off"}`}>
                  {enabled ? "启用" : "已停用"}
                </span>
                {constant ? <span className="wb-tag wb-tag-constant">常驻</span> : null}
                <span className="wb-tag wb-tag-position">{positionSummary(entry)}</span>
                <span className="wb-entry-name">{comment}</span>
                <span className="wb-entry-keys">{keysSummary !== "" ? keysSummary : "（无关键字）"}</span>
              </div>
              {!readOnly ? (
                <div className="wb-row-actions">
                  <button
                    type="button"
                    className="char-btn char-btn-ghost wb-btn-xs"
                    onClick={() => move(index, -1)}
                    disabled={index === 0}
                    aria-label="上移"
                    data-testid={`wb-entry-up-${index}`}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="char-btn char-btn-ghost wb-btn-xs"
                    onClick={() => move(index, 1)}
                    disabled={index === entries.length - 1}
                    aria-label="下移"
                    data-testid={`wb-entry-down-${index}`}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="char-btn char-btn-ghost wb-btn-xs"
                    onClick={() => copyAt(index)}
                    aria-label="复制条目"
                    data-testid={`wb-entry-copy-${index}`}
                  >
                    复制
                  </button>
                  <button
                    type="button"
                    className="char-btn char-btn-ghost wb-btn-xs wb-danger"
                    onClick={() => removeAt(index)}
                    aria-label="删除条目"
                    data-testid={`wb-entry-remove-${index}`}
                  >
                    <TrashIcon width={12} height={12} />
                    删除
                  </button>
                </div>
              ) : null}
            </div>
            {isOpen ? (
              isPlainObject(entry) ? (
                <WorldBookEntryEditor
                  entry={entry}
                  testIdPrefix={`wb-entry-${index}`}
                  readOnly={readOnly}
                  onChange={(next) => {
                    const nextEntries = [...entries];
                    nextEntries[index] = next;
                    onChange(nextEntries);
                  }}
                />
              ) : (
                <div className="wb-notice" role="alert" data-testid={`wb-entry-malformed-${index}`}>
                  <p>该条目不是键值对象，编辑器未启用；数据原样保留：</p>
                  <pre className="wb-raw-pre">{jsonToText(entry)}</pre>
                </div>
              )
            ) : null}
          </div>
        );
      })}
      {!readOnly ? (
        <button
          type="button"
          className="char-btn char-btn-ghost wb-btn-sm wb-add-entry"
          onClick={add}
          data-testid="wb-add-entry"
        >
          <PlusIcon width={12} height={12} />
          新建条目
        </button>
      ) : null}
    </div>
  );
}
