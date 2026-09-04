import { useRef, useState } from "react";
import { ChevronDownIcon, ChevronRightIcon, PlusIcon } from "../icons";
import { classifyValue } from "./mufyValues";
import { RawJsonField } from "./RawJsonField";
import { RuntimeTriggerCard } from "./RuntimeTriggerCard";
import { StringListEditor } from "./StringListEditor";

export type FieldTone = "known" | "unknown" | "managed";

export interface NestedValueEditorProps {
  path: string;
  label: string;
  description?: string;
  tone?: FieldTone;
  value: unknown;
  onChange: (next: unknown) => void;
  readOnly?: boolean;
  depth: number;
  /** 位于 event_system 子树时，dict 的 runtime_trigger 保留字段按契约呈现。 */
  triggerAware?: boolean;
  /** 已知字符串子键的多行提示。 */
  multilineHint?: boolean;
  /** 未知键默认进入 raw JSON 编辑。 */
  defaultRaw?: boolean;
  /** 对象列表条目内嵌使用：不渲染行头。 */
  hideHeader?: boolean;
}

export function NestedValueEditor({
  path,
  label,
  description,
  tone = "known",
  value,
  onChange,
  readOnly = false,
  depth,
  triggerAware = false,
  multilineHint = false,
  defaultRaw = false,
  hideHeader = false,
}: NestedValueEditorProps) {
  const kind = classifyValue(value);
  const effectiveReadOnly = readOnly || tone === "managed";
  const [rawMode, setRawMode] = useState(defaultRaw || kind === "raw");
  const [collapsed, setCollapsed] = useState(!hideHeader && depth >= 2);

  const renderGuided = () => {
    if (kind === "string") {
      return (
        <StringRow
          value={value as string}
          onChange={onChange}
          readOnly={effectiveReadOnly}
          multilineHint={multilineHint}
          testId={`mufy-value-${path}`}
          ariaLabel={label}
        />
      );
    }
    if (kind === "number") {
      return (
        <input
          type="number"
          step="any"
          className="char-create-input mufy-input-num"
          value={String(value)}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw.trim() === "") return;
            const parsed = Number(raw);
            if (Number.isFinite(parsed)) onChange(parsed);
          }}
          disabled={effectiveReadOnly}
          aria-label={label}
          data-testid={`mufy-value-${path}`}
        />
      );
    }
    if (kind === "boolean") {
      return (
        <label className="mufy-bool">
          <input
            type="checkbox"
            checked={value === true}
            onChange={(event) => onChange(event.target.checked)}
            disabled={effectiveReadOnly}
            data-testid={`mufy-value-${path}`}
          />
          <span>{value === true ? "是" : "否"}</span>
        </label>
      );
    }
    if (kind === "stringList") {
      const items = value as string[];
      return (
        <div className="mufy-stringlist-wrap">
          <StringListEditor
            items={items}
            onChange={onChange}
            readOnly={effectiveReadOnly}
            testIdPrefix={`mufy-value-${path}`}
            ariaLabel={label}
          />
          {!effectiveReadOnly && items.length === 0 ? (
            <button
              type="button"
              className="char-btn char-btn-ghost mufy-btn-sm"
              onClick={() => onChange([{}])}
              data-testid={`mufy-objlist-add-${path}`}
            >
              <PlusIcon width={12} height={12} />
              添加对象条目
            </button>
          ) : null}
        </div>
      );
    }
    if (kind === "objectList") {
      const items = value as Record<string, unknown>[];
      return (
        <div className="mufy-obj-list" data-testid={`mufy-objlist-${path}`}>
          {items.map((item, index) => (
            <ObjectListItem
              key={index}
              path={`${path}.${index}`}
              index={index}
              item={item}
              onReplace={(next) => {
                const nextItems = [...items];
                nextItems[index] = next as Record<string, unknown>;
                onChange(nextItems);
              }}
              onRemove={() => onChange(items.filter((_, i) => i !== index))}
              onMove={(delta) => {
                const target = index + delta;
                if (target < 0 || target >= items.length) return;
                const nextItems = [...items];
                const moved = nextItems[index];
                nextItems[index] = nextItems[target];
                nextItems[target] = moved;
                onChange(nextItems);
              }}
              canMoveUp={index > 0}
              canMoveDown={index < items.length - 1}
              readOnly={effectiveReadOnly}
              depth={depth + 1}
              triggerAware={triggerAware}
            />
          ))}
          {!effectiveReadOnly ? (
            <button
              type="button"
              className="char-btn char-btn-ghost mufy-btn-sm"
              onClick={() => onChange([...items, {}])}
              data-testid={`mufy-objlist-add-${path}`}
            >
              <PlusIcon width={12} height={12} />
              添加条目
            </button>
          ) : null}
        </div>
      );
    }

    const obj = value as Record<string, unknown>;
    const hasTrigger = triggerAware && "runtime_trigger" in obj;
    const rowKeys = Object.keys(obj).filter((key) => !(hasTrigger && key === "runtime_trigger"));
    const bodyVisible = hideHeader || !collapsed;
    return (
      <div className="mufy-obj-group">
        {bodyVisible ? (
          <>
            {hasTrigger ? (
              <RuntimeTriggerCard
                trigger={obj.runtime_trigger}
                onChange={(next) => onChange({ ...obj, runtime_trigger: next })}
                readOnly={effectiveReadOnly}
                testIdPrefix={`mufy-trigger-${path}`}
              />
            ) : null}
            {rowKeys.length === 0 ? <p className="mufy-empty-line">（空对象）</p> : null}
            {rowKeys.map((key) => (
              <NestedValueEditor
                key={key}
                path={`${path}.${key}`}
                label={key}
                value={obj[key]}
                onChange={(next) => onChange({ ...obj, [key]: next })}
                readOnly={effectiveReadOnly}
                depth={depth + 1}
                triggerAware={triggerAware}
              />
            ))}
            {!effectiveReadOnly ? (
              <AddKeyRow path={path} obj={obj} onAdd={(key) => onChange({ ...obj, [key]: "" })} />
            ) : null}
          </>
        ) : null}
      </div>
    );
  };

  const showGuided = !rawMode && kind !== "raw";
  const body = showGuided ? (
    renderGuided()
  ) : (
    <RawJsonField
      value={value}
      onChange={onChange}
      readOnly={effectiveReadOnly}
      testId={`mufy-raw-${path}`}
      ariaLabel={`以 JSON 编辑 ${label}`}
    />
  );

  if (hideHeader) {
    return <div className="mufy-nested-body">{body}</div>;
  }

  return (
    <div className="mufy-row" data-testid={`mufy-row-${path}`}>
      <div className="mufy-row-head">
        {kind === "object" ? (
          <button
            type="button"
            className="mufy-collapse"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? `展开 ${label}` : `收起 ${label}`}
            data-testid={`mufy-collapse-${path}`}
          >
            {collapsed ? <ChevronRightIcon width={12} height={12} /> : <ChevronDownIcon width={12} height={12} />}
          </button>
        ) : null}
        <span className="mufy-row-label">{label}</span>
        {tone === "unknown" ? <span className="mufy-tag mufy-tag-unknown">未识别字段</span> : null}
        {tone === "managed" ? <span className="mufy-tag mufy-tag-managed">受管理字段</span> : null}
        <span className="mufy-row-spacer" />
        {!effectiveReadOnly && kind !== "raw" ? (
          <button
            type="button"
            className="char-btn char-btn-ghost mufy-btn-xs"
            onClick={() => setRawMode((v) => !v)}
            aria-pressed={rawMode}
            data-testid={`mufy-json-toggle-${path}`}
          >
            {rawMode ? "表单编辑" : "JSON"}
          </button>
        ) : null}
      </div>
      {description ? <p className="mufy-row-desc">{description}</p> : null}
      {body}
    </div>
  );
}

