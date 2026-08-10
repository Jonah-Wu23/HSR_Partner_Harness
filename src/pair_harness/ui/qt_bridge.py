from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class OrchestratorBridge(QObject):
    message_ready = pyqtSignal(object)
    tool_run_ready = pyqtSignal(object)
    busy_changed = pyqtSignal(bool)
    error = pyqtSignal(str)
    cancel_requested = pyqtSignal()
    approval_resolved = pyqtSignal(str, str)

