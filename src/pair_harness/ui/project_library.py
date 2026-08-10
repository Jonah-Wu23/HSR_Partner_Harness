from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from pair_harness.storage.sqlite_store import SQLiteStore


class ProjectLibrary(QWidget):
    conversation_selected = pyqtSignal(str)

    def __init__(self, store: SQLiteStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.tree = QTreeWidget()
        self.tree.setObjectName("projectTree")
        self.tree.setHeaderLabels(["项目与聊天"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        self.tree.itemActivated.connect(self._activated)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        for project in self.store.list_projects():
            project_item = QTreeWidgetItem([project.name])
            project_item.setData(0, Qt.UserRole, None)
            if not project.path_available:
                project_item.setText(0, f"{project.name}（路径失效）")
            self.tree.addTopLevelItem(project_item)
            for conversation in self.store.list_conversations(project.project_id):
                item = QTreeWidgetItem(
                    [f"{conversation.title} · {conversation.pair_id}"]
                )
                item.setData(0, Qt.UserRole, conversation.conversation_id)
                project_item.addChild(item)
            project_item.setExpanded(True)

    def _activated(self, item: QTreeWidgetItem) -> None:
        conversation_id = item.data(0, Qt.UserRole)
        if conversation_id:
            self.conversation_selected.emit(str(conversation_id))

