import type { ReactNode } from "react";
import { InfoIcon } from "../icons";
import { isPlainObject, jsonToText } from "./mufyValues";

/**
 * command_panels 只读声明式呈现（安全边界）：任何值都作为转义文本展示，
 * 不渲染 HTML、不提供任何编辑入口，明确标注仅保存为数据。
 */
export function CommandPanelsView({ panels }: { panels: unknown }) {
  return (
    <section className="mufy-block" data-testid="mufy-command-panels">
      <header className="mufy-block-head">
        <div className="mufy-block-head-text">
          <h3 className="mufy-block-title">指令面板（command_panels）</h3>
          <p className="mufy-block-desc">角色卡作者声明的会话内面板数据，以代码原文形式查看。</p>
        </div>
        {Array.isArray(panels) ? <span className="mufy-meta">{panels.length} 个面板</span> : null}
      </header>
      <div className="char-create-notice-box mufy-panel-notice" role="note" data-testid="mufy-command-panels-notice">
        <InfoIcon width={16} height={16} />
        <div>
          <div className="mufy-panel-notice-title">仅保存为数据，不会在应用内执行</div>
          <div>面板内容可能包含 HTML、脚本或样式文本，本应用只原样存储与展示，不渲染、不运行其中任何代码。</div>
        </div>
      </div>
      {panels === undefined ? (
        <p className="mufy-empty-line" data-testid="mufy-command-panels-empty">
          未声明 command_panels 数据。
        </p>
      ) : !Array.isArray(panels) ? (
        <div>
          <p className="mufy-block-desc">command_panels 不是数组，以下为原始数据：</p>
          <pre className="char-create-json-view">{jsonToText(panels)}</pre>
        </div>
      ) : panels.length === 0 ? (
        <p className="mufy-empty-line">command_panels 为空列表。</p>
      ) : (
        <div className="mufy-panel-list">
          {panels.map((panel, index) => (
            <article className="mufy-panel-card" key={index} data-testid={`mufy-command-panel-${index}`}>
              <div className="mufy-panel-card-head">
                <span className="mufy-panel-index">面板 {index + 1}</span>
                {isPlainObject(panel) && typeof panel.command === "string" ? (
                  <code className="mufy-panel-command">{panel.command}</code>
                ) : null}
              </div>
              {isPlainObject(panel) ? (
                <dl className="mufy-panel-rows">
                  {Object.keys(panel).map((key) => (
                    <div className="mufy-panel-row" key={key}>
                      <dt className="mufy-panel-key">{key}</dt>
                      <dd className="mufy-panel-value">{renderPanelValue(panel[key])}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <pre className="char-create-json-view">{jsonToText(panel)}</pre>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function renderPanelValue(value: unknown): ReactNode {
  if (typeof value === "string") {
    if (value.includes("\n") || value.length > 60) {
      return <pre className="char-create-json-view mufy-panel-pre">{value}</pre>;
    }
    return <span>{value}</span>;
  }
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return <span>{jsonToText(value)}</span>;
  }
  return <pre className="char-create-json-view mufy-panel-pre">{jsonToText(value)}</pre>;
}
