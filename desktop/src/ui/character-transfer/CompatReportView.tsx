import type { CompatReportPayload } from "../../contracts/protocol";
import { groupNotExecuted } from "./compatView";

import "./character-transfer.css";

/* ------------------------------------------------------------------ *
 * V0.3.7 兼容报告完整视图（V6）：CompatReport 六字段分组呈现，
 * not_executed 按冻结 §11 类别再分组。导入流程、导出预览与角色详情页共用。
 * ------------------------------------------------------------------ */

interface CompatReportViewProps {
  report: CompatReportPayload;
  /** 可选标题；缺省不渲染标题行。 */
  title?: string;
  className?: string;
  /** 紧凑变体：更小的字号与间距，供角色详情等空间有限的挂载点使用。 */
  compact?: boolean;
}

function ReportGroup(props: {
  label: string;
  items: readonly string[];
  tone?: "default" | "warning" | "danger";
}) {
  if (!props.items.length) return null;
  return (
    <div className="xfer-report-section">
      <label
        className="xfer-muted"
        style={
          props.tone === "warning"
            ? { color: "var(--warning)" }
            : props.tone === "danger"
              ? { color: "var(--danger)" }
              : undefined
        }
      >
        {props.label}
      </label>
      <ul className="xfer-report-list">
        {props.items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function CompatReportView({ report, title, className, compact = false }: CompatReportViewProps) {
  const notExecutedGroups = groupNotExecuted(report.not_executed);
  const isEmpty =
    !report.applied.length &&
    !report.preserved.length &&
    !report.not_executed.length &&
    !report.normalized_from_root.length &&
    !report.warnings.length &&
    !report.errors.length;

  const rootClass = [
    "xfer-compat-report",
    compact ? "xfer-compat-report-compact" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={rootClass}>
      {title && <label className="xfer-muted">{title}</label>}
      {isEmpty ? (
        <div className="xfer-report-empty">无兼容报告项</div>
      ) : (
        <>
          <ReportGroup label="已应用" items={report.applied} />
          <ReportGroup label="已保留（原样存储）" items={report.preserved} />
          {report.not_executed.length > 0 && (
            <div className="xfer-report-section">
              <label className="xfer-muted">未执行（存而不运行）</label>
              <div className="xfer-report-subgroups">
                {notExecutedGroups.map((group) => (
                  <div key={group.key} className="xfer-report-subgroup">
                    <span className="xfer-report-subgroup-label">
                      {group.label}（{group.items.length}）
                    </span>
                    <ul className="xfer-report-list">
                      {group.items.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}
          <ReportGroup label="根级字段回退（已归一化）" items={report.normalized_from_root} />
          <ReportGroup label="警告" items={report.warnings} tone="warning" />
          <ReportGroup label="错误" items={report.errors} tone="danger" />
        </>
      )}
    </div>
  );
}
