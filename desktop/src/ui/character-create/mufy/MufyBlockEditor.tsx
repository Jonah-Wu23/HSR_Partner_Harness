import { useState } from "react";
import { PlusIcon } from "../icons";
import { isPlainObject, valueTypeLabel } from "./mufyValues";
import type { MufyBlockMeta, MufyFieldMeta } from "./mufySchema";
import { NestedValueEditor } from "./NestedValueEditor";
import { RawJsonField } from "./RawJsonField";

export interface MufyBlockEditorProps {
  meta: MufyBlockMeta;
  value: unknown;
  onChange: (next: unknown) => void;
  readOnly?: boolean;
}

export function MufyBlockEditor({ meta, value, onChange, readOnly = false }: MufyBlockEditorProps) {
  const [rawMode, setRawMode] = useState(false);
  const [newKey, setNewKey] = useState("");
  const obj = isPlainObject(value) ? value : null;
  const knownByKey = new Map(meta.fields.map((field) => [field.key, field]));
  const missingKnown = meta.fields.filter((field) => obj === null || !(field.key in obj));

  const addKnownField = (field: MufyFieldMeta) => {
    onChange({ ...(obj ?? {}), [field.key]: field.createDefault() });
  };

  const addCustomKey = () => {
    const key = newKey.trim();
    if (obj === null || key === "" || key in obj) return;
    onChange({ ...obj, [key]: "" });
    setNewKey("");
  };

  const isEmptyObject = obj !== null && Object.keys(obj).length === 0;
  const showEmptyState = (obj === null && (value === undefined || value === null)) || isEmptyObject;
  const showNonObjectRaw = obj === null && value !== undefined && value !== null;
  const showWholeRaw = obj !== null && rawMode;
  const showRows = obj !== null && !rawMode && !isEmptyObject;
  const showFooter = !readOnly && !showWholeRaw && (showEmptyState || obj !== null);

  return (
    <section className="mufy-block" data-testid={`mufy-block-${meta.key}`}>
      <header className="mufy-block-head">
        <div className="mufy-block-head-text">
          <h3 className="mufy-block-title">{meta.title}</h3>
          <p className="mufy-block-desc">{meta.description}</p>
        </div>
        {obj !== null && !readOnly ? (
          <button
            type="button"
            className="char-btn char-btn-ghost mufy-btn-sm"
            onClick={() => setRawMode((v) => !v)}
            aria-pressed={rawMode}
            data-testid={`mufy-block-raw-${meta.key}`}
          >
            {rawMode ? "返回表单编辑" : "JSON 编辑整块"}
          </button>
        ) : null}
      </header>

      {showEmptyState ? (
        <div className="mufy-empty" data-testid={`mufy-empty-${meta.key}`}>
          <p>该分区暂无内容。</p>
          <p className="mufy-empty-hint">可以从下方常用字段开始，添加后随时切换 JSON 方式核对与粘贴。</p>
        </div>
      ) : null}

      {showNonObjectRaw ? (
        <div>
          <p className="mufy-block-desc">
            该分区的数据不是键值对象（实际为{valueTypeLabel(value)}），以下按原始 JSON 呈现，可直接编辑，内容不会丢失。
          </p>
          <RawJsonField
            value={value}
            onChange={onChange}
            readOnly={readOnly}
            testId={`mufy-raw-${meta.key}`}
            ariaLabel={`以 JSON 编辑 ${meta.title}`}
          />
        </div>
      ) : null}

      {showWholeRaw ? (
        <RawJsonField
          value={value}
          onChange={onChange}
          readOnly={readOnly}
          testId={`mufy-raw-${meta.key}`}
          ariaLabel={`以 JSON 编辑 ${meta.title}`}
        />
      ) : null}

      {showRows ? (
        <div className="mufy-block-rows">
          {Object.keys(obj).map((key) => {
            const known = knownByKey.get(key);
            return (
              <NestedValueEditor
                key={key}
                path={`${meta.key}.${key}`}
                label={known ? known.label : key}
                description={known?.description}
                tone={known ? "known" : "unknown"}
                defaultRaw={!known}
                multilineHint={known?.multiline === true}
                value={obj[key]}
                onChange={(next) => onChange({ ...obj, [key]: next })}
                readOnly={readOnly}
                depth={0}
                triggerAware={meta.triggerAware === true}
              />
            );
          })}
        </div>
      ) : null}

      {showFooter ? (
        <footer className="mufy-block-add">
          {missingKnown.length > 0 ? (
            <div className="mufy-add-chips">
              {missingKnown.map((field) => (
                <button
                  key={field.key}
                  type="button"
                  className="mufy-chip"
                  title={field.description}
                  onClick={() => addKnownField(field)}
                  data-testid={`mufy-add-${meta.key}.${field.key}`}
                >
                  <PlusIcon width={12} height={12} />
                  {field.label}
                </button>
              ))}
            </div>
          ) : null}
          <div className="mufy-addkey">
            <input
              className="char-create-input mufy-addkey-input"
              placeholder="自定义字段名"
              value={newKey}
              onChange={(event) => setNewKey(event.target.value)}
              data-testid={`mufy-addkey-input-${meta.key}`}
            />
            <button
              type="button"
              className="char-btn char-btn-ghost mufy-btn-sm"
              onClick={addCustomKey}
              disabled={obj === null || newKey.trim() === "" || newKey.trim() in obj}
              data-testid={`mufy-addkey-apply-${meta.key}`}
            >
              添加字段
            </button>
          </div>
        </footer>
      ) : null}
    </section>
  );
}
