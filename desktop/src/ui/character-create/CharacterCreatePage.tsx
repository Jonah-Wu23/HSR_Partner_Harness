import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { CharacterCreateViewModel } from "../../contracts/view-models";
import type { CharacterCardState, CardGetResult } from "../../contracts/protocol";
import type { FileFilter } from "../../services/backend";
import { BasicInfoSection } from "./BasicInfoSection";
import { PersonalitySection } from "./PersonalitySection";
import { CharacterLivePreview } from "./CharacterLivePreview";
import { AdvancedEditorPanel } from "./AdvancedEditorPanel";
import { SaveStatusBadge } from "./SaveStatusBadge";
import { AlertCircleIcon, ArrowLeftIcon, SaveIcon } from "./icons";
import {
  buildCardPayload,
  extractFormData,
  isCardPublished,
  type CharacterFormData,
  type CreateMode,
  type PublishStatus,
  type SaveStatus,
} from "./types";
import "./CharacterCreate.css";

interface CharacterCreatePageProps {
  vm: CharacterCreateViewModel;
  actions: HarnessActions;
  /** V0.3.5：Tauri 文件选择桥（头像需要真实绝对路径）；浏览器 mock 环境缺省，
      此时退化为 HTML 文件选择（仅能拿到文件名，见 BasicInfoSection 注释）。 */
  onPickFile?: (options?: { title?: string; filters?: FileFilter[] }) => Promise<string | null>;
}

