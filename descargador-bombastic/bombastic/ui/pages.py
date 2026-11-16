"""Base de las páginas de la ventana principal y página provisional."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from bombastic.core.i18n import tr


class Page(QWidget):
    """Página con cabecera (título y subtítulo). El contenido se añade a ``self.body``."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName(f"Page_{key}")

        self.title_label = QLabel()
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setWordWrap(True)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(4)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(14)
        layout.addLayout(self.body, 1)

    def retranslate(self) -> None:
        """Vuelve a poner todos los textos. Las subclases amplían este método."""
        self.title_label.setText(tr(f"nav.{self.key}"))
        self.subtitle_label.setText(tr(f"page.{self.key}.subtitle"))


class PlaceholderPage(Page):
    """Sección todavía sin implementar: indica en qué fase llegará."""

    def __init__(self, key: str, phase: int, parent: QWidget | None = None) -> None:
        super().__init__(key, parent)
        self.phase = phase
        self.message = QLabel()
        self.message.setObjectName("Placeholder")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.body.addWidget(self.message)
        self.body.addStretch(1)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self.message.setText(tr("page.placeholder", phase=self.phase))
