import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { HarnessActions } from "../../contracts/actions";
import type {
  CharacterCardSummaryView,
  CharacterLibraryViewModel,
} from "../../contracts/view-models";
import type { DesktopBackend } from "../../services/backend";
import { CharacterImportFlow } from "../character-transfer/CharacterImportFlow";
import { CharacterExportFlow } from "../character-transfer/CharacterExportFlow";
import { CharacterCardItem } from "./CharacterCardItem";
import { CharacterCompatModal } from "./CharacterCompatModal";
import { CharacterDeleteModal } from "./CharacterDeleteModal";
import {
  EmptyFilterIcon,
  EmptyLibraryIcon,
  ImportIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
} from "./CharacterIcons";
import { CharacterInUseStrip } from "./CharacterInUseStrip";
import { CharacterNoticeModal } from "./CharacterNoticeModal";
import {
  filterCharacterCards,
  type CharacterFilterState,
  type SourceFilter,
  type VoiceStateFilter,
} from "./types";

import "./character-library.css";

interface CharacterLibraryPageProps {
  vm: CharacterLibraryViewModel;
  actions: HarnessActions;
  /** V0.3.5：「配置音色」直达设置中心语音页并预选该卡（AppShell 注入）。 */
  onConfigureCardVoice?: (cardId: string) => void;
  /** V0.3.5：桌面后端，用于打开文件对话框。当前 AppShell 未注入，故为可选；注入后立即生效。 */
  backend?: DesktopBackend;
}

