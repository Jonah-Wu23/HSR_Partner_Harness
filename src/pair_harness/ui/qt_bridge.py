from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class OrchestratorBridge(QObject):
    # O2.1：流式事件通道——消息、引擎事件（含工具与审批）产生时即推送
    message_ready = pyqtSignal(object)
    tool_run_ready = pyqtSignal(object)
    engine_event_ready = pyqtSignal(object)
    busy_changed = pyqtSignal(bool)
    error = pyqtSignal(str)
    cancel_requested = pyqtSignal()
    approval_resolved = pyqtSignal(str, str)

