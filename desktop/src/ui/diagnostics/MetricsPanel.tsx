import { useState } from "react";

import type { TurnMetric } from "../../contracts/protocol";
import {
  formatDurationMs,
  formatMetricNumber,
  formatOptionalText,
  formatTimestamp,
  formatTurnKind,
  formatTurnStatus,
  NO_DATA,
} from "./format";

export type DiagnosticsLoadState = "idle" | "loading" | "loaded" | "failed";

export interface MetricsPanelProps {
  /** metrics.query 结果。null/缺省 = 未读取或无数据；[] = 服务端返回真实零条。 */
  metrics?: TurnMetric[] | null;
  state?: DiagnosticsLoadState;
  /** 查询失败原文；如实上屏，不吞异常。 */
  error?: string | null;
  /** 分页游标；为 null 表示没有更多。 */
  nextCursor?: string | null;
  /** 显式只读查询（打开诊断抽屉即用户显式请求）。 */
  onLoad?: () => void;
  onLoadMore?: () => void;
}

function MetricRow({ metric }: { metric: TurnMetric }) {
  const [open, setOpen] = useState(false);
  const failure =
    metric.status === "failed"
      ? {
          type: metric.failure_type ?? "未报告失败类型",
          message: metric.failure_message ?? "未报告失败信息",
        }
      : null;

  return (
    <>
      <tr className={`diag-metric-row is-${metric.status}`} data-testid={`diag-metric-${metric.metric_id}`}>
        <td>
          <button
            type="button"
            className="diag-metric-toggle"
            aria-expanded={open}
            onClick={() => setOpen((current) => !current)}
          >
            {open ? "收起" : "详情"}
          </button>
          <span className="diag-metric-kind">{formatTurnKind(metric.turn_kind)}</span>
          <span className="diag-metric-id">{metric.metric_id}</span>
        </td>
        <td>{metric.origin === "remote" ? `手机远程${metric.remote_device_name ? ` · ${metric.remote_device_name}` : ""}` : "桌面"}</td>
        <td>
          {metric.provider ?? NO_DATA}
          <span className="diag-metric-sub">
            {metric.model ?? NO_DATA} · {metric.engine_type ?? NO_DATA} ·{" "}
            {metric.reasoning_effort ?? NO_DATA}
          </span>
        </td>
        <td>
          <span className={`diag-status diag-status-${metric.status}`}>{formatTurnStatus(metric.status)}</span>
        </td>
        <td>
          {formatDurationMs(metric.duration_ms)}
          <span className="diag-metric-sub">
            首事件 {formatTimestamp(metric.first_event_at)} · 完成 {formatTimestamp(metric.completed_at)}
          </span>
        </td>
        <td data-testid={`diag-tokens-${metric.metric_id}`}>
          入 {formatMetricNumber(metric.input_tokens)} / 出 {formatMetricNumber(metric.output_tokens)} / 合{" "}
          {formatMetricNumber(metric.total_tokens)}
        </td>
        <td data-testid={`diag-toolrounds-${metric.metric_id}`}>{formatMetricNumber(metric.tool_rounds)}</td>
        <td>{formatMetricNumber(metric.compression_count)}</td>
        <td>{formatMetricNumber(metric.approval_count)}</td>
        <td className={failure ? "diag-metric-failure" : undefined}>
          {failure ? (
            <>
              <span>{failure.type}</span>
              <span className="diag-metric-sub">{failure.message}</span>
            </>
          ) : (
            "—"
          )}
        </td>
      </tr>
      {open ? (
        <tr className="diag-metric-detail-row" data-testid={`diag-metric-detail-${metric.metric_id}`}>
          <td colSpan={10}>
            <dl className="diag-metric-detail">
              <div><dt>metric_id</dt><dd>{metric.metric_id}</dd></div>
              <div><dt>account_id</dt><dd>{metric.account_id}</dd></div>
              <div><dt>project_id</dt><dd>{metric.project_id}</dd></div>
              <div><dt>conversation_id</dt><dd>{metric.conversation_id}</dd></div>
              <div><dt>pair_id</dt><dd>{metric.pair_id}</dd></div>
              <div><dt>character_ref</dt><dd>{metric.character_ref}</dd></div>
              <div><dt>turn_kind</dt><dd>{metric.turn_kind} ({formatTurnKind(metric.turn_kind)})</dd></div>
              <div><dt>turn_id</dt><dd>{metric.turn_id}</dd></div>
              <div><dt>task_id</dt><dd>{formatOptionalText(metric.task_id)}</dd></div>
              <div><dt>engine_turn_id</dt><dd>{formatOptionalText(metric.engine_turn_id)}</dd></div>
              <div><dt>provider</dt><dd>{formatOptionalText(metric.provider)}</dd></div>
              <div><dt>model</dt><dd>{formatOptionalText(metric.model)}</dd></div>
              <div><dt>engine_type</dt><dd>{formatOptionalText(metric.engine_type)}</dd></div>
              <div><dt>reasoning_effort</dt><dd>{formatOptionalText(metric.reasoning_effort)}</dd></div>
              <div><dt>status</dt><dd>{metric.status} ({formatTurnStatus(metric.status)})</dd></div>
              <div><dt>started_at</dt><dd>{formatTimestamp(metric.started_at)}</dd></div>
              <div><dt>first_event_at</dt><dd>{formatTimestamp(metric.first_event_at)}</dd></div>
              <div><dt>completed_at</dt><dd>{formatTimestamp(metric.completed_at)}</dd></div>
              <div><dt>duration_ms</dt><dd>{formatMetricNumber(metric.duration_ms)}</dd></div>
              <div><dt>input_tokens</dt><dd>{formatMetricNumber(metric.input_tokens)}</dd></div>
              <div><dt>output_tokens</dt><dd>{formatMetricNumber(metric.output_tokens)}</dd></div>
              <div><dt>total_tokens</dt><dd>{formatMetricNumber(metric.total_tokens)}</dd></div>
              <div><dt>tool_rounds</dt><dd>{formatMetricNumber(metric.tool_rounds)}</dd></div>
              <div><dt>compression_count</dt><dd>{formatMetricNumber(metric.compression_count)}</dd></div>
              <div><dt>approval_count</dt><dd>{formatMetricNumber(metric.approval_count)}</dd></div>
              <div><dt>failure_type</dt><dd>{formatOptionalText(metric.failure_type)}</dd></div>
              <div><dt>failure_message</dt><dd>{formatOptionalText(metric.failure_message)}</dd></div>
              <div><dt>origin</dt><dd>{metric.origin}</dd></div>
              <div><dt>remote_device_key</dt><dd>{formatOptionalText(metric.remote_device_key)}</dd></div>
              <div><dt>remote_device_name</dt><dd>{formatOptionalText(metric.remote_device_name)}</dd></div>
            </dl>
          </td>
        </tr>
      ) : null}
    </>
  );
}