function StringRow({
  value,
  onChange,
  readOnly,
  multilineHint,
  testId,
  ariaLabel,
}: {
  value: string;
  onChange: (next: string) => void;
  readOnly: boolean;
  multilineHint: boolean;
  testId: string;
  ariaLabel: string;
}) {
  // 多行与否在挂载时一次性判定，输入过程中控件形态保持稳定、不丢焦点。
  const multilineRef = useRef<boolean | null>(null);
  if (multilineRef.current === null) {
    multilineRef.current = multilineHint || value.includes("\n") || value.length > 60;
  }
  const multiline = multilineRef.current;
  if (multiline) {
    return (
      <textarea
        className="char-create-textarea mufy-textarea-sm"
        rows={3}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={readOnly}
        spellCheck={false}
        aria-label={ariaLabel}
        data-testid={testId}
      />
    );
  }
  return (
    <input
      className="char-create-input"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={readOnly}
      spellCheck={false}
      aria-label={ariaLabel}
      data-testid={testId}
    />
  );
}

interface ObjectListItemProps {
  path: string;
  index: number;
  item: Record<string, unknown>;
  onReplace: (next: unknown) => void;
  onRemove: () => void;
  onMove: (delta: -1 | 1) => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  readOnly: boolean;
  depth: number;
  triggerAware: boolean;
}