export function CharacterLibraryPage({
  vm,
  actions,
  onConfigureCardVoice,
  backend,
}: CharacterLibraryPageProps) {
  const [filters, setFilters] = useState<CharacterFilterState>({
    search: "",
    source: "all",
    voice: "all",
  });

  const [deletingCard, setDeletingCard] = useState<CharacterCardSummaryView | null>(null);
  const [notice, setNotice] = useState<{ open: boolean; title: string; message: string }>({
    open: false,
    title: "",
    message: "",
  });
  const [importOpen, setImportOpen] = useState(false);
  const [exportCard, setExportCard] = useState<CharacterCardSummaryView | null>(null);
  const [compatCard, setCompatCard] = useState<CharacterCardSummaryView | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  const totalCards = vm.cards.length;
  const draftCount = vm.cards.filter((c) => c.state === "draft").length;
  const archivedCount = vm.cards.filter((c) => c.archived).length;

  const isZeroCardLibrary = vm.loaded && totalCards === 0;

  const filteredCards = useMemo(() => {
    return filterCharacterCards(vm.cards, filters);
  }, [vm.cards, filters]);

  const activeCard = useMemo(() => {
    return vm.cards.find((c) => c.active && !c.archived);
  }, [vm.cards]);

  const shouldVirtualize = filteredCards.length > 32;

  const virtualizer = useVirtualizer({
    count: filteredCards.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 180,
    overscan: 6,
    getItemKey: (index) => filteredCards[index]?.cardId ?? index,
  });

  const handleClearFilters = () => {
    setFilters({ search: "", source: "all", voice: "all" });
  };

  const showInvalidErrorNotice = (card: CharacterCardSummaryView) => {
    setNotice({
      open: true,
      title: `导入失败详情 · ${card.name}`,
      message: "该角色卡在解析时中断：文件损坏或缺少必要规范字段。可点击删除移除该条目并重新尝试导入。",
    });
  };

  const handleUseCard = async (cardId: string) => {
    await actions.selectActiveCard(cardId);
    await actions.createConversation();
    actions.openChat();
  };

  const handleImportSuccess = () => {
    void actions.listCards();
  };

  return (
    <div
      ref={scrollRef}
      className="char-lib-page"
      data-testid="character-library-page"
    >
      {/* 顶部工具栏 */}
      <header className="char-lib-toolbar" data-testid="library-toolbar">
        <div className="char-lib-title-area">
          <h1>角色库</h1>
          {!isZeroCardLibrary && (
            <span className="char-lib-meta">
              共 {totalCards} 个角色 · 筛选出 {filteredCards.length} 个
              {draftCount > 0 ? ` · ${draftCount} 个草稿` : ""}
              {archivedCount > 0 ? ` · ${archivedCount} 个已归档` : ""}
            </span>
          )}
        </div>

        {/* 零角色空库时不渲染筛选 UI */}
        {!isZeroCardLibrary && (
          <div className="char-lib-controls">
            <div className="char-search-box">
              <SearchIcon />
              <input
                type="search"
                placeholder="搜索名称…"
                aria-label="搜索角色"
                value={filters.search}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, search: e.target.value }))
                }
              />
            </div>

            <select
              className="char-select"
              aria-label="按来源筛选"
              value={filters.source}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  source: e.target.value as SourceFilter,
                }))
              }
            >
              <option value="all">全部来源</option>
              <option value="builtin">内置</option>
              <option value="user_created">创建</option>
              <option value="imported">导入</option>
              <option value="draft">草稿</option>
              <option value="archived">已归档</option>
            </select>

            <select
              className="char-select"
              aria-label="按音色状态筛选"
              value={filters.voice}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  voice: e.target.value as VoiceStateFilter,
                }))
              }
            >
              <option value="all">全部音色</option>
              <option value="voice_ready">已绑定</option>
              <option value="voice_unconfigured">未配置</option>
              <option value="voice_creating">创建中</option>
              <option value="voice_failed">失败</option>
            </select>

            <button
              type="button"
              className="char-btn char-btn-secondary"
              onClick={() => setImportOpen(true)}
            >
              <ImportIcon />
              <span>导入角色</span>
            </button>

            <button
              type="button"
              className="char-btn char-btn-primary"
              onClick={() => actions.openCharacterCreate()}
            >
              <PlusIcon />
              <span>创建角色</span>
            </button>

            <button
              type="button"
              className="char-btn char-btn-ghost"
              onClick={() => actions.openChat()}
            >
              返回聊天
            </button>
          </div>
        )}
      </header>

      {/* 真实加载失败展示与重试入口 */}
      {vm.error ? (
        <div className="char-error-banner" role="alert" data-testid="library-error-banner">
          <div className="char-error-text">
            <span>角色库加载失败：{vm.error}</span>
          </div>
          <button
            type="button"
            className="char-btn char-btn-secondary"
            onClick={() => void actions.listCards()}
          >
            <RefreshIcon />
            <span>重试</span>
          </button>
        </div>
      ) : null}

      {/* 骨架加载态 */}
      {vm.loading && !vm.loaded ? (
        <div className="char-grid" data-testid="library-skeleton-grid">
          {[1, 2, 3].map((key) => (
            <div key={key} className="char-card char-skeleton char-skeleton-card" />
          ))}
        </div>
      ) : isZeroCardLibrary ? (
        /* 空态 1：零角色空库（无筛选 UI，仅两项引导 CTA） */
        <div className="char-empty-container" data-testid="empty-library-zero">
          <div className="char-empty-icon-wrap">
            <EmptyLibraryIcon />
          </div>
          <h2 className="char-empty-title">角色库还是空的</h2>
          <p className="char-empty-desc">
            从空白创建第一个角色，或导入酒馆角色卡开始。所有角色都会集中在这里管理。
          </p>
          <div className="char-empty-actions">
            <button
              type="button"
              className="char-btn char-btn-primary"
              onClick={() => actions.openCharacterCreate()}
            >
              <PlusIcon />
              <span>创建第一个角色</span>
            </button>
            <button
              type="button"
              className="char-btn char-btn-secondary"
              onClick={() => setImportOpen(true)}
            >
              <ImportIcon />
              <span>导入角色卡</span>
            </button>
          </div>
        </div>
      ) : filteredCards.length === 0 ? (
        /* 空态 2：筛选无结果（可清空筛选） */
        <div className="char-empty-container" data-testid="empty-library-filtered">
          <div className="char-empty-icon-wrap">
            <EmptyFilterIcon />
          </div>
          <h2 className="char-empty-title">还没有符合筛选的角色</h2>
          <p className="char-empty-desc">清空筛选，或创建新角色。</p>
          <div className="char-empty-actions">
            <button
              type="button"
              className="char-btn char-btn-secondary"
              onClick={handleClearFilters}
            >
              清空筛选
            </button>
            <button
              type="button"
              className="char-btn char-btn-primary"
              onClick={() => actions.openCharacterCreate()}
            >
              <PlusIcon />
              <span>创建角色</span>
            </button>
          </div>
        </div>
      ) : (
        /* 角色卡片列表与使用中条 */
        <>
          {/* 使用中置顶条 */}
          {activeCard && (
            <CharacterInUseStrip
              card={activeCard}
              onEdit={(cardId) => actions.openCharacterCreate(cardId)}
            />
          )}

          {/* 卡片网格 */}
          {shouldVirtualize ? (
            <div
              style={{
                height: `${virtualizer.getTotalSize()}px`,
                width: "100%",
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const card = filteredCards[virtualRow.index];
                if (!card) return null;
                return (
                  <div
                    key={card.cardId}
                    ref={virtualizer.measureElement}
                    data-index={virtualRow.index}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                  >
                    <CharacterCardItem
                      card={card}
                      onUse={(id) => void handleUseCard(id)}
                      onEdit={(id) => actions.openCharacterCreate(id)}
                      onDuplicate={(id) => void actions.duplicateCard(id)}
                      onExport={(c) => setExportCard(c)}
                      onArchive={(id) => void actions.archiveCard(id)}
                      onDeleteRequest={(c) => setDeletingCard(c)}
                      onViewError={(c) => showInvalidErrorNotice(c)}
                      onViewCompat={setCompatCard}
                      onConfigureVoice={onConfigureCardVoice}
                    />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="char-grid" data-testid="character-card-grid">
              {filteredCards.map((card) => (
                <CharacterCardItem
                  key={card.cardId}
                  card={card}
                  onUse={(id) => void handleUseCard(id)}
                  onEdit={(id) => actions.openCharacterCreate(id)}
                  onDuplicate={(id) => void actions.duplicateCard(id)}
                  onExport={(c) => setExportCard(c)}
                  onArchive={(id) => void actions.archiveCard(id)}
                  onDeleteRequest={(c) => setDeletingCard(c)}
                  onViewError={(c) => showInvalidErrorNotice(c)}
                  onViewCompat={setCompatCard}
                  onConfigureVoice={onConfigureCardVoice}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* 删除确认弹窗 */}
      <CharacterDeleteModal
        card={deletingCard}
        onConfirm={(cardId) => void actions.deleteCard(cardId)}
        onClose={() => setDeletingCard(null)}
      />

      {/* 导入流程弹窗 */}
      {importOpen && (
        <div
          className="char-modal-mask"
          role="dialog"
          aria-modal="true"
          aria-label="导入角色"
          data-testid="import-flow-modal"
          onClick={(e) => {
            if (e.target === e.currentTarget) setImportOpen(false);
          }}
        >
          <div className="char-modal-box" style={{ width: "640px", maxWidth: "calc(100vw - 48px)" }}>
            <CharacterImportFlow
              backend={backend}
              actions={actions}
              onClose={() => setImportOpen(false)}
              onSuccess={handleImportSuccess}
            />
          </div>
        </div>
      )}

      {/* 导出流程弹窗 */}
      {exportCard && (
        <div
          className="char-modal-mask"
          role="dialog"
          aria-modal="true"
          aria-label="导出角色"
          data-testid="export-flow-modal"
          onClick={(e) => {
            if (e.target === e.currentTarget) setExportCard(null);
          }}
        >
          <div className="char-modal-box" style={{ width: "560px", maxWidth: "calc(100vw - 48px)" }}>
            <CharacterExportFlow
              cardId={exportCard.cardId}
              cardName={exportCard.name}
              backend={backend}
              actions={actions}
              onClose={() => setExportCard(null)}
              onSuccess={() => void actions.listCards()}
            />
          </div>
        </div>
      )}

      {/* 兼容性详情弹窗（V6：导入报告的随时回看入口） */}
      {compatCard && (
        <CharacterCompatModal
          cardId={compatCard.cardId}
          cardName={compatCard.name}
          actions={actions}
          onClose={() => setCompatCard(null)}
        />
      )}

      {/* 功能占位通知弹窗（保留给导入失败详情等） */}
      <CharacterNoticeModal
        title={notice.title}
        message={notice.message}
        open={notice.open}
        onClose={() => setNotice((prev) => ({ ...prev, open: false }))}
      />
    </div>
  );
}
