"""Windows Explorer-style folder browser for the material library."""

from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import QFileInfo, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileIconProvider,
    QHeaderView,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FolderColumnsBrowser(QWidget):
    """Show added roots and their subfolders in one multi-select tree."""

    folder_selected = pyqtSignal(str)
    folders_selected = pyqtSignal(object)
    material_selected = pyqtSignal(str)
    root_removal_requested = pyqtSignal(str)

    PATH_ROLE = Qt.ItemDataRole.UserRole
    ROOT_ROLE = Qt.ItemDataRole.UserRole + 1
    LOADED_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_folder = ""
        self._last_emitted_paths: list[str] = []
        self._icon_provider = QFileIconProvider()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setObjectName("materialFolderTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["名称", "修改日期", "类型"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(18)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemExpanded.connect(self._populate_item)
        self.tree.itemDoubleClicked.connect(self._open_item)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setStyleSheet(
            """
            QTreeWidget#materialFolderTree {
                background:#FFFFFF; alternate-background-color:#FAFBFD;
                border:1px solid #DCE3EB; border-radius:9px; outline:none;
            }
            QTreeWidget#materialFolderTree::item {
                min-height:30px; padding:3px 5px; border-radius:5px;
            }
            QTreeWidget#materialFolderTree::item:selected {
                background:#DDECFB; color:#1F6FBB;
            }
            QTreeWidget#materialFolderTree::item:hover:!selected {
                background:#F0F5FA;
            }
            """
        )
        layout.addWidget(self.tree)

    @property
    def current_folder(self) -> str:
        return self._current_folder

    @property
    def selected_folders(self) -> list[str]:
        return self._ordered_selected_paths()

    def set_roots(self, directories: list[str]) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self._last_emitted_paths = []
        roots = [os.path.abspath(path) for path in directories if os.path.isdir(path)]
        for path in roots:
            self.tree.addTopLevelItem(self._folder_item(path, root=True))
        if self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(first)
            first.setSelected(True)
            self._current_folder = str(first.data(0, self.PATH_ROLE) or "")
        else:
            self._current_folder = ""
        self.tree.blockSignals(False)

    def _folder_item(self, path: str, *, root: bool = False) -> QTreeWidgetItem:
        name = os.path.basename(path.rstrip("\\/")) or path
        item = QTreeWidgetItem([name, self._modified_text(path), "文件夹"])
        item.setData(0, self.PATH_ROLE, path)
        item.setData(0, self.ROOT_ROLE, root)
        item.setData(0, self.LOADED_ROLE, False)
        item.setToolTip(0, path)
        item.setIcon(0, self._icon_provider.icon(QFileInfo(path)))
        placeholder = QTreeWidgetItem([""])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        item.addChild(placeholder)
        return item

    @staticmethod
    def _modified_text(path: str) -> str:
        try:
            return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y/%m/%d %H:%M")
        except OSError:
            return ""

    @staticmethod
    def _subfolders(path: str) -> list[str]:
        try:
            folders = [
                entry.path
                for entry in os.scandir(path)
                if entry.is_dir(follow_symlinks=False) and not entry.name.startswith(".")
            ]
        except OSError:
            return []
        return sorted(folders, key=lambda value: os.path.basename(value).casefold())

    def _populate_item(self, item: QTreeWidgetItem) -> None:
        if bool(item.data(0, self.LOADED_ROLE)):
            return
        path = str(item.data(0, self.PATH_ROLE) or "")
        item.takeChildren()
        for folder in self._subfolders(path):
            item.addChild(self._folder_item(folder))
        item.setData(0, self.LOADED_ROLE, True)

    def _open_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        path = str(item.data(0, self.PATH_ROLE) or "")
        if not os.path.isdir(path):
            return
        self._populate_item(item)
        item.setExpanded(True)
        self.tree.setCurrentItem(item)
        if not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        self._selection_changed()

    def _ordered_selected_paths(self) -> list[str]:
        selected = [
            str(item.data(0, self.PATH_ROLE) or "")
            for item in self.tree.selectedItems()
            if os.path.isdir(str(item.data(0, self.PATH_ROLE) or ""))
        ]
        current = self.tree.currentItem()
        current_path = str(current.data(0, self.PATH_ROLE) or "") if current else ""
        selected = list(dict.fromkeys(selected))
        if current_path in selected:
            selected.remove(current_path)
            selected.append(current_path)
        return selected

    def _selection_changed(self) -> None:
        paths = self._ordered_selected_paths()
        self._current_folder = paths[-1] if paths else ""
        if paths == self._last_emitted_paths:
            return
        self._last_emitted_paths = list(paths)
        self.folders_selected.emit(paths)
        self.folder_selected.emit(self._current_folder)

    def _show_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None or not bool(item.data(0, self.ROOT_ROLE)):
            return
        path = str(item.data(0, self.PATH_ROLE) or "")
        if not path:
            return
        menu = QMenu(self)
        remove_action = menu.addAction("从素材库移除此文件夹")
        remove_action.triggered.connect(
            lambda _checked=False, target=path: self.root_removal_requested.emit(target)
        )
        menu.exec(self.tree.viewport().mapToGlobal(position))