function ObjectListItem({
  path,
  index,
  item,
  onReplace,
  onRemove,
  onMove,
  canMoveUp,
  canMoveDown,
  readOnly,
  depth,
  triggerAware,
}: ObjectListItemProps) {
  const [rawMode, setRawMode] = useState(false);
  return (
    <div className="mufy-object-item" data-testid={`mufy-item-${path}`}>
      <div className="mufy-object-item-head">
        <span className="mufy-obj-key">条目 {index + 1}</span>
        {!readOnly ? (
          <div className="mufy-row-actions">
            <button
              type="button"
              className="char-btn char-btn-ghost mufy-btn-xs"
              onClick={() => setRawMode((v) => !v)}
              aria-pressed={rawMode}
              data-testid={`mufy-json-toggle-${path}`}
            >
              {rawMode ? "表单编辑" : "JSON"}
            </button>
            <button
              type="button"
              className="char-btn char-btn-ghost mufy-btn-xs"
              onClick={() => onMove(-1)}
              disabled={!canMoveUp}
              aria-label="上移"
              data-testid={`mufy-item-up-${path}`}
            >
              ↑
            </button>
            <button
              type="button"
              className="char-btn char-btn-ghost mufy-btn-xs"
              onClick={() => onMove(1)}
              disabled={!canMoveDown}
              aria-label="下移"
              data-testid={`mufy-item-down-${path}`}
            >
              ↓
            </button>
            <button
              type="button"
              className="char-btn char-btn-ghost mufy-btn-xs mufy-danger"
              onClick={onRemove}
              aria-label="删除条目"
              data-testid={`mufy-item-remove-${path}`}
            >
              删除
            </button>
          </div>
        ) : null}
      </div>
      {rawMode ? (
        <RawJsonField
          value={item}
          onChange={onReplace}
          readOnly={readOnly}
          testId={`mufy-raw-${path}`}
          ariaLabel={`以 JSON 编辑条目 ${index + 1}`}
        />
      ) : (
        <NestedValueEditor
          path={path}
          label={`条目 ${index + 1}`}
          value={item}
          onChange={onReplace}
          readOnly={readOnly}
          depth={depth}
          triggerAware={triggerAware}
          hideHeader
        />
      )}
    </div>
  );
}

function AddKeyRow({
  path,
  obj,
  onAdd,
}: {
  path: string;
  obj: Record<string, unknown>;
  onAdd: (key: string) => void;
}) {
  const [keyName, setKeyName] = useState("");
  const trimmed = keyName.trim();
  const canAdd = trimmed.length > 0 && !(trimmed in obj);
  return (
    <div className="mufy-addkey">
      <input
        className="char-create-input mufy-addkey-input"
        placeholder="新字段名"
        value={keyName}
        onChange={(event) => setKeyName(event.target.value)}
        data-testid={`mufy-addkey-input-${path}`}
      />
      <button
        type="button"
        className="char-btn char-btn-ghost mufy-btn-sm"
        onClick={() => {
          if (!canAdd) return;
          onAdd(trimmed);
          setKeyName("");
        }}
        disabled={!canAdd}
        data-testid={`mufy-addkey-apply-${path}`}
      >
        添加字段
      </button>
    </div>
  );
}