function formatTime(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function CharacterCreatePage({ vm, actions, onPickFile }: CharacterCreatePageProps) {
  const [formData, setFormData] = useState<CharacterFormData>(() => extractFormData(vm.card));
  const [currentCardId, setCurrentCardId] = useState<string | null>(vm.cardId);
  const [cardDetails, setCardDetails] = useState<CardGetResult | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>(() => (vm.cardId ? "saved" : "idle"));
  const [lastSavedTime, setLastSavedTime] = useState<string | null>(() =>
    vm.cardId ? formatTime() : null,
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [mode, setMode] = useState<CreateMode>("quick");
  const [publishStatus, setPublishStatus] = useState<PublishStatus>("idle");
  const [publishError, setPublishError] = useState<string | null>(null);
  // 整卡 v3 JSON 草稿：世界书与 mufy 高级设定的编辑先合并到这里，再随 card.update 整卡提交。
  const [cardJson, setCardJson] = useState<Record<string, unknown> | null>(() => vm.card);

  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestFormDataRef = useRef(formData);
  latestFormDataRef.current = formData;
  const currentCardIdRef = useRef(currentCardId);
  currentCardIdRef.current = currentCardId;
  const cardJsonRef = useRef(cardJson);
  cardJsonRef.current = cardJson;
  const isSavingRef = useRef(false);

  // 当 vm.card 外部变更时水合；同时拉取服务端 state/avatar 权威状态。
  useEffect(() => {
    setCardJson(vm.card);
    if (vm.card) {
      setFormData(extractFormData(vm.card));
      setCurrentCardId(vm.cardId);
      setSaveStatus("saved");
      setLastSavedTime(formatTime());
      setPublishStatus("idle");
      setPublishError(null);
    }
  }, [vm.card, vm.cardId]);

  // 拉取服务端权威状态（state/avatar）：vm 进入或本地创建 draft 后都触发。
  useEffect(() => {
    if (!currentCardId) {
      setCardDetails(null);
      return;
    }
    let cancelled = false;
    actions
      .cardGet(currentCardId)
      .then((result: CardGetResult) => {
        if (cancelled) return;
        setCardDetails(result);
      })
      .catch(() => {
        // 拉取失败时保持本地假设
        setCardDetails(null);
      });
    return () => {
      cancelled = true;
    };
  }, [currentCardId, actions]);

  const cardState: CharacterCardState = cardDetails?.state ?? (currentCardId ? "saved" : "draft");

  // 执行核心保存
  const performSave = useCallback(async (): Promise<boolean> => {
    const currentData = latestFormDataRef.current;
    const name = currentData.name.trim();

    if (!name) {
      setNameError("名称为必填项，填写后才能完成创建");
      const nameInput = document.getElementById("f-name");
      if (nameInput) {
        nameInput.focus();
      }
      return false;
    }

    if (vm.readOnly || isSavingRef.current) {
      return false;
    }

    isSavingRef.current = true;
    setSaveStatus("saving");
    setSaveError(null);

    try {
      let targetId = currentCardIdRef.current;
      if (!targetId) {
        targetId = await actions.createCardDraft(name);
        setCurrentCardId(targetId);
        currentCardIdRef.current = targetId;
      }

      const payload = buildCardPayload(cardJsonRef.current, currentData);
      await actions.updateCard(targetId, payload);

      const timeStr = formatTime();
      setLastSavedTime(timeStr);
      setSaveStatus("saved");
      return true;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveError(msg);
      setSaveStatus("error");
      return false;
    } finally {
      isSavingRef.current = false;
    }
  }, [actions, vm.readOnly]);

  // 发布流程
  const performPublish = useCallback(async (): Promise<boolean> => {
    const saved = await performSave();
    if (!saved) return false;

    const targetId = currentCardIdRef.current;
    if (!targetId) return false;

    setPublishStatus("publishing");
    setPublishError(null);
    try {
      await actions.cardPublish(targetId);
      // 发布成功后刷新服务端权威状态，使「完成创建」按钮立即转为「开始对话」。
      const refreshed = await actions.cardGet(targetId);
      setCardDetails(refreshed);
      setPublishStatus("published");
      return true;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setPublishError(msg);
      setPublishStatus("error");
      return false;
    }
  }, [performSave, actions]);

  // 未保存标记 + 防抖自动保存：表单字段与整卡 JSON（世界书 / mufy）编辑共用同一状态机。
  const markDirtyAndScheduleSave = useCallback(() => {
    setSaveStatus("unsaved");
    setSaveError(null);
    setPublishStatus("idle");
    setPublishError(null);

    // 清除前一个防抖计时器并重设
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }

    autoSaveTimerRef.current = setTimeout(() => {
      if (!vm.readOnly && latestFormDataRef.current.name.trim().length > 0) {
        void performSave();
      }
    }, 1000);
  }, [performSave, vm.readOnly]);

  // 字段变更处理
  const handleFieldChange = useCallback(
    <K extends keyof CharacterFormData>(field: K, value: CharacterFormData[K]) => {
      if (vm.readOnly) return;

      setFormData((prev) => {
        const next = { ...prev, [field]: value };
        latestFormDataRef.current = next;
        return next;
      });

      markDirtyAndScheduleSave();
    },
    [markDirtyAndScheduleSave, vm.readOnly],
  );

  // 整卡 JSON 编辑（世界书 / mufy 高级设定）：合并进草稿后走同一套防抖保存。
  const handleCardJsonChange = useCallback(
    (updater: (prev: Record<string, unknown> | null) => Record<string, unknown>) => {
      if (vm.readOnly) return;

      setCardJson((prev) => {
        const next = updater(prev);
        cardJsonRef.current = next;
        return next;
      });

      markDirtyAndScheduleSave();
    },
    [markDirtyAndScheduleSave, vm.readOnly],
  );

  // 世界书编辑回传完整 character_book，合并回整卡 JSON；其余字段原样保留。
  const handleCharacterBookChange = useCallback(
    (book: Record<string, unknown>) => {
      handleCardJsonChange((prev) => {
        const base = prev ?? vm.card ?? { spec: "chara_card_v3", spec_version: "3.0", data: {} };
        const data = (base.data as Record<string, unknown> | undefined) ?? {};
        return { ...base, data: { ...data, character_book: book } };
      });
    },
    [handleCardJsonChange, vm.card],
  );

  // mufy 高级设定回传完整 extensions.hsr，合并回整卡 JSON；extensions 内其他键原样保留。
  const handleHsrChange = useCallback(
    (hsr: Record<string, unknown>) => {
      handleCardJsonChange((prev) => {
        const base = prev ?? vm.card ?? { spec: "chara_card_v3", spec_version: "3.0", data: {} };
        const data = (base.data as Record<string, unknown> | undefined) ?? {};
        const extensions = (data.extensions as Record<string, unknown> | undefined) ?? {};
        return { ...base, data: { ...data, extensions: { ...extensions, hsr } } };
      });
    },
    [handleCardJsonChange, vm.card],
  );

  // 清理计时器
  useEffect(() => {
    return () => {
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }
    };
  }, []);

  // 未保存离开提示
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (saveStatus === "unsaved") {
        e.preventDefault();
        e.returnValue = "";
        return "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [saveStatus]);

  // 手动保存
  const handleManualSubmit = async (e?: React.FormEvent) => {
    if (e) {
      e.preventDefault();
    }
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }
    await performSave();
  };

  // 未保存变更时离开创作页需二次确认
  const confirmLeave = useCallback(
    (onConfirm: () => void) => {
      if (saveStatus === "unsaved") {
        const ok = window.confirm("有未保存的更改，确定要离开创作页吗？");
        if (!ok) return;
      }
      onConfirm();
    },
    [saveStatus],
  );

  // 使用该角色开始对话：激活卡 → 创建新聊天 → 进入聊天视图。
  const handleStartChat = useCallback(
    async (cardId: string | null) => {
      if (!cardId) return;
      confirmLeave(async () => {
        await actions.selectActiveCard(cardId);
        await actions.createConversation();
        actions.openChat();
      });
    },
    [actions, confirmLeave],
  );

  const isEditingExisting = Boolean(vm.cardId || currentCardId);
  const published = isCardPublished(cardState);

  return (
    <div className="char-create-root" data-testid="character-create-page">
      {/* 顶部工具栏与面包屑 */}
      <header className="char-create-topbar" data-testid="char-create-topbar">
        <div className="char-create-crumbs">
          <button
            type="button"
            className="char-create-crumbs-link"
            onClick={() => confirmLeave(() => actions.openCharacterLibrary())}
            aria-label="返回角色库"
          >
            <ArrowLeftIcon />
            角色库
          </button>
          <span>/</span>
          <span className="char-create-crumbs-current">
            {isEditingExisting ? (formData.name || "编辑角色") : "创建角色"}
          </span>
        </div>

        {/* 模式切换 */}
        <div
          className="char-create-mode-switch"
          role="group"
          aria-label="编辑模式切换"
          data-testid="mode-switch"
        >
          <button
            type="button"
            className={`char-create-mode-btn ${mode === "quick" ? "active" : ""}`}
            onClick={() => setMode("quick")}
            data-testid="mode-btn-quick"
          >
            快速创建
          </button>
          <button
            type="button"
            className={`char-create-mode-btn ${mode === "advanced" ? "active" : ""}`}
            onClick={() => setMode("advanced")}
            data-testid="mode-btn-advanced"
          >
            高级编辑
          </button>
        </div>

        {/* 状态徽标与主操作 */}
        <div className="char-create-topbar-actions">
          <SaveStatusBadge
            status={saveStatus}
            lastSavedTime={lastSavedTime}
            errorMessage={saveError}
          />
          <button
            type="button"
            className="char-btn char-btn-outline"
            onClick={() => confirmLeave(() => actions.openCharacterLibrary())}
          >
            返回角色库
          </button>
        </div>
      </header>

      {/* 主工作区 */}
      <main className="char-create-content">
        {/* 全局加载或错误反馈 */}
        {vm.loading ? (
          <div className="char-create-banner readonly" role="status">
            <span>载入角色卡数据中…</span>
          </div>
        ) : null}

        {vm.error ? (
          <div className="char-create-banner error" role="alert">
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <AlertCircleIcon />
              <span>角色卡加载失败：{vm.error}</span>
            </div>
            <button
              type="button"
              className="char-btn char-btn-outline"
              style={{ minHeight: "28px", padding: "2px 10px", fontSize: "12px" }}
              onClick={() => actions.openCharacterCreate(vm.cardId ?? undefined)}
            >
              重试
            </button>
          </div>
        ) : null}

        {saveError ? (
          <div className="char-create-banner error" role="alert" data-testid="save-error-banner">
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <AlertCircleIcon />
              <span>保存失败：{saveError}</span>
            </div>
            <button
              type="button"
              className="char-btn char-btn-secondary"
              style={{ minHeight: "28px", padding: "2px 10px", fontSize: "12px" }}
              onClick={() => void performSave()}
            >
              重试保存
            </button>
          </div>
        ) : null}

        {vm.readOnly ? (
          <div className="char-create-banner readonly" role="note">
            <span>内置角色卡为只读模式，不可修改或保存。</span>
          </div>
        ) : null}

        {mode === "quick" ? (
          <div className="char-create-grid">
            {/* 左侧表单 */}
            <form
              className="char-create-form"
              onSubmit={handleManualSubmit}
              noValidate
              style={{ display: "flex", flexDirection: "column", gap: "20px" }}
            >
              <BasicInfoSection
                cardId={currentCardId}
                formData={formData}
                avatar={cardDetails?.avatar}
                nameError={nameError}
                readOnly={vm.readOnly}
                actions={actions}
                onPickFile={onPickFile}
                onFieldChange={handleFieldChange}
                onClearNameError={() => setNameError(null)}
                onAvatarChange={async () => {
                  if (!currentCardId) return;
                  try {
                    const result = await actions.cardGet(currentCardId);
                    setCardDetails(result);
                  } catch {
                    // 失败保留旧头像
                  }
                }}
              />

              <PersonalitySection
                formData={formData}
                readOnly={vm.readOnly}
                onFieldChange={handleFieldChange}
              />

              <div className="char-create-action-bar">
                <button
                  type="button"
                  className="char-btn char-btn-secondary"
                  onClick={() => void performSave()}
                  disabled={vm.readOnly || saveStatus === "saving"}
                  data-testid="btn-draft"
                >
                  <SaveIcon />
                  保存草稿
                </button>
                {published ? (
                  <button
                    type="button"
                    className="char-btn char-btn-primary"
                    onClick={() => void handleStartChat(currentCardId)}
                    disabled={!currentCardId}
                    data-testid="btn-start-chat"
                  >
                    使用该角色开始对话
                  </button>
                ) : (
                  <button
                    type="button"
                    className="char-btn char-btn-primary"
                    onClick={() => void performPublish()}
                    disabled={vm.readOnly || saveStatus === "saving" || publishStatus === "publishing"}
                    data-testid="btn-submit"
                  >
                    {publishStatus === "publishing" ? "发布中…" : "完成创建"}
                  </button>
                )}
              </div>
            </form>

            {/* 右侧实时预览 */}
            <CharacterLivePreview
              cardId={currentCardId}
              formData={formData}
              avatar={cardDetails?.avatar}
              readOnly={vm.readOnly}
              cardState={cardState}
              publishStatus={publishStatus}
              publishError={publishError}
              actions={actions}
              onPublish={performPublish}
              onStartChat={() => void handleStartChat(currentCardId)}
            />
          </div>
        ) : (
          <AdvancedEditorPanel
            formData={formData}
            readOnly={vm.readOnly}
            cardJson={cardJson}
            onFieldChange={handleFieldChange}
            onCharacterBookChange={handleCharacterBookChange}
            onHsrChange={handleHsrChange}
            onReturnToQuick={() => setMode("quick")}
          />
        )}
      </main>
    </div>
  );
}
