"""Settings widgets for LX JavaScript and declarative REST audio sources."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.audio_sources import import_lx_source, validate_source_config


def _js_files_from_mime(mime_data) -> list[str]:
    if not mime_data or not mime_data.hasUrls():
        return []
    return [
        url.toLocalFile()
        for url in mime_data.urls()
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.casefold() == ".js"
    ]


class AudioSourceDropZone(QFrame):
    """Visible drop target for one or more LX source files."""

    files_dropped = pyqtSignal(object)
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("audioSourceDropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        icon = QLabel("JS")
        icon.setObjectName("audioSourceDropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(38, 38)
        layout.addWidget(icon)
        copy = QVBoxLayout()
        title = QLabel("拖入 LX 音源脚本")
        title.setObjectName("audioSourceDropTitle")
        copy.addWidget(title)
        hint = QLabel("支持一次拖入多个 .js 文件，也可以点击这里选择")
        hint.setObjectName("audioSourceDropHint")
        copy.addWidget(hint)
        layout.addLayout(copy)
        layout.addStretch()
        self.setStyleSheet(
            """
            QFrame#audioSourceDropZone {
                background:#F6FAFF; border:1px dashed #8DB9E8;
                border-radius:8px;
            }
            QFrame#audioSourceDropZone[dragActive="true"] {
                background:#E8F3FF; border:2px solid #4B96E6;
            }
            QLabel#audioSourceDropIcon {
                color:#FFFFFF; background:#3686D7; border-radius:7px;
                font-weight:700;
            }
            QLabel#audioSourceDropTitle { color:#17365D; font-weight:700; }
            QLabel#audioSourceDropHint { color:#718096; font-size:11px; }
            """
        )

    def _set_active(self, active: bool):
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if _js_files_from_mime(event.mimeData()):
            self._set_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_active(False)
        paths = _js_files_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()


class AudioSourceImportWorker(QThread):
    completed = pyqtSignal(object, object)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.paths = list(dict.fromkeys(paths))

    def run(self):
        imported = []
        failures = []
        for path in self.paths:
            try:
                imported.extend(import_lx_source(path))
            except (OSError, ValueError) as exc:
                failures.append(f"{Path(path).name}：{exc}")
        self.completed.emit(imported, failures)


class AudioSourceEditDialog(QDialog):
    """Edit one declarative JSON/REST source."""

    def __init__(self, source: dict | None = None, parent=None):
        super().__init__(parent)
        self._source = dict(source or {})
        self.setWindowTitle("编辑 REST 音源" if source else "添加 REST 音源")
        self.resize(620, 500)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(str(self._source.get("name", "")))
        self.id_edit = QLineEdit(str(self._source.get("id", "")))
        self.base_url_edit = QLineEdit(str(self._source.get("base_url", "")))
        self.search_path_edit = QLineEdit(
            str(self._source.get("search_path", "/search?q={query}"))
        )
        self.resolve_path_edit = QLineEdit(
            str(self._source.get("resolve_path", "/tracks/{id}?quality={quality}"))
        )
        self.qualities_edit = QLineEdit(
            ", ".join(self._source.get("qualities", ["128k", "320k", "flac"]))
        )
        self.headers_edit = QLineEdit(
            json.dumps(self._source.get("headers", {}), ensure_ascii=False)
        )
        self.terms_edit = QLineEdit(str(self._source.get("terms_url", "")))
        self.enabled_check = QCheckBox("启用此音源")
        self.enabled_check.setChecked(bool(self._source.get("enabled", True)))
        self.authorized_check = QCheckBox("我确认有权访问和下载该音源提供的内容")
        self.authorized_check.setChecked(bool(self._source.get("authorized", False)))
        form.addRow("名称：", self.name_edit)
        form.addRow("唯一 ID：", self.id_edit)
        form.addRow("接口地址：", self.base_url_edit)
        form.addRow("搜索路径：", self.search_path_edit)
        form.addRow("解析路径：", self.resolve_path_edit)
        form.addRow("音质：", self.qualities_edit)
        form.addRow("请求头 JSON：", self.headers_edit)
        form.addRow("授权说明：", self.terms_edit)
        form.addRow("", self.enabled_check)
        form.addRow("", self.authorized_check)
        layout.addLayout(form)
        hint = QLabel(
            '搜索接口返回 {"tracks":[...]}；解析接口返回 '
            '{"url":"https://..."}。REST 接口仅支持 HTTPS。'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748B;font-size:11px")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存音源")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self):
        if not self.id_edit.text().strip() and self.name_edit.text().strip():
            generated = re.sub(
                r"[^A-Za-z0-9._-]+",
                "-",
                self.name_edit.text().strip().casefold(),
            ).strip("-")
            self.id_edit.setText(generated or "custom-source")
        try:
            self.source()
        except (ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "音源配置有误", str(exc))
            return
        self.accept()

    def source(self) -> dict:
        headers = json.loads(self.headers_edit.text().strip() or "{}")
        return validate_source_config(
            {
                "type": "rest",
                "id": self.id_edit.text().strip(),
                "name": self.name_edit.text().strip(),
                "base_url": self.base_url_edit.text().strip(),
                "search_path": self.search_path_edit.text().strip(),
                "resolve_path": self.resolve_path_edit.text().strip(),
                "qualities": [
                    value.strip()
                    for value in self.qualities_edit.text().split(",")
                    if value.strip()
                ],
                "headers": headers,
                "terms_url": self.terms_edit.text().strip(),
                "authorized": self.authorized_check.isChecked(),
                "enabled": self.enabled_check.isChecked(),
            }
        )


class AudioSourceManagerWidget(QWidget):
    """Manage configured audio sources from Settings."""

    sources_changed = pyqtSignal()

    def __init__(self, sources: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._sources = deepcopy(sources or [])
        self._import_worker: AudioSourceImportWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        description = QLabel(
            "导入 LX Music 格式的 .js 音源脚本。一个脚本支持的各音乐平台会自动拆分，"
            "并显示在“音频下载”的音源栏中。"
        )
        description.setWordWrap(True)
        description.setStyleSheet("color:#64748B")
        layout.addWidget(description)

        self.drop_zone = AudioSourceDropZone()
        self.drop_zone.files_dropped.connect(self._import_js_paths)
        self.drop_zone.clicked.connect(self._choose_js_files)
        layout.addWidget(self.drop_zone)

        self.import_status = QLabel("")
        self.import_status.setStyleSheet("color:#64748B;font-size:11px")
        self.import_status.hide()
        layout.addWidget(self.import_status)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["启用", "音源脚本", "平台", "版本", "支持音质"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_source)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.add_js_button = QPushButton("＋ 添加 JS 音源")
        self.add_js_button.setObjectName("primaryAction")
        self.add_js_button.clicked.connect(self._choose_js_files)
        actions.addWidget(self.add_js_button)
        toggle_button = QPushButton("启用 / 停用")
        toggle_button.clicked.connect(self._toggle_source)
        actions.addWidget(toggle_button)
        remove_button = QPushButton("移除")
        remove_button.clicked.connect(self._remove_source)
        actions.addWidget(remove_button)
        rest_button = QPushButton("添加 REST 音源")
        rest_button.clicked.connect(self._add_rest_source)
        actions.addWidget(rest_button)
        import_button = QPushButton("导入 REST JSON")
        import_button.clicked.connect(self._import_json)
        actions.addWidget(import_button)
        actions.addStretch()
        layout.addLayout(actions)
        self._refresh()

    def sources(self) -> list[dict]:
        return deepcopy(self._sources)

    def _refresh(self):
        self.table.setRowCount(len(self._sources))
        for row, source in enumerate(self._sources):
            is_lx = source.get("type") == "lx_js"
            metadata = source.get("metadata", {}) if is_lx else {}
            values = (
                "是" if source.get("enabled", True) else "否",
                metadata.get("name", source.get("name", "")),
                source.get("platform_name", "REST 接口"),
                metadata.get("version", "—"),
                " / ".join(source.get("qualities", [])),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def _choose_js_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加 LX JS 音源",
            "",
            "LX 音源脚本 (*.js);;JavaScript 文件 (*.js)",
        )
        if paths:
            self._import_js_paths(paths)

    def _import_js_paths(self, paths):
        valid_paths = [
            str(path)
            for path in paths
            if Path(path).is_file() and Path(path).suffix.casefold() == ".js"
        ]
        if not valid_paths:
            QMessageBox.information(self, "添加 JS 音源", "请拖入或选择 .js 文件。")
            return
        if self._import_worker and self._import_worker.isRunning():
            QMessageBox.information(self, "添加 JS 音源", "正在加载上一批音源，请稍候。")
            return
        self.add_js_button.setEnabled(False)
        self.drop_zone.setEnabled(False)
        self.import_status.setText(f"正在校验并加载 {len(valid_paths)} 个 JS 音源…")
        self.import_status.show()
        self._import_worker = AudioSourceImportWorker(valid_paths, self)
        self._import_worker.completed.connect(self._import_finished)
        self._import_worker.finished.connect(lambda: self.add_js_button.setEnabled(True))
        self._import_worker.finished.connect(lambda: self.drop_zone.setEnabled(True))
        self._import_worker.start()

    def _import_finished(self, imported, failures):
        if imported:
            replacement_keys = {
                (
                    item.get("metadata", {}).get("name", "").casefold(),
                    item.get("source_key", ""),
                )
                for item in imported
                if item.get("type") == "lx_js"
            }
            retained = [
                source
                for source in self._sources
                if source.get("type") != "lx_js"
                or (
                    source.get("metadata", {}).get("name", "").casefold(),
                    source.get("source_key", ""),
                )
                not in replacement_keys
            ]
            by_id = {source["id"]: source for source in retained}
            for source in imported:
                by_id[source["id"]] = source
            self._sources = list(by_id.values())
            self._refresh()
            self.sources_changed.emit()
        if failures:
            self.import_status.setText(
                f"已添加 {len(imported)} 个平台；{len(failures)} 个文件失败。"
            )
            QMessageBox.warning(self, "部分 JS 音源添加失败", "\n".join(failures))
        else:
            script_count = len({item.get("script_path") for item in imported})
            self.import_status.setText(
                f"添加成功：{script_count} 个脚本，{len(imported)} 个音乐平台。"
            )

    def _add_rest_source(self):
        dialog = AudioSourceEditDialog(parent=self)
        if not dialog.exec():
            return
        source = dialog.source()
        if any(item.get("id") == source["id"] for item in self._sources):
            QMessageBox.warning(self, "添加音源", "已有相同 ID 的音源。")
            return
        self._sources.append(source)
        self._refresh()
        self.sources_changed.emit()

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _toggle_source(self):
        row = self._selected_row()
        if row < 0:
            return
        self._sources[row]["enabled"] = not self._sources[row].get("enabled", True)
        self._refresh()
        self.table.selectRow(row)
        self.sources_changed.emit()

    def _edit_source(self, *_args):
        row = self._selected_row()
        if row < 0:
            return
        source = self._sources[row]
        if source.get("type") == "lx_js":
            metadata = source.get("metadata", {})
            QMessageBox.information(
                self,
                "JS 音源信息",
                "\n".join(
                    [
                        f"音源：{metadata.get('name', source.get('name', ''))}",
                        f"平台：{source.get('platform_name', '')}",
                        f"版本：{metadata.get('version') or '未标注'}",
                        f"作者：{metadata.get('author') or '未标注'}",
                        f"音质：{' / '.join(source.get('qualities', []))}",
                    ]
                ),
            )
            return
        dialog = AudioSourceEditDialog(source, self)
        if not dialog.exec():
            return
        updated = dialog.source()
        if any(
            index != row and item.get("id") == updated["id"]
            for index, item in enumerate(self._sources)
        ):
            QMessageBox.warning(self, "编辑音源", "已有相同 ID 的音源。")
            return
        self._sources[row] = updated
        self._refresh()
        self.sources_changed.emit()

    def _remove_source(self):
        row = self._selected_row()
        if row < 0:
            return
        del self._sources[row]
        self._refresh()
        self.sources_changed.emit()

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 REST 音源 JSON",
            "",
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            raw_sources = payload if isinstance(payload, list) else [payload]
            imported = [validate_source_config(source) for source in raw_sources]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "导入 REST 音源失败", str(exc))
            return
        by_id = {source["id"]: source for source in self._sources}
        for source in imported:
            by_id[source["id"]] = source
        self._sources = list(by_id.values())
        self._refresh()
        self.sources_changed.emit()
