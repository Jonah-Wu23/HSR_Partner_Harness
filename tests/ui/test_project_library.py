from pathlib import Path

from pair_harness.storage.sqlite_store import SQLiteStore
from pair_harness.ui.project_library import ProjectLibrary


def test_project_library_selects_and_creates_conversation(qtbot, tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.db") as store:
        store.create_project(
            project_id="p", name="Repo", root_path=str(tmp_path)
        )
        store.create_conversation(
            conversation_id="c",
            project_id="p",
            pair_id="phainon_ancient_machine",
            title="聊天",
        )
        library = ProjectLibrary(store)
        qtbot.addWidget(library)
        project_item = library.tree.topLevelItem(0)
        conversation_item = project_item.child(0)

        selected = []
        library.conversation_selected.connect(selected.append)
        library._activated(conversation_item)
        assert selected == ["c"]

        requested = []
        library.conversation_create_requested.connect(requested.append)
        library.tree.setCurrentItem(conversation_item)
        library.new_conversation_button.click()
        assert requested == ["p"]


def test_project_library_requests_new_project(qtbot, tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.db") as store:
        library = ProjectLibrary(store)
        qtbot.addWidget(library)
        requested = []
        library.project_create_requested.connect(lambda: requested.append(True))
        library.new_project_button.click()
        assert requested == [True]
