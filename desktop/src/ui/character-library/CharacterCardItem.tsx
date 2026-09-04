import type { CharacterCardSummaryView } from "../../contracts/view-models";
import {
  AlertTriangleIcon,
  ArchiveIcon,
  CompatCheckIcon,
  DeleteIcon,
  DuplicateIcon,
  EditIcon,
  ExportIcon,
  EyeIcon,
  MicrophoneIcon,
  RestoreIcon,
  UserCheckIcon,
} from "./CharacterIcons";
import { formatUpdatedAt } from "./types";

interface CharacterCardItemProps {
  card: CharacterCardSummaryView;
  onUse: (cardId: string) => void;
  onEdit: (cardId: string) => void;
  onDuplicate: (cardId: string) => void;
  onExport: (card: CharacterCardSummaryView) => void;
  onArchive: (cardId: string) => void;
  onDeleteRequest: (card: CharacterCardSummaryView) => void;
  onViewError: (card: CharacterCardSummaryView) => void;
  onViewCompat?: (card: CharacterCardSummaryView) => void;
  onConfigureVoice?: (cardId: string) => void;
}

export function CharacterCardItem({
  card,
  onUse,
  onEdit,
  onDuplicate,
  onExport,
  onArchive,
  onDeleteRequest,
  onViewError,
  onViewCompat,
  onConfigureVoice,
}: CharacterCardItemProps) {
  const isInvalid = card.state === "invalid";
  const isDraft = card.state === "draft";
  const isArchived = card.archived;
  const isReadOnly = card.readOnly;

  const firstChar = card.name.trim().charAt(0) || "角";

  // 来源文本推导
  let sourceText = "创建";
  if (card.source === "builtin") {
    sourceText = "内置 · 只读";
  } else if (card.source === "imported_json") {
    sourceText = "导入 (JSON)";
  } else if (card.source === "imported_png") {
    sourceText = "导入 (PNG)";
  } else if (card.source === "user_created") {
    sourceText = "创建";
  }

  // 音色状态推导
  let voiceDotClass = "char-dot-muted";
  let voiceText = isReadOnly ? "不适用音色" : "音色未配置";
  if (card.voiceState === "voice_ready") {
    voiceDotClass = "char-dot-ok";
    voiceText = "音色已绑定";
  } else if (card.voiceState === "voice_creating") {
    voiceDotClass = "char-dot-progress";
    voiceText = "音色创建中";
  } else if (card.voiceState === "voice_failed") {
    voiceDotClass = "char-dot-danger";
    voiceText = "音色创建失败";
  }

  const voiceConfigurable = !isReadOnly && !isInvalid && onConfigureVoice !== undefined;

  return (
    <article
      className={`char-card ${isArchived ? "is-archived" : ""} ${isInvalid ? "is-invalid" : ""}`}
      data-testid={`char-card-${card.cardId}`}
    >
      {/* 悬停快捷操作栏 */}
      <div className="char-card-actions" role="toolbar" aria-label={`${card.name} 操作`}>
        {isReadOnly ? (
          <>
            <button
              type="button"
              className="char-icon-btn"
              title="查看"
              aria-label={`查看${card.name}`}
              onClick={() => onEdit(card.cardId)}
            >
              <EyeIcon />
            </button>
            {onViewCompat ? (
              <button
                type="button"
                className="char-icon-btn"
                title="兼容性"
                aria-label={`查看${card.name}的兼容性`}
                onClick={() => onViewCompat(card)}
              >
                <CompatCheckIcon />
              </button>
            ) : null}
          </>
        ) : isInvalid ? (
          <>
            <button
              type="button"
              className="char-icon-btn"
              title="查看错误"
              aria-label="查看导入错误"
              onClick={() => onViewError(card)}
            >
              <AlertTriangleIcon />
            </button>
            <button
              type="button"
              className="char-icon-btn danger"
              title="删除"
              aria-label={`删除${card.name}`}
              onClick={() => onDeleteRequest(card)}
            >
              <DeleteIcon />
            </button>
          </>
        ) : (
          <>
            {!card.active ? (
              <button
                type="button"
                className="char-icon-btn"
                title="使用该角色开始对话"
                aria-label={`使用${card.name}`}
                onClick={() => onUse(card.cardId)}
              >
                <UserCheckIcon />
              </button>
            ) : null}
            {voiceConfigurable ? (
              <button
                type="button"
                className="char-icon-btn"
                title="配置音色"
                aria-label={`配置${card.name}的音色`}
                onClick={() => onConfigureVoice?.(card.cardId)}
              >
                <MicrophoneIcon />
              </button>
            ) : null}
            <button
              type="button"
              className="char-icon-btn"
              title="编辑"
              aria-label={`编辑${card.name}`}
              onClick={() => onEdit(card.cardId)}
            >
              <EditIcon />
            </button>
            {onViewCompat ? (
              <button
                type="button"
                className="char-icon-btn"
                title="兼容性"
                aria-label={`查看${card.name}的兼容性`}
                onClick={() => onViewCompat(card)}
              >
                <CompatCheckIcon />
              </button>
            ) : null}
            <button
              type="button"
              className="char-icon-btn"
              title="复制"
              aria-label={`复制${card.name}`}
              onClick={() => onDuplicate(card.cardId)}
            >
              <DuplicateIcon />
            </button>
            <button
              type="button"
              className="char-icon-btn"
              title="导出"
              aria-label={`导出${card.name}`}
              onClick={() => onExport(card)}
            >
              <ExportIcon />
            </button>
            {isArchived ? (
              <button
                type="button"
                className="char-icon-btn"
                title="恢复"
                aria-label={`恢复${card.name}`}
                onClick={() => onArchive(card.cardId)}
              >
                <RestoreIcon />
              </button>
            ) : (
              <button
                type="button"
                className="char-icon-btn"
                title="归档"
                aria-label={`归档${card.name}`}
                onClick={() => onArchive(card.cardId)}
              >
                <ArchiveIcon />
              </button>
            )}
            <button
              type="button"
              className="char-icon-btn danger"
              title="删除"
              aria-label={`删除${card.name}`}
              onClick={() => onDeleteRequest(card)}
            >
              <DeleteIcon />
            </button>
          </>
        )}
      </div>

      {/* 头部信息 */}
      <div className="char-card-header">
        <div
          className={`char-avatar ${isInvalid ? "avatar-invalid" : card.hasAvatar ? "avatar-geo" : ""}`}
        >
          {isInvalid ? <AlertTriangleIcon style={{ width: 22, height: 22 }} /> : firstChar}
        </div>
        <div className="char-card-title-group">
          <div className="char-card-name-row">
            <h3 className="char-card-name">{card.name}</h3>
            {card.active ? <span className="char-pill char-pill-accent">使用中</span> : null}
            {isDraft ? <span className="char-pill">草稿</span> : null}
            {isArchived ? <span className="char-pill">已归档</span> : null}
            {isInvalid ? <span className="char-pill char-pill-danger">导入失败</span> : null}
          </div>
          <div className="char-card-meta">
            {isInvalid ? "导入失败 · 未创建角色" : sourceText}
          </div>
        </div>
      </div>

      {/* 提示与标签 */}
      {isInvalid ? (
        <p className="char-card-meta" style={{ color: "var(--danger)", margin: 0 }}>
          解析中断：文件格式或元数据损坏。可移除后重新导入。
        </p>
      ) : !card.hasAvatar && !isReadOnly ? (
        <div className="char-card-tags">
          <span className="char-pill char-pill-warn">
            <AlertTriangleIcon style={{ width: 12, height: 12 }} />
            缺头像
          </span>
        </div>
      ) : null}

      {/* 底部信息 */}
      <div className="char-card-foot">
        <button
          type="button"
          className={`char-voice-info ${voiceConfigurable ? "char-voice-configurable" : ""}`}
          onClick={() => voiceConfigurable && onConfigureVoice?.(card.cardId)}
          disabled={!voiceConfigurable}
          title={voiceConfigurable ? "点击配置音色" : voiceText}
          aria-label={voiceConfigurable ? `配置${card.name}的音色` : undefined}
        >
          <span className={`char-dot ${voiceDotClass}`} />
          <span>{voiceText}</span>
        </button>
        <span className="char-lib-meta">{formatUpdatedAt(card.updatedAt)}</span>
      </div>
    </article>
  );
}
