import type { HarnessActions } from "../../contracts/actions";
import type { CharacterLibraryViewModel } from "../../contracts/view-models";

interface CharacterLibraryPageProps {
  vm: CharacterLibraryViewModel;
  actions: HarnessActions;
}

/**
 * V0.3.3 角色库（骨架空壳，由 W1 填充）。
 *
 * 视觉与状态参照：
 * - docs/design/web-prototype/character-library.html（页面原型）
 * - docs/design/web-prototype/index.html（状态矩阵：两种空态必须分开）
 *
 * TODO(W1)：角色列表 / 状态徽章 / 来源与音色筛选 / 双空态（零角色 vs 筛选无结果）/
 * 操作菜单与删除确认 / 虚拟滚动。数据只走 vm 与 actions；样例数据仅允许
 * 经 mock 后端来自 src/mocks/characterCards.ts，不得在本组件内硬编码。
 */
export function CharacterLibraryPage({ vm, actions }: CharacterLibraryPageProps) {
  return (
    <div className="characters-page" data-testid="character-library-page">
      <header className="characters-page-head">
        <h1>角色库</h1>
        <button type="button" className="btn btn-outline" onClick={() => actions.openChat()}>
          返回聊天
        </button>
      </header>
      <p className="characters-hint">骨架空壳：等待 W1 实现（见文件头 TODO）。</p>
      {vm.loading ? <p className="characters-hint">载入中…</p> : null}
      {vm.error ? (
        <p className="field-error" role="alert">
          角色库加载失败：{vm.error}
        </p>
      ) : null}
      <p className="characters-hint">当前 {vm.cards.length} 张角色卡。</p>
    </div>
  );
}
