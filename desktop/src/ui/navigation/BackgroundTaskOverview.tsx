import type { HarnessActions } from "../../contracts/actions";
import type { ProjectViewModel } from "../../contracts/view-models";
import { CloseIcon } from "../../assets/icons/icons";

export interface BackgroundTaskOverviewItem {
  taskId?: string;
  projectId: string;
  projectName: string;
  conversationId: string;
  conversationTitle: string;
  isRunning: boolean;
  engineTurnId?: string | null;
}

export interface BackgroundTaskOverviewProps {
  projects: ProjectViewModel[];
  actions: HarnessActions;
  isOpen: boolean;
  onClose: () => void;
  /** 待真实接线：待 logic store/presenter 暴露全量 active_tasks 后直接传入详细任务列表 */
  activeTasksDetail?: BackgroundTaskOverviewItem[];
}

export function TaskOverviewIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" {...props}>
      <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

/**
 * V0.3.9 V01：跨聊天后台任务总览组件。
 * 消费 presenters 已有 isBusy / activeTaskCount，展示跨项目/聊天的后台运行任务，
 * 并提供一键跳转至对应会话的入口。
 */
export function BackgroundTaskOverview({
  projects,
  actions,
  isOpen,
  onClose,
  activeTasksDetail,
}: BackgroundTaskOverviewProps) {
  if (!isOpen) return null;

  // 聚合各项目下正在运行的会话（消费 presenters.isBusy / conversation.isRunning）
  const runningTasks: BackgroundTaskOverviewItem[] =
    activeTasksDetail ??
    projects.flatMap((project) =>
      (project.conversations ?? [])
        .filter((conv) => Boolean((conv as unknown as { isRunning?: boolean }).isRunning))
        .map((conv) => ({
          projectId: project.project_id,
          projectName: project.name,
          conversationId: conv.conversation_id,
          conversationTitle: conv.title,
          isRunning: true,
        })),
    );

  const totalActive =
    projects.reduce((sum, p) => sum + (p.activeTaskCount || 0), 0) || runningTasks.length;

  return (
    <div className="task-overview-backdrop" onClick={onClose} role="presentation">
      <div
        className="task-overview-panel"
        data-testid="task-overview-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-overview-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="task-overview-header">
          <div className="task-overview-header-title">
            <span className="task-overview-pulse-dot" aria-hidden />
            <h2 id="task-overview-title">跨聊天后台任务总览</h2>
            <span className="task-overview-count-badge">{totalActive} 个运行中</span>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="关闭总览"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="task-overview-body">
          {runningTasks.length === 0 ? (
            <div className="task-overview-empty">当前没有正在运行的后台任务</div>
          ) : (
            <div className="task-overview-list">
              {runningTasks.map((task) => (
                <div
                  key={`${task.projectId}-${task.conversationId}`}
                  className="task-overview-item"
                  data-testid="task-overview-item"
                >
                  <div className="task-overview-item-info">
                    <div className="task-overview-project-tag">{task.projectName}</div>
                    <div className="task-overview-conv-title">{task.conversationTitle}</div>
                    <span className="task-overview-status-tag">运行中</span>
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      void actions.selectProject(task.projectId);
                      void actions.openConversationTab(task.conversationId);
                      onClose();
                    }}
                  >
                    前往该聊天
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
