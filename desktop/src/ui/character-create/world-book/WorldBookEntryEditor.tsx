import { AlertCircleIcon, InfoIcon } from "../icons";
import { StringListEditor } from "../mufy/StringListEditor";
import { isPlainObject, jsonToText } from "../mufy/mufyValues";
import { NumberField } from "./NumberField";
import "./world-book-editor.css";
import {
  DEFAULT_DEPTH,
  DEFAULT_ROLE,
  ROLES,
  SELECTIVE_LOGICS,
  SUPPORTED_POSITIONS,
  POSITION_LABELS,
  asStringList,
  collectEntryNotRunFields,
  displayPositionRaw,
  entryRegexWarnings,
  entryUnknownExtensionKeys,
  entryUnknownKeys,
  getExtensions,
  normalizePosition,
  readDepth,
  readRole,
} from "./worldBookSchema";

export interface WorldBookEntryEditorProps {
  entry: Record<string, unknown>;
  /** data-testid 前缀，如 `wb-entry-0`。 */
  testIdPrefix: string;
  readOnly?: boolean;
  /** 回传完整条目对象；spread/replace 更新，未触及字段原样保留。 */
  onChange: (next: Record<string, unknown>) => void;
}

function BoolToggle({
  checked,
  label,
  hint,
  testId,
  disabled,
  onChange,
}: {
  checked: boolean;
  label: string;
  hint?: string;
  testId: string;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="wb-bool">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        data-testid={testId}
      />
      <span>{label}</span>
      {hint ? <span className="wb-bool-hint">{hint}</span> : null}
    </label>
  );
}

function RawValue({ value }: { value: unknown }) {
  return <pre className="wb-raw-pre">{jsonToText(value)}</pre>;
}

