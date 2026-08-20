import type { HarnessActions } from "../../contracts/actions";
import type { CharacterCreateViewModel } from "../../contracts/view-models";

interface CharacterCreatePageProps {
  vm: CharacterCreateViewModel;
  actions: HarnessActions;
}

/**
 * V0.3.3 角色创作页（骨架空壳，由 W2 填充）。
 *
 * 视觉与字段参照：
 * - docs/design/web-prototype/character-create.html（快速创建原型）
 * - docs/design/web-prototype/handoff-requirements.md 第 1 节（字段与必填约束）
 *
 * TODO(W2)：基础信息区（名称必填）/ 人格设定区（2000 字计数）/
 * 渐进式「进入高级编辑」占位入口 / 保存态机（未保存→保存中→已保存 HH:MM:SS，
 * 防抖自动保存 + 手动保存）。首次保存走 actions.createCardDraft(name) 再
 * actions.updateCard(cardId, card)，之后走 updateCard；保存失败展示真实错误
 * 并保留未保存内容，不得丢稿。
 */
export function CharacterCreatePage({ vm, actions }: CharacterCreatePageProps) {
  void actions;
  return (
    <div className="characters-page" data-testid="character-create-page">
      <header className="characters-page-head">
        <h1>创建角色</h1>
        <button type="button" className="btn btn-outline" onClick={() => actions.openCharacterLibrary()}>
          返回角色库
        </button>
      </header>
      <p className="characters-hint">骨架空壳：等待 W2 实现（见文件头 TODO）。</p>
      {vm.loading ? <p className="characters-hint">载入中…</p> : null}
      {vm.error ? (
        <p className="field-error" role="alert">
          角色卡加载失败：{vm.error}
        </p>
      ) : null}
      <p className="characters-hint">
        当前草稿：{vm.cardId ?? "（尚未保存）"}
        {vm.readOnly ? "（只读卡不可编辑）" : ""}
      </p>
    </div>
  );
}
