import { useState } from "react";

import { formatCharRange, formatMemoryInjected, formatOptionalText, formatTimestamp } from "./format";
import type { DiagnosticsLoadState } from "./MetricsPanel";
import type { PromptAssemblyView } from "./types";

interface HiddenContentState {
  status: "loading" | "loaded" | "failed";
  content: string | null;
  error: string | null;
}

export interface PromptAssemblyPanelProps {
  /** diagnostics.prompt_assembly 结果（已由 adaptPromptAssembly 适配）。null = 未读取。 */
  assembly?: PromptAssemblyView | null;
  state?: DiagnosticsLoadState;
  /** 查询失败原文；如实上屏。 */
  error?: string | null;
  onLoad?: () => void;
  /**
   * 用户显式请求隐藏原文。未提供时不渲染按钮（不谎称支持）。
   * 返回的原文只留在本组件内部状态里，抽屉关闭即随组件卸载清除。
   */
  onRequestHiddenContent?: (moduleName: string) => Promise<string>;
}

/**
 * V0.3.9 V03 提示词装配视图：模块名、字符范围、hash、摘要与记忆是否注入。
 * 隐藏原文只在用户点「显示原文」后请求并展示；普通聊天不出现该内容，
 * 关闭抽屉（组件卸载）即清除，不做任何缓存或跨会话保留。
 */
export function PromptAssemblyPanel({
  assembly,
  state = "idle",
  error,
  onLoad,
  onRequestHiddenContent,
}: PromptAssemblyPanelProps) {
  const [hidden, setHidden] = useState<Record<string, HiddenContentState>>({});

  const requestHidden = async (moduleName: string) => {
    if (!onRequestHiddenContent) return;
    setHidden((current) => ({
      ...current,
      [moduleName]: { status: "loading", content: null, error: null },
    }));
    try {
      const content = await onRequestHiddenContent(moduleName);
      setHidden((current) => ({
        ...current,
        [moduleName]: { status: "loaded", content, error: null },
      }));
    } catch (requestError) {
      // Let It Fail：隐藏内容请求失败原文上屏。
      setHidden((current) => ({
        ...current,
        [moduleName]: {
          status: "failed",
          content: null,
          error: requestError instanceof Error ? requestError.message : String(requestError),
        },
      }));
    }
  };

  const dropHidden = (moduleName: string) => {
    setHidden((current) => {
      const next = { ...current };
      delete next[moduleName];
      return next;
    });
  };

  return (
    <section className="diag-panel" aria-label="提示词装配">
      <div className="diag-panel-head">
        <div className="diag-panel-title">
          <h3>提示词装配</h3>
          <p className="diag-panel-hint">
            diagnostics.prompt_assembly 显式只读查询。默认只返回模块名、字符范围、hash、摘要与记忆是否注入；
            隐藏原文需要你在这里显式请求，关闭抽屉即清除。
          </p>
        </div>
        {onLoad ? (
          <button type="button" className="btn btn-outline diag-btn" onClick={onLoad}>
            {state === "loading" ? "正在读取…" : assembly ? "刷新装配" : "读取装配"}
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="field-error" role="alert" data-testid="diag-assembly-error">
          装配诊断读取失败：{error}
        </p>
      ) : null}

      {assembly === null || assembly === undefined ? (
        state === "loading" ? (
          <p className="diag-panel-hint" role="status">
            正在读取装配诊断…
          </p>
        ) : (
          <p className="diag-panel-hint" role="status" data-testid="diag-assembly-nodata">
            {state === "failed" ? "装配诊断未读取到，错误见上方。" : "无数据：尚未读取装配诊断。"}
          </p>
        )
      ) : (
        <>
          <p className="diag-panel-hint" role="status" data-testid="diag-assembly-meta">
            共 {assembly.modules.length} 个模块
            {assembly.conversation_id ? ` · conversation_id: ${assembly.conversation_id}` : " · conversation_id：无数据"}
            {assembly.generated_at ? ` · 生成时间 ${formatTimestamp(assembly.generated_at)}` : " · 生成时间：无数据"}
          </p>

          {assembly.modules.length === 0 ? (
            <p className="diag-panel-hint" role="status" data-testid="diag-assembly-empty">
              服务端返回 0 个装配模块。
            </p>
          ) : (
            <ul className="diag-module-list">
              {assembly.modules.map((module) => {
                const hiddenState = hidden[module.name];
                return (
                  <li
                    key={module.name}
                    className="diag-module"
                    data-testid={`diag-module-${module.name}`}
                  >
                    <div className="diag-module-head">
                      <span className="diag-module-name">{module.name}</span>
                      <span className="diag-module-fact">字符范围 {formatCharRange(module.char_start, module.char_end)}</span>
                      <span className="diag-module-fact">hash {formatOptionalText(module.hash)}</span>
                      <span
                        className={`diag-module-memory${module.memory_injected ? " is-injected" : ""}`}
                      >
                        记忆 {formatMemoryInjected(module.memory_injected)}
                      </span>
                    </div>
                    <p className="diag-module-summary">{formatOptionalText(module.summary)}</p>

                    {onRequestHiddenContent ? (
                      <div className="diag-module-actions">
                        {hiddenState?.status === "loaded" ? (
                          <button
                            type="button"
                            className="btn btn-outline diag-btn"
                            onClick={() => dropHidden(module.name)}
                          >
                            隐藏原文
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-outline diag-btn"
                            disabled={hiddenState?.status === "loading"}
                            onClick={() => void requestHidden(module.name)}
                            data-testid={`diag-module-hidden-btn-${module.name}`}
                          >
                            {hiddenState?.status === "loading" ? "正在请求原文…" : "显示原文"}
                          </button>
                        )}
                      </div>
                    ) : null}

                    {hiddenState?.status === "loaded" ? (
                      <pre
                        className="diag-module-hidden"
                        data-testid={`diag-module-hidden-${module.name}`}
                      >
                        {hiddenState.content ?? ""}
                      </pre>
                    ) : null}
                    {hiddenState?.status === "failed" ? (
                      <p className="field-error" role="alert">
                        原文请求失败：{hiddenState.error}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}

          {assembly.diagnostics.length > 0 ? (
            <div className="diag-assembly-diagnostics" data-testid="diag-assembly-diagnostics">
              <h4>服务端诊断</h4>
              <ul>
                {assembly.diagnostics.map((line, index) => (
                  <li key={`${index}-${line}`}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
