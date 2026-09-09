import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { HarnessActions } from "../../contracts/actions";
import type { NavigationViewModel, ProjectViewModel } from "../../contracts/view-models";
import { HeartIcon, PlusIcon, WarningIcon } from "../../assets/icons/icons";
import { TaskOverviewIcon } from "./BackgroundTaskOverview";

interface ProjectRailProps {
  navigation: NavigationViewModel;
  actions: HarnessActions;
  onOpenTaskOverview?: () => void;
}

function projectBadgeText(name: string): string {
  const trimmed = name.trim();
  if (trimmed.length <= 2) return trimmed || "?";
  return `${trimmed.charAt(0)}${trimmed.charAt(1)}`;
}

function ProjectRailItem({
  project,
  actions,
}: {
  project: ProjectViewModel;
  actions: HarnessActions;
}) {
  return (
    <button
      type="button"
      className={`rail-item${project.isCurrent ? " is-current" : ""}${project.isBusy ? " is-busy" : ""}`}
      onClick={() => void actions.selectProject(project.project_id)}
      title={project.path_available ? project.name : `${project.name}（文件夹不可用）`}
      aria-label={project.name}
      aria-current={project.isCurrent ? "page" : undefined}
    >
      <span className="project-badge">
        <span className="project-badge-initial">{projectBadgeText(project.name)}</span>
        {project.isBusy ? <span className="badge-busy-dot" aria-hidden /> : null}
        {!project.path_available ? (
          <span className="badge-alert" aria-label="路径不可用">
            <WarningIcon />
          </span>
        ) : null}
      </span>
    </button>
  );
}

/** 56px 项目轨道：后台任务总览、角色库、项目徽章、新建项目。 */
export function ProjectRail({ navigation, actions, onOpenTaskOverview }: ProjectRailProps) {
  const totalActiveTasks = navigation.projects.reduce(
    (sum, p) => sum + (p.activeTaskCount || (p.isBusy ? 1 : 0)),
    0,
  );

  const shouldVirtualize = navigation.projects.length > 30;
  const projectsScrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: navigation.projects.length,
    getScrollElement: () => projectsScrollRef.current,
    estimateSize: () => 48,
    overscan: 5,
    getItemKey: (index) => navigation.projects[index]?.project_id ?? index,
  });

  return (
    <div className="project-rail" role="navigation" aria-label="项目轨道">
      <button
        type="button"
        className={`rail-item${totalActiveTasks > 0 ? " is-busy" : ""}`}
        title={totalActiveTasks > 0 ? `后台任务总览（${totalActiveTasks} 个进行中）` : "后台任务总览"}
        aria-label="后台任务总览"
        onClick={() => onOpenTaskOverview?.()}
        data-testid="rail-btn-task-overview"
      >
        <span className="project-badge">
          <TaskOverviewIcon />
          {totalActiveTasks > 0 ? <span className="badge-busy-dot" aria-hidden /> : null}
        </span>
      </button>

      <button
        type="button"
        className="rail-item"
        title="角色库"
        aria-label="角色库"
        onClick={() => void actions.openCharacterLibrary()}
      >
        <span className="project-badge">
          <HeartIcon />
        </span>
      </button>

      <div className="rail-divider" />

      <div className="rail-caption">项目</div>

      {shouldVirtualize ? (
        <div className="rail-projects-scroll" ref={projectsScrollRef}>
          <div
            className="rail-projects-virtual"
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              position: "relative",
              width: "100%",
            }}
          >
            {virtualizer.getVirtualItems().map((vItem) => {
              const project = navigation.projects[vItem.index];
              if (!project) return null;
              return (
                <div
                  key={vItem.key}
                  ref={virtualizer.measureElement}
                  data-index={vItem.index}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    display: "flex",
                    justifyContent: "center",
                    transform: `translateY(${vItem.start}px)`,
                  }}
                >
                  <ProjectRailItem project={project} actions={actions} />
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        navigation.projects.map((project) => (
          <ProjectRailItem key={project.project_id} project={project} actions={actions} />
        ))
      )}

      <div className="rail-spacer" />

      <button
        type="button"
        className="rail-item rail-item-new"
        title="新建项目"
        aria-label="新建项目"
        onClick={() => void actions.createProject()}
      >
        <span className="project-badge">
          <PlusIcon />
        </span>
        <span className="rail-new-label">新建项目</span>
      </button>
    </div>
  );
}

