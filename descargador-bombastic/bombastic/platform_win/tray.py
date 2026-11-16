"""Icono de la bandeja del sistema con menú, progreso en el tooltip y notificaciones."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from bombastic.core.i18n import tr


class Tray(QObject):
    show_requested = Signal()
    pause_all_requested = Signal()
    resume_all_requested = Signal()
    open_folder_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.icon = QSystemTrayIcon(icon, self)
        self.menu = QMenu()
        self._actions: list[tuple[QAction, str]] = []
        for key, signal in (
            ("tray.show", self.show_requested),
            ("tray.pause_all", self.pause_all_requested),
            ("tray.resume_all", self.resume_all_requested),
            ("tray.open_folder", self.open_folder_requested),
            ("tray.quit", self.quit_requested),
        ):
            action = self.menu.addAction(tr(key))
            action.triggered.connect(signal)
            self._actions.append((action, key))
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.messageClicked.connect(self._on_message_clicked)
        self._on_click: Callable[[], None] | None = None
        self.set_progress("")

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        self.icon.show()

    def retranslate(self) -> None:
        for action, key in self._actions:
            action.setText(tr(key))

    def set_progress(self, text: str) -> None:
        """Tooltip con el progreso global (vacío = solo el nombre de la app)."""
        self.icon.setToolTip(tr("app.name") + (f"\n{text}" if text else ""))

    def notify(self, title: str, message: str, on_click: Callable[[], None] | None = None) -> None:
        self._on_click = on_click
        self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 6000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def _on_message_clicked(self) -> None:
        callback, self._on_click = self._on_click, None
        if callback is not None:
            callback()
        else:
            self.show_requested.emit()
