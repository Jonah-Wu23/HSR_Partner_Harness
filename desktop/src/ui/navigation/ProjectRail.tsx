import type { HarnessActions } from "../../contracts/actions";
import type { NavigationViewModel } from "../../contracts/view-models";
import { PlusIcon, RecordVoiceIcon, WarningIcon } from "../../assets/icons/icons";

interface ProjectRailProps {
  navigation: NavigationViewModel;
  actions: HarnessActions;
}

/** 56px 项目轨道：日常聊天入口、项目徽章、新建项目。 */
export function ProjectRail({ navigation, actions }: ProjectRailProps) {
  return (
    <div className="project-rail" role="navigation" aria-label="项目轨道">
      <button
        type="button"
        className="rail-item"
        disabled
        title="日常聊天将在后续版本接入"
        aria-label="日常聊天（即将推出）"
      >
        <span className="project-badge">
          <RecordVoiceIcon />
        </span>
      </button>

      <div className="rail-divider" />

      {navigation.projects.map((project) => (
        <button
          key={project.project_id}
          type="button"
          className={`rail-item${project.isCurrent ? " is-current" : ""}${project.isBusy ? " is-busy" : ""}`}
          onClick={() => void actions.selectProject(project.project_id)}
          title={project.path_available ? project.name : `${project.name}（文件夹不可用）`}
          aria-label={project.name}
          aria-current={project.isCurrent ? "page" : undefined}
        >
          <span className="project-badge">
            <span className="project-badge-initial">{project.name.trim().charAt(0) || "?"}</span>
            {project.isBusy ? <span className="badge-busy-dot" aria-hidden /> : null}
            {!project.path_available ? (
              <span className="badge-alert" aria-label="路径不可用">
                <WarningIcon />
              </span>
            ) : null}
          </span>
        </button>
      ))}

      <div className="rail-spacer" />

      <button
        type="button"
        className="rail-item"
        disabled
        title="新建项目需要选择文件夹，待逻辑侧接入文件对话框"
        aria-label="新建项目（待接入）"
      >
        <span className="project-badge">
          <PlusIcon />
        </span>
      </button>
    </div>
  );
}
