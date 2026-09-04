import { InfoIcon } from "../icons";
import "./mufy-editor.css";
import { CommandPanelsView } from "./CommandPanelsView";
import { MANAGED_KEY_NOTES, MANAGED_KEYS, MUFY_BLOCKS } from "./mufySchema";
import { isPlainObject } from "./mufyValues";
import { MufyBlockEditor } from "./MufyBlockEditor";
import { NestedValueEditor } from "./NestedValueEditor";

export interface MufyAdvancedEditorProps {
  /** data.extensions.hsr 对象，可为空（新建卡尚无高级设定）。 */
  hsr: Record<string, unknown> | null | undefined;
  /** 任何编辑后回传完整 hsr；未触及的键原样透传。 */
  onChange: (next: Record<string, unknown>) => void;
  readOnly?: boolean;
}

export function MufyAdvancedEditor({ hsr, onChange, readOnly = false }: MufyAdvancedEditorProps) {
  if (hsr != null && !isPlainObject(hsr)) {
    return (
      <div className="mufy-editor" data-testid="mufy-advanced-editor">
        <div className="char-create-notice-box" role="alert">
          <InfoIcon width={16} height={16} />
          <div>高级设定数据（extensions.hsr）不是键值对象，编辑器未启用；数据保持原样，未被改动。</div>
        </div>
      </div>
    );
  }

  const obj: Record<string, unknown> = hsr ?? {};
  const updateKey = (key: string, next: unknown) => onChange({ ...obj, [key]: next });
  const blockKeySet = new Set(MUFY_BLOCKS.map((block) => block.key));
  const managedKeys = MANAGED_KEYS.filter((key) => key in obj);
  const unknownKeys = Object.keys(obj).filter(
    (key) => !blockKeySet.has(key) && key !== "command_panels" && !MANAGED_KEYS.includes(key),
  );

  return (
    <div className="mufy-editor" data-testid="mufy-advanced-editor">
      <p className="mufy-editor-intro">
        这里编辑角色卡的 mufy 高级设定（data.extensions.hsr）。所有内容都会原样保存进卡片；未识别的键与结构不会丢失，可随时切换
        JSON 方式核对。
      </p>
      {MUFY_BLOCKS.map((meta) => (
        <MufyBlockEditor
          key={meta.key}
          meta={meta}
          value={obj[meta.key]}
          onChange={(next) => updateKey(meta.key, next)}
          readOnly={readOnly}
        />
      ))}
      <CommandPanelsView panels={obj.command_panels} />
      {managedKeys.length > 0 || unknownKeys.length > 0 ? (
        <section className="mufy-block" data-testid="mufy-other-fields">
          <header className="mufy-block-head">
            <div className="mufy-block-head-text">
              <h3 className="mufy-block-title">其他字段</h3>
              <p className="mufy-block-desc">
                受管理字段由应用的其他功能维护，这里只读展示；未识别字段原样保留，可按需编辑。
              </p>
            </div>
          </header>
          <div className="mufy-block-rows">
            {managedKeys.map((key) => (
              <NestedValueEditor
                key={key}
                path={key}
                label={key}
                description={MANAGED_KEY_NOTES[key]}
                tone="managed"
                value={obj[key]}
                onChange={() => {}}
                readOnly
                depth={0}
              />
            ))}
            {unknownKeys.map((key) => (
              <NestedValueEditor
                key={key}
                path={key}
                label={key}
                tone="unknown"
                defaultRaw
                value={obj[key]}
                onChange={(next) => updateKey(key, next)}
                readOnly={readOnly}
                depth={0}
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
