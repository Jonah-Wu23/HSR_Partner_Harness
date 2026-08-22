import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { CharacterCreateViewModel } from "../../contracts/view-models";
import { BasicInfoSection } from "./BasicInfoSection";
import { PersonalitySection } from "./PersonalitySection";
import { CharacterLivePreview } from "./CharacterLivePreview";
import { AdvancedPlaceholderPanel } from "./AdvancedPlaceholderPanel";
import { SaveStatusBadge } from "./SaveStatusBadge";
import { AlertCircleIcon, ArrowLeftIcon, SaveIcon } from "./icons";
import {
  buildCardPayload,
  extractFormData,
  type CharacterFormData,
  type CreateMode,
  type SaveStatus,
} from "./types";
import "./CharacterCreate.css";

interface CharacterCreatePageProps {
  vm: CharacterCreateViewModel;
  actions: HarnessActions;
}

function formatTime(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function CharacterCreatePage({ vm, actions }: CharacterCreatePageProps) {
  const [formData, setFormData] = useState<CharacterFormData>(() => extractFormData(vm.card));
  const [currentCardId, setCurrentCardId] = useState<string | null>(vm.cardId);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>(() => (vm.cardId ? "saved" : "idle"));
  const [lastSavedTime, setLastSavedTime] = useState<string | null>(() =>
    vm.cardId ? formatTime() : null,
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [mode, setMode] = useState<CreateMode>("quick");

  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestFormDataRef = useRef(formData);
  latestFormDataRef.current = formData;
  const currentCardIdRef = useRef(currentCardId);
  currentCardIdRef.current = currentCardId;
  const isSavingRef = useRef(false);

  // 当 vm.card 外部变更时水合
  useEffect(() => {
    if (vm.card) {
      setFormData(extractFormData(vm.card));
      setCurrentCardId(vm.cardId);
      setSaveStatus("saved");
      setLastSavedTime(formatTime());
    }
  }, [vm.card, vm.cardId]);

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

      const payload = buildCardPayload(vm.card, currentData);
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
  }, [actions, vm.card, vm.readOnly]);

  // 字段变更处理
  const handleFieldChange = useCallback(
    <K extends keyof CharacterFormData>(field: K, value: CharacterFormData[K]) => {
      if (vm.readOnly) return;

      setFormData((prev) => {
        const next = { ...prev, [field]: value };
        latestFormDataRef.current = next;
        return next;
      });

      setSaveStatus("unsaved");
      setSaveError(null);

      // 清除前一个防抖计时器并重设
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }

      autoSaveTimerRef.current = setTimeout(() => {
        if (!vm.readOnly && latestFormDataRef.current.name.trim().length > 0) {
          void performSave();
        }
      }, 1000);
    },
    [performSave, vm.readOnly],
  );

  // 清理计时器
  useEffect(() => {
    return () => {
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }
    };
  }, []);

  // 手动保存/完成创建
  const handleManualSubmit = async (e?: React.FormEvent) => {
    if (e) {
      e.preventDefault();
    }
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }
    await performSave();
  };

  const isEditingExisting = Boolean(vm.cardId || currentCardId);

  return (
    <div className="char-create-root" data-testid="character-create-page">
      {/* 顶部工具栏与面包屑 */}
      <header className="char-create-topbar" data-testid="char-create-topbar">
        <div className="char-create-crumbs">
          <button
            type="button"
            className="char-create-crumbs-link"
            onClick={() => actions.openCharacterLibrary()}
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
            onClick={() => actions.openCharacterLibrary()}
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
                formData={formData}
                nameError={nameError}
                readOnly={vm.readOnly}
                onFieldChange={handleFieldChange}
                onClearNameError={() => setNameError(null)}
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
                <button
                  type="submit"
                  className="char-btn char-btn-primary"
                  disabled={vm.readOnly || saveStatus === "saving"}
                  data-testid="btn-submit"
                >
                  完成创建
                </button>
              </div>
            </form>

            {/* 右侧实时预览 */}
            <CharacterLivePreview formData={formData} readOnly={vm.readOnly} />
          </div>
        ) : (
          <AdvancedPlaceholderPanel
            formData={formData}
            onReturnToQuick={() => setMode("quick")}
          />
        )}
      </main>
    </div>
  );
}
