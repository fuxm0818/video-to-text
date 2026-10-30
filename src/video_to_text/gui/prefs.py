"""Preferences window. Changes apply immediately and drive the next batch."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, config, core
from .common import open_path

TAB_OUTPUT, TAB_FORMAT, TAB_PERFORMANCE, TAB_GENERAL = range(4)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sheetText")
    label.setWordWrap(True)
    return label


class PreferencesDialog(QDialog):
    changed = Signal()

    def __init__(self, parent, settings: dict) -> None:
        super().__init__(parent)
        self.setObjectName("prefsDialog")
        self.setWindowTitle("偏好设置")
        self.setMinimumWidth(480)
        self._settings = dict(settings)
        self._loading = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_output(), "输出")
        self.tabs.addTab(self._build_format(), "格式")
        self.tabs.addTab(self._build_performance(), "性能")
        self.tabs.addTab(self._build_general(), "一般")
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.load(settings)
        self._loading = False

    # ------------------------------------------------------------- pages

    def _build_output(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(8)
        label = QLabel("保存位置")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.open_output_button = QPushButton("打开")
        self.open_output_button.clicked.connect(self._open_output)
        self.change_output_button = QPushButton("更改…")
        self.change_output_button.clicked.connect(self._pick_output)
        row.addWidget(self.output_edit, 1)
        row.addWidget(self.open_output_button)
        row.addWidget(self.change_output_button)
        layout.addLayout(row)
        layout.addWidget(_hint(
            "转写产物默认保存在“下载/视频转文字”，也可以点“更改…”另选文件夹；"
            "不存在的文件夹会自动创建。"
        ))
        layout.addStretch(1)
        return page

    def _build_format(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(8)
        label = QLabel("文稿格式")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.fmt_md = QCheckBox("Markdown")
        self.fmt_docx = QCheckBox("Word")
        row = QHBoxLayout()
        row.setSpacing(24)
        row.addWidget(self.fmt_md)
        row.addWidget(self.fmt_docx)
        row.addStretch(1)
        layout.addLayout(row)

        audio_label = QLabel("音频")
        audio_label.setObjectName("fieldLabel")
        layout.addWidget(audio_label)
        self.audio_combo = QComboBox()
        self.audio_combo.addItem("M4A", "m4a")
        self.audio_combo.addItem("WAV", "wav")
        self.audio_combo.addItem("不导出", "none")
        self.audio_combo.setFixedWidth(160)
        layout.addWidget(self.audio_combo)
        self.valid_hint = _hint("至少保留一种输出。")
        self.valid_hint.hide()
        layout.addWidget(self.valid_hint)
        layout.addStretch(1)

        for box in (self.fmt_md, self.fmt_docx):
            box.toggled.connect(self._changed)
        self.audio_combo.currentIndexChanged.connect(self._changed)
        return page

    def _build_performance(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(8)
        label = QLabel("同时转写文件数")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.workers_combo = QComboBox()
        for value in (1, 2, 3, 4):
            self.workers_combo.addItem(str(value), value)
        self.workers_combo.setFixedWidth(160)
        layout.addWidget(self.workers_combo)
        layout.addWidget(
            _hint("并发 2 提高总吞吐但更吃内存，16 GB 内存建议 1–2。每路线程数会按核数自动分配。")
        )
        layout.addStretch(1)
        self.workers_combo.currentIndexChanged.connect(self._changed)
        return page

    def _build_general(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(10)
        self.force_check = QCheckBox("重新转写已存在的文稿")
        self.force_check.toggled.connect(self._changed)
        layout.addWidget(self.force_check)
        layout.addWidget(_hint("关闭时，已有同一来源的文稿会直接跳过。"))

        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        version_label = QLabel(f"{__version__} · MIT")
        form.addRow(QLabel("版本"), version_label)
        log_row = QWidget()
        log_layout = QHBoxLayout(log_row)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(8)
        self.log_path_label = QLabel()
        self.log_path_label.setObjectName("sheetText")
        open_log = QPushButton("打开日志文件")
        open_log.clicked.connect(self._open_log)
        log_layout.addWidget(self.log_path_label, 1)
        log_layout.addWidget(open_log)
        form.addRow(QLabel("运行日志"), log_row)
        layout.addLayout(form)
        layout.addWidget(_hint("全部在本机完成，不上传、不联网。"))
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- state

    def load(self, settings: dict) -> None:
        self._settings = dict(settings)
        was_loading = self._loading
        self._loading = True
        self.output_edit.setText(settings["output_dir"])
        self.output_edit.setToolTip(settings["output_dir"])
        formats = settings.get("formats") or []
        self.fmt_md.setChecked("md" in formats)
        self.fmt_docx.setChecked("docx" in formats)
        self.audio_combo.setCurrentIndex(
            max(0, self.audio_combo.findData(settings.get("audio_format", "m4a")))
        )
        self.workers_combo.setCurrentIndex(
            max(0, self.workers_combo.findData(int(settings.get("workers") or 1)))
        )
        self.force_check.setChecked(bool(settings.get("force")))
        self.log_path_label.setText(str(core.log_path()))
        self.valid_hint.hide()
        self._loading = was_loading

    def open_tab(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)

    def _pick_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择保存文件夹", self.output_edit.text() or str(Path.home())
        )
        if folder:
            self.output_edit.setText(folder)
            self.output_edit.setToolTip(folder)
            self._changed()

    def _open_output(self) -> None:
        folder = Path(
            self.output_edit.text().strip() or config.default_output_dir()
        ).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法打开文件夹", str(exc))
            return
        open_path(folder)

    def _collect(self) -> dict:
        formats = []
        if self.fmt_md.isChecked():
            formats.append("md")
        if self.fmt_docx.isChecked():
            formats.append("docx")
        return {
            "output_dir": self.output_edit.text().strip(),
            "formats": formats,
            "audio_format": self.audio_combo.currentData(),
            "workers": self.workers_combo.currentData(),
            "force": self.force_check.isChecked(),
        }

    def _valid(self) -> bool:
        return bool(self.fmt_md.isChecked() or self.fmt_docx.isChecked()) or (
            self.audio_combo.currentData() != "none"
        )

    def _changed(self, *_args) -> None:
        if self._loading:
            return
        if not self._valid():
            self.valid_hint.show()
            return
        self.valid_hint.hide()
        self._settings = config.save_settings(self._collect())
        self.changed.emit()

    def _open_log(self) -> None:
        open_path(core.log_path())

    def _ensure_valid(self) -> None:
        if not self._valid():
            self.fmt_md.setChecked(True)
            self._changed()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._ensure_valid()
        super().closeEvent(event)
