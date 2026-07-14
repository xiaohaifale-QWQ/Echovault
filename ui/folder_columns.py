"""A Finder-style, horizontally scrollable folder browser for the material library."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class FolderColumnsBrowser(QWidget):
    """Show each opened folder in its own column.

    A double click opens a folder in the column to its right.  Columns deliberately
    keep a minimum readable width; the scroll area supplies a horizontal scrollbar
    on narrow windows instead of compressing the folder names into an unusable tree.
    """

    folder_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[tuple[str | None, QListWidget]] = []
        self._current_folder = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._content = QWidget()
        self._content_layout = QHBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(1)
        self._content_layout.addStretch()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    @property
    def current_folder(self) -> str:
        return self._current_folder

    def set_roots(self, directories: list[str]) -> None:
        self._clear_columns()
        roots = [path for path in directories if os.path.isdir(path)]
        self._add_column("素材文件夹", roots, roots=True)
        self._current_folder = roots[0] if roots else ""

    def _clear_columns(self) -> None:
        self._columns.clear()
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _entries_for(self, folder: str) -> list[str]:
        try:
            entries = [entry.path for entry in os.scandir(folder) if not entry.name.startswith(".")]
        except OSError:
            return []
        return sorted(
            entries,
            key=lambda path: (not os.path.isdir(path), os.path.basename(path).lower()),
        )

    def _add_column(self, title: str, paths: list[str], *, roots: bool = False) -> None:
        column = QFrame()
        column.setObjectName("materialFolderColumn")
        column.setFixedWidth(238)
        column.setStyleSheet(
            "QFrame#materialFolderColumn{background:#FFFFFF;border:1px solid #D9DEE5;}"
            "QListWidget{border:0;background:#FFFFFF;}"
            "QListWidget::item{padding:6px 7px;}"
            "QListWidget::item:selected{background:#E7EDF3;color:#1F2933;}"
        )
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet("padding:7px 8px;background:#F1F3F5;color:#4B5563;font-weight:600;")
        layout.addWidget(label)
        listing = QListWidget()
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for path in paths:
            item = QListWidgetItem(
                ("▸ " if os.path.isdir(path) else "   ") + (os.path.basename(path) or path)
            )
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(Qt.ItemDataRole.UserRole + 1, roots)
            listing.addItem(item)
        listing.itemClicked.connect(self._select_item)
        listing.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(listing)
        self._content_layout.insertWidget(self._content_layout.count() - 1, column)
        self._columns.append((None if roots else title, listing))
        self._content.setMinimumWidth(len(self._columns) * 239)

    def _select_item(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if os.path.isdir(path):
            self._current_folder = path
            self.folder_selected.emit(path)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not os.path.isdir(path):
            return
        listing = item.listWidget()
        column_index = next(
            (i for i, (_, widget) in enumerate(self._columns) if widget is listing), -1
        )
        if column_index < 0:
            return
        while len(self._columns) > column_index + 1:
            _title, old_listing = self._columns.pop()
            old_column = old_listing.parentWidget()
            self._content_layout.removeWidget(old_column)
            old_column.deleteLater()
        self._content.setMinimumWidth(len(self._columns) * 239)
        self._current_folder = path
        self.folder_selected.emit(path)
        self._add_column(os.path.basename(path) or path, self._entries_for(path))
        QTimer.singleShot(
            0,
            lambda: self._scroll.horizontalScrollBar().setValue(
                self._scroll.horizontalScrollBar().maximum()
            ),
        )