/**
 * V0.3.9 V03 指标视图：消费 metrics.query 结果，渲染 TurnMetric 全字段。
 * 未观测字段（null）显示「无数据」，真实零值显示 0；缺键由适配层直接报错。
 * 空结果分两种：null = 尚未读取/无数据，[] = 服务端返回真实零条。
 */
export function MetricsPanel({
  metrics,
  state = "idle",
  error,
  nextCursor,
  onLoad,
  onLoadMore,
}: MetricsPanelProps) {
  return (
    <section className="diag-panel" aria-label="指标">
      <div className="diag-panel-head">
        <div className="diag-panel-title">
          <h3>回合指标</h3>
          <p className="diag-panel-hint">
            metrics.query 显式只读查询。未观测字段显示「无数据」，真实零值显示 0；应用不估算 token。
          </p>
        </div>
        {onLoad ? (
          <button type="button" className="btn btn-outline diag-btn" onClick={onLoad}>
            {state === "loading" ? "正在读取…" : metrics ? "刷新指标" : "读取指标"}
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="field-error" role="alert" data-testid="diag-metrics-error">
          指标读取失败：{error}
        </p>
      ) : null}

      {state === "loading" && !metrics ? (
        <p className="diag-panel-hint" role="status">
          正在读取指标…
        </p>
      ) : null}

      {metrics === null || metrics === undefined ? (
        state === "loading" ? null : (
          <p className="diag-panel-hint" role="status" data-testid="diag-metrics-nodata">
            {state === "failed" ? "指标未读取到，错误见上方。" : "无数据：尚未读取指标。"}
          </p>
        )
      ) : metrics.length === 0 ? (
        <p className="diag-panel-hint" role="status" data-testid="diag-metrics-empty">
          查询返回 0 条指标记录。
        </p>
      ) : (
        <>
          <p className="diag-panel-hint" role="status" data-testid="diag-metrics-count">
            共 {metrics.length} 条指标记录。
          </p>
          <div className="diag-table-wrap">
            <table className="diag-table">
              <thead>
                <tr>
                  <th scope="col">回合</th>
                  <th scope="col">来源</th>
                  <th scope="col">供应商 / 模型</th>
                  <th scope="col">状态</th>
                  <th scope="col">时长</th>
                  <th scope="col">tokens（入/出/合）</th>
                  <th scope="col">工具轮次</th>
                  <th scope="col">压缩</th>
                  <th scope="col">审批</th>
                  <th scope="col">失败</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map((metric) => (
                  <MetricRow key={metric.metric_id} metric={metric} />
                ))}
              </tbody>
            </table>
          </div>
          {nextCursor ? (
            onLoadMore ? (
              <button type="button" className="btn btn-outline diag-btn" onClick={onLoadMore}>
                加载更多（cursor: {nextCursor}）
              </button>
            ) : (
              <p className="diag-panel-hint">还有更多记录（cursor: {nextCursor}），当前未提供加载动作。</p>
            )
          ) : null}
        </>
      )}
    </section>
  );
}
