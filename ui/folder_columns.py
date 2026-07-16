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
    QMenu,
    QScrollArea,
    QSizePolicy,
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
    material_selected = pyqtSignal(str)
    root_removal_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[tuple[str | None, QListWidget]] = []
        self._current_folder = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        # Let the content take the viewport height. Its minimum width still keeps
        # every column readable and causes a horizontal bar when needed.
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._content_layout = QHBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)
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
        # Show the first added folder's contents immediately in the right column.
        if roots:
            first_root = roots[0]
            self._add_column(
                os.path.basename(first_root) or first_root, self._entries_for(first_root)
            )

    def _clear_columns(self) -> None:
        self._columns.clear()
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._update_content_minimum_width()

    def _update_content_minimum_width(self) -> None:
        self._content.setMinimumWidth(max(216, len(self._columns) * 216))

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
        column.setMinimumWidth(210)
        column.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        column.setStyleSheet(
            "QFrame#materialFolderColumn{background:#FFFFFF;border:1px solid #DCE3EB;"
            "border-radius:9px;}"
            "QLabel#materialFolderColumnTitle{padding:8px 10px;background:#F3F6FA;"
            "color:#526073;font-weight:600;border-top-left-radius:8px;"
            "border-top-right-radius:8px;}"
            "QListWidget{border:0;background:#FFFFFF;border-bottom-left-radius:8px;"
            "border-bottom-right-radius:8px;}"
            "QListWidget::item{padding:7px 9px;border-radius:6px;margin:1px 4px;}"
            "QListWidget::item:selected{background:#E7F1FC;color:#1F6FBB;}"
        )
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setObjectName("materialFolderColumnTitle")
        layout.addWidget(label)
        listing = QListWidget()
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if not paths:
            empty = QListWidgetItem(
                "尚未添加文件夹" if roots else "此文件夹没有可显示内容"
            )
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            listing.addItem(empty)
        for path in paths:
            item = QListWidgetItem(
                ("文件夹  " if os.path.isdir(path) else "文件  ")
                + (os.path.basename(path) or path)
            )
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(Qt.ItemDataRole.UserRole + 1, roots)
            item.setToolTip(path)
            listing.addItem(item)
        listing.itemClicked.connect(self._select_item)
        listing.itemDoubleClicked.connect(self._open_item)
        listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        listing.customContextMenuRequested.connect(
            lambda position, target=listing: self._show_context_menu(target, position)
        )
        layout.addWidget(listing)
        self._content_layout.addWidget(column, 1)
        self._columns.append((None if roots else title, listing))
        self._update_content_minimum_width()

    def _select_item(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if os.path.isdir(path):
            self._current_folder = path
            self.folder_selected.emit(path)
        elif os.path.isfile(path):
            self.material_selected.emit(path)

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
        self._update_content_minimum_width()
        self._current_folder = path
        self.folder_selected.emit(path)
        self._add_column(os.path.basename(path) or path, self._entries_for(path))
        QTimer.singleShot(
            0,
            lambda: self._scroll.horizontalScrollBar().setValue(
                self._scroll.horizontalScrollBar().maximum()
            ),
        )

    def _show_context_menu(self, listing: QListWidget, position) -> None:
        item = listing.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole + 1):
            return
        folder_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not folder_path:
            return
        menu = QMenu(self)
        remove_action = menu.addAction("取消添加此文件夹")
        remove_action.triggered.connect(
            lambda _checked=False, path=folder_path: self.root_removal_requested.emit(path)
        )
        menu.exec(listing.mapToGlobal(position))
