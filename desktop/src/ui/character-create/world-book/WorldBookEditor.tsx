import { InfoIcon, PlusIcon } from "../icons";
import { isPlainObject, jsonToText } from "../mufy/mufyValues";
import { NumberField } from "./NumberField";
import { WorldBookEntryList } from "./WorldBookEntryList";
import "./world-book-editor.css";
import {
  DEFAULT_SCAN_DEPTH,
  DEFAULT_TOKEN_BUDGET,
  collectBookNotRunFields,
  createEmptyEntry,
} from "./worldBookSchema";

export interface WorldBookEditorProps {
  /** 酒馆 v3 JSON 的 character_book 对象；null/undefined 视为尚未创建的世界书。 */
  book: Record<string, unknown> | null | undefined;
  /** 任何编辑后回传完整 book；spread/replace 更新，未触及字段（含未知键）字节级保留。 */
  onChange: (next: Record<string, unknown>) => void;
  readOnly?: boolean;
}

const KNOWN_BOOK_KEYS = new Set([
  "name",
  "description",
  "scan_depth",
  "token_budget",
  "recursive_scanning",
  "extensions",
  "entries",
]);

function asEntryList(value: unknown): Record<string, unknown>[] | null {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) return null;
  return value as Record<string, unknown>[];
}

export function WorldBookEditor({ book, onChange, readOnly = false }: WorldBookEditorProps) {
  if (book != null && !isPlainObject(book)) {
    return (
      <div className="wb-editor" data-testid="wb-editor-invalid">
        <div className="char-create-notice-box" role="alert">
          <InfoIcon width={16} height={16} />
          <div>世界书数据（character_book）不是键值对象，编辑器未启用；数据保持原样，未被改动。</div>
        </div>
      </div>
    );
  }

  const obj: Record<string, unknown> = book ?? {};
  const setBookKey = (key: string, value: unknown) => {
    const next = { ...obj };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange(next);
  };

  const entriesValue = obj.entries;
  const entries = asEntryList(entriesValue);
  const notRunFields = collectBookNotRunFields(obj);
  const unknownBookKeys = Object.keys(obj).filter((key) => !KNOWN_BOOK_KEYS.has(key));

  return (
    <div className="wb-editor" data-testid="wb-editor">
      <p className="wb-editor-intro">
        这里编辑角色卡的世界书（character_book）。条目按主/次关键字在最近对话中匹配后插入提示词，或以常驻方式无条件注入；扫描深度缺省
        {DEFAULT_SCAN_DEPTH}，预算缺省 {DEFAULT_TOKEN_BUDGET}。存而不运行的字段与未识别键只展示、不编辑，任何保存都不会丢弃它们。
      </p>

      <section className="wb-block" data-testid="wb-book-settings">
        <header className="wb-block-head">
          <div className="wb-block-head-text">
            <h3 className="wb-block-title">书级设置</h3>
            <p className="wb-block-desc">留空即删键回缺省：scan_depth 缺省 {DEFAULT_SCAN_DEPTH}，token_budget 缺省 {DEFAULT_TOKEN_BUDGET}。</p>
          </div>
        </header>
        <div className="wb-book-fields">
          <div className="wb-depth-cell">
            <span className="wb-field-label">scan_depth（扫描深度）</span>
            <NumberField
              value={obj.scan_depth}
              onValueChange={(next) => setBookKey("scan_depth", next)}
              readOnly={readOnly}
              testId="wb-scan-depth"
              ariaLabel="扫描深度"
              placeholder={`缺省 ${DEFAULT_SCAN_DEPTH}`}
            />
          </div>
          <div className="wb-depth-cell">
            <span className="wb-field-label">token_budget（token 预算）</span>
            <NumberField
              value={obj.token_budget}
              onValueChange={(next) => setBookKey("token_budget", next)}
              readOnly={readOnly}
              testId="wb-token-budget"
              ariaLabel="token 预算"
              placeholder={`缺省 ${DEFAULT_TOKEN_BUDGET}`}
            />
          </div>
        </div>
        {notRunFields.length > 0 ? (
          <div className="wb-notrun" data-testid="wb-book-notrun">
            <p className="wb-notrun-title">书级「保留但不运行」字段（任何编辑与保存都不会丢弃它们）：</p>
            <ul className="wb-notrun-list">
              {notRunFields.map((field) => (
                <li key={field.id} className="wb-notrun-item" data-testid={`wb-book-notrun-${field.id}`}>
                  <span className="wb-badge-hold">保留但不运行</span>
                  <span className="wb-notrun-label">{field.label}</span>
                  <span className="wb-notrun-where">{field.where}</span>
                  <pre className="wb-raw-pre">{jsonToText(field.value)}</pre>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {unknownBookKeys.length > 0 ? (
          <div className="wb-notrun" data-testid="wb-book-unknown">
            <p className="wb-notrun-title">未识别的书级字段原样保留（只读展示）：</p>
            <ul className="wb-notrun-list">
              {unknownBookKeys.map((key) => (
                <li key={key} className="wb-notrun-item" data-testid={`wb-book-unknown-${key}`}>
                  <span className="wb-badge-hold">未识别</span>
                  <span className="wb-notrun-label">{key}</span>
                  <pre className="wb-raw-pre">{jsonToText(obj[key])}</pre>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="wb-block" data-testid="wb-entries-block">
        <header className="wb-block-head">
          <div className="wb-block-head-text">
            <h3 className="wb-block-title">条目列表{entries !== null ? `（${entries.length}）` : ""}</h3>
            <p className="wb-block-desc">上下移会交换相邻条目的 insertion_order，同时保持列表顺序与运行优先序一致。</p>
          </div>
        </header>
        {entries === null ? (
          <div className="wb-notice" role="alert" data-testid="wb-entries-malformed">
            <InfoIcon width={14} height={14} />
            <div>
              entries 不是数组，条目编辑器未启用；数据原样保留：
              <pre className="wb-raw-pre">{jsonToText(entriesValue)}</pre>
            </div>
          </div>
        ) : entries.length === 0 ? (
          <div className="wb-empty" data-testid="wb-empty-entries">
            <p>这个世界书还没有条目。</p>
            <p className="wb-empty-hint">
              条目由主关键字（可叠加次关键字逻辑）在最近对话中匹配激活，或以常驻方式无条件注入；也可以先新建一个条目，再逐步补关键字与内容。
            </p>
            {!readOnly ? (
              <button
                type="button"
                className="char-btn char-btn-ghost wb-btn-sm wb-add-entry"
                onClick={() => setBookKey("entries", [createEmptyEntry()])}
                data-testid="wb-add-entry"
              >
                <PlusIcon width={12} height={12} />
                新建条目
              </button>
            ) : null}
          </div>
        ) : (
          <WorldBookEntryList
            entries={entries}
            readOnly={readOnly}
            onChange={(next) => setBookKey("entries", next)}
          />
        )}
      </section>
    </div>
  );
}
