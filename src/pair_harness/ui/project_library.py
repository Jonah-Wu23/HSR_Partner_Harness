from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pair_harness.storage.sqlite_store import SQLiteStore


class ProjectLibrary(QWidget):
    conversation_selected = pyqtSignal(str)
    project_create_requested = pyqtSignal()
    conversation_create_requested = pyqtSignal(str)

    def __init__(self, store: SQLiteStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.tree = QTreeWidget()
        self.tree.setObjectName("projectTree")
        self.tree.setHeaderLabels(["项目与聊天"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.new_project_button = QPushButton("新建项目")
        self.new_project_button.setObjectName("newProjectButton")
        # 主操作按钮：走全局 QSS 的 primary 变体
        self.new_project_button.setProperty("kind", "primary")
        self.new_conversation_button = QPushButton("新建聊天")
        self.new_conversation_button.setObjectName("newConversationButton")
        # 次操作按钮：走全局 QSS 的 ghost 变体
        self.new_conversation_button.setProperty("kind", "ghost")
        buttons.addWidget(self.new_project_button)
        buttons.addWidget(self.new_conversation_button)
        layout.addLayout(buttons)
        layout.addWidget(self.tree)
        self.tree.itemActivated.connect(self._activated)
        self.new_project_button.clicked.connect(self.project_create_requested)
        self.new_conversation_button.clicked.connect(self._request_new_conversation)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        for project in self.store.list_projects():
            project_item = QTreeWidgetItem([project.name])
            project_item.setData(0, Qt.UserRole, project.project_id)
            project_item.setData(0, Qt.UserRole + 1, None)
            if not project.path_available:
                project_item.setText(0, f"{project.name}（路径失效）")
            self.tree.addTopLevelItem(project_item)
            for conversation in self.store.list_conversations(project.project_id):
                item = QTreeWidgetItem(
                    [f"{conversation.title} · {conversation.pair_id}"]
                )
                item.setData(0, Qt.UserRole, conversation.conversation_id)
                item.setData(0, Qt.UserRole + 1, project.project_id)
                project_item.addChild(item)
            project_item.setExpanded(True)

    def _activated(self, item: QTreeWidgetItem) -> None:
        conversation_id = item.data(0, Qt.UserRole)
        if item.parent() is None:
            return
        if conversation_id:
            self.conversation_selected.emit(str(conversation_id))

    def _request_new_conversation(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        project_id = item.data(0, Qt.UserRole + 1)
        if item.parent() is None:
            project_id = item.data(0, Qt.UserRole)
        if project_id:
            self.conversation_create_requested.emit(str(project_id))