export function WorldBookEntryEditor({ entry, testIdPrefix, readOnly = false, onChange }: WorldBookEntryEditorProps) {
  const setKey = (key: string, value: unknown) => {
    const next = { ...entry };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange(next);
  };

  const ext = getExtensions(entry);
  const extensionsMalformed = entry.extensions != null && !isPlainObject(entry.extensions);
  const setExtensionValue = (key: string, value: unknown) => {
    const base: Record<string, unknown> = { ...(ext ?? {}) };
    if (value === undefined) delete base[key];
    else base[key] = value;
    onChange({ ...entry, extensions: base });
  };

  const keys = asStringList(entry.keys);
  const secondaryKeys = asStringList(entry.secondary_keys);
  const rawLogic = ext && "selectiveLogic" in ext ? ext.selectiveLogic : undefined;
  const logicValid = SELECTIVE_LOGICS.some((logic) => logic.value === rawLogic);
  const logicChoice = logicValid ? String(rawLogic) : "0";

  const rawPosition = entry.position;
  const normalizedPosition = normalizePosition(rawPosition);
  const positionAbsent = rawPosition === undefined;
  const positionChoice = normalizedPosition ?? (positionAbsent ? "before_char" : "__unsupported__");

  const regexWarnings = entryRegexWarnings(entry);
  const notRunFields = collectEntryNotRunFields(entry);
  const unknownEntryKeys = entryUnknownKeys(entry);
  const unknownExtKeys = ext ? entryUnknownExtensionKeys(ext) : [];
  const depth = ext ? readDepth(ext) : null;
  const role = ext ? readRole(ext) : null;

  return (
    <div className="wb-entry-editor" data-testid={`${testIdPrefix}-editor`}>
      <div className="wb-field">
        <label className="wb-field-label" htmlFor={`${testIdPrefix}-comment`}>
          条目备注（comment）
        </label>
        <input
          id={`${testIdPrefix}-comment`}
          className="char-create-input"
          value={typeof entry.comment === "string" ? entry.comment : ""}
          onChange={(event) => setKey("comment", event.target.value)}
          disabled={readOnly}
          aria-label="条目备注"
          data-testid={`${testIdPrefix}-comment`}
        />
      </div>

      <div className="wb-field">
        <label className="wb-field-label" htmlFor={`${testIdPrefix}-content`}>
          内容（content）
        </label>
        <textarea
          id={`${testIdPrefix}-content`}
          className="char-create-input wb-textarea"
          value={typeof entry.content === "string" ? entry.content : ""}
          onChange={(event) => setKey("content", event.target.value)}
          disabled={readOnly}
          aria-label="条目内容"
          data-testid={`${testIdPrefix}-content`}
        />
      </div>

      <div className="wb-field">
        <span className="wb-field-label">主关键字（keys）</span>
        {keys === null ? (
          <div className="wb-notice" data-testid={`${testIdPrefix}-keys-malformed`}>
            <InfoIcon width={14} height={14} />
            <span>keys 不是字符串数组，已原样保留，未启用编辑：</span>
            <RawValue value={entry.keys} />
          </div>
        ) : (
          <StringListEditor
            items={keys}
            onChange={(next) => setKey("keys", next)}
            readOnly={readOnly}
            testIdPrefix={`${testIdPrefix}-keys`}
            ariaLabel="主关键字"
          />
        )}
      </div>

      <div className="wb-field">
        <BoolToggle
          checked={entry.selective === true}
          label="selective（启用次关键字）"
          hint="开启且次关键字非空时，次关键字逻辑生效"
          testId={`${testIdPrefix}-selective`}
          disabled={readOnly}
          onChange={(next) => setKey("selective", next)}
        />
        <div className="wb-logic-row">
          <label className="wb-field-label" htmlFor={`${testIdPrefix}-selective-logic`}>
            次关键字逻辑（extensions.selectiveLogic）
          </label>
          <select
            id={`${testIdPrefix}-selective-logic`}
            className="char-create-input wb-select"
            value={logicChoice}
            onChange={(event) => setExtensionValue("selectiveLogic", Number(event.target.value))}
            disabled={readOnly || ext === null}
            aria-label="次关键字逻辑"
            data-testid={`${testIdPrefix}-selective-logic`}
          >
            {SELECTIVE_LOGICS.map((logic) => (
              <option key={logic.value} value={String(logic.value)}>
                {logic.label}
                {logic.value === 0 && !logicValid ? "（缺省）" : ""}
              </option>
            ))}
            {!logicValid && rawLogic !== undefined ? (
              <option value="__invalid__" disabled>
                当前值 {String(rawLogic)} 非 0-3（运行时按 AND_ANY 处理，原值保留）
              </option>
            ) : null}
          </select>
        </div>
        {secondaryKeys === null ? (
          <div className="wb-notice" data-testid={`${testIdPrefix}-secondary-keys-malformed`}>
            <InfoIcon width={14} height={14} />
            <span>secondary_keys 不是字符串数组，已原样保留，未启用编辑：</span>
            <RawValue value={entry.secondary_keys} />
          </div>
        ) : (
          <StringListEditor
            items={secondaryKeys}
            onChange={(next) => setKey("secondary_keys", next)}
            readOnly={readOnly}
            testIdPrefix={`${testIdPrefix}-secondary-keys`}
            ariaLabel="次关键字"
          />
        )}
      </div>

      <div className="wb-flag-row">
        <BoolToggle
          checked={entry.enabled !== false}
          label="enabled（启用）"
          hint="缺省视为启用"
          testId={`${testIdPrefix}-enabled`}
          disabled={readOnly}
          onChange={(next) => setKey("enabled", next)}
        />
        <BoolToggle
          checked={entry.constant === true}
          label="constant（常驻）"
          hint="无条件激活，不做关键字匹配"
          testId={`${testIdPrefix}-constant`}
          disabled={readOnly}
          onChange={(next) => setKey("constant", next)}
        />
        <BoolToggle
          checked={entry.case_sensitive === true}
          label="case_sensitive（大小写敏感）"
          testId={`${testIdPrefix}-case-sensitive`}
          disabled={readOnly}
          onChange={(next) => setKey("case_sensitive", next)}
        />
        <BoolToggle
          checked={entry.use_regex === true}
          label="use_regex（裸关键字按正则）"
          testId={`${testIdPrefix}-use-regex`}
          disabled={readOnly}
          onChange={(next) => setKey("use_regex", next)}
        />
      </div>

      <div className="wb-field">
        <label className="wb-field-label" htmlFor={`${testIdPrefix}-position`}>
          插入位置（position）
        </label>
        <select
          id={`${testIdPrefix}-position`}
          className="char-create-input wb-select"
          value={positionChoice}
          onChange={(event) => {
            const next = event.target.value;
            if ((SUPPORTED_POSITIONS as readonly string[]).includes(next)) setKey("position", next);
          }}
          disabled={readOnly}
          aria-label="插入位置"
          data-testid={`${testIdPrefix}-position`}
        >
          {SUPPORTED_POSITIONS.map((position) => (
            <option key={position} value={position}>
              {position}（{POSITION_LABELS[position]}
              {position === "before_char" && positionAbsent ? "，缺省" : ""}）
            </option>
          ))}
          {!positionAbsent && normalizedPosition === null ? (
            <option value="__unsupported__" disabled>
              不支持的位置：{displayPositionRaw(rawPosition)}（保留但不运行，不注入）
            </option>
          ) : null}
        </select>
        {normalizedPosition === null && !positionAbsent ? (
          <p className="wb-hint">当前位置不在支持范围（before_char / after_char / atDepth），条目运行时不会注入；原值保留，不做静默改写。</p>
        ) : null}
        {normalizedPosition === "atDepth" ? (
          <div className="wb-depth-row">
            <div className="wb-depth-cell">
              <span className="wb-field-label">depth（extensions.depth）</span>
              <NumberField
                value={ext && "depth" in ext ? ext.depth : undefined}
                onValueChange={(next) => setExtensionValue("depth", next)}
                readOnly={readOnly || ext === null}
                testId={`${testIdPrefix}-depth`}
                ariaLabel="注入深度"
                placeholder={`缺省 ${DEFAULT_DEPTH}`}
              />
            </div>
            <div className="wb-depth-cell">
              <label className="wb-field-label" htmlFor={`${testIdPrefix}-role`}>
                role（extensions.role）
              </label>
              <select
                id={`${testIdPrefix}-role`}
                className="char-create-input wb-select"
                value={role ?? DEFAULT_ROLE}
                onChange={(event) => setExtensionValue("role", event.target.value)}
                disabled={readOnly || ext === null}
                aria-label="注入角色"
                data-testid={`${testIdPrefix}-role`}
              >
                {ROLES.map((item) => (
                  <option key={item} value={item}>
                    {item}
                    {item === DEFAULT_ROLE && role === null ? "（缺省）" : ""}
                  </option>
                ))}
                {role === null && ext !== null && "role" in ext ? (
                  <option value="__invalid__" disabled>
                    当前值 {String(ext.role)} 非法（运行时按 system 处理，原值保留）
                  </option>
                ) : null}
              </select>
            </div>
            <span className="wb-hint">留空 depth 或保持缺省即回缺省值 {DEFAULT_DEPTH} / {DEFAULT_ROLE}；键从 extensions 中删除。</span>
          </div>
        ) : null}
      </div>

      <div className="wb-field">
        <span className="wb-field-label">insertion_order</span>
        <NumberField
          value={entry.insertion_order}
          onValueChange={(next) => setKey("insertion_order", next)}
          readOnly={readOnly}
          testId={`${testIdPrefix}-insertion-order`}
          ariaLabel="插入顺序"
        />
        <p className="wb-hint">激活优先序按 insertion_order 降序；同值按条目 id / 书内下标平局。</p>
      </div>

      {extensionsMalformed ? (
        <div className="wb-notice" role="alert" data-testid={`${testIdPrefix}-extensions-malformed`}>
          <InfoIcon width={14} height={14} />
          <span>extensions 不是键值对象，扩展设置未启用编辑；数据原样保留。</span>
        </div>
      ) : null}

      {regexWarnings.length > 0 ? (
        <div className="wb-warning" data-testid={`${testIdPrefix}-regex-warning`}>
          <AlertCircleIcon width={14} height={14} />
          <ul>
            {regexWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {notRunFields.length > 0 ? (
        <div className="wb-notrun" data-testid={`${testIdPrefix}-notrun`}>
          <p className="wb-notrun-title">以下字段保留但不运行（任何编辑与保存都不会丢弃它们）：</p>
          <ul className="wb-notrun-list">
            {notRunFields.map((field) => (
              <li key={field.id} className="wb-notrun-item" data-testid={`${testIdPrefix}-notrun-${field.id}`}>
                <span className="wb-badge-hold">保留但不运行</span>
                <span className="wb-notrun-label">{field.label}</span>
                <span className="wb-notrun-where">{field.where}</span>
                <RawValue value={field.value} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {unknownEntryKeys.length > 0 || unknownExtKeys.length > 0 ? (
        <div className="wb-notrun" data-testid={`${testIdPrefix}-unknown`}>
          <p className="wb-notrun-title">未识别字段原样保留（只读展示）：</p>
          <ul className="wb-notrun-list">
            {unknownEntryKeys.map((key) => (
              <li key={key} className="wb-notrun-item" data-testid={`${testIdPrefix}-unknown-${key}`}>
                <span className="wb-badge-hold">未识别</span>
                <span className="wb-notrun-label">{key}</span>
                <span className="wb-notrun-where">条目字段</span>
                <RawValue value={entry[key]} />
              </li>
            ))}
            {unknownExtKeys.map((key) => (
              <li key={key} className="wb-notrun-item" data-testid={`${testIdPrefix}-unknown-ext-${key}`}>
                <span className="wb-badge-hold">未识别</span>
                <span className="wb-notrun-label">{key}</span>
                <span className="wb-notrun-where">extensions</span>
                <RawValue value={ext?.[key]} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
