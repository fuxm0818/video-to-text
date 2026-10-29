"""Native Qt desktop application."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QSize, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__, config, core
from .jobs import JobManager
from .theme import stylesheet

APP_TITLE = "视频转文字"
ASSETS = Path(__file__).resolve().parent / "assets"
MEDIA_FILTER = (
    "视频和音频 (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.ts *.flv *.wmv "
    "*.m4a *.mp3 *.wav *.aac *.flac *.ogg *.opus *.wma);;所有文件 (*)"
)
STATUS_TEXT = {
    "queued": "待转写",
    "running": "转写中",
    "done": "完成",
    "failed": "失败",
    "skipped": "跳过",
    "canceled": "已取消",
}
KIND_LABEL = {"md": "MD", "docx": "DOCX"}


def fmt_clock(seconds: float) -> str:
    total = max(0, int(round(seconds or 0)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_size(size: float) -> str:
    value = float(size or 0)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024:
            return f"{value:.0f} {unit}" if value >= 100 else f"{value:.1f} {unit}"
    return f"{value:.0f} TB"


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _asset_icon(name: str) -> QIcon:
    path = ASSETS / "icons" / name
    return QIcon(str(path)) if path.is_file() else QIcon()


DETAIL_ROLE = Qt.UserRole + 1
FAILED_ROLE = Qt.UserRole + 2


class FileCellDelegate(QStyledItemDelegate):
    """File column: name on the first line, size/duration/status underneath."""

    def paint(self, painter, option, index):  # noqa: N802 - Qt signature
        painter.save()
        rect = option.rect
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#f6ece6"))
        content = rect.adjusted(4, 6, -8, -6)

        name_font = QFont(option.font)
        name_font.setWeight(QFont.Medium)
        painter.setFont(name_font)
        painter.setPen(QColor("#241f19"))
        name_metrics = QFontMetrics(name_font)
        name = name_metrics.elidedText(
            str(index.data(Qt.DisplayRole) or ""), Qt.ElideMiddle, content.width()
        )
        painter.drawText(content, Qt.AlignLeft | Qt.AlignTop, name)

        detail_font = QFont(option.font)
        detail_font.setPointSizeF(max(8.0, option.font.pointSizeF() - 1.5))
        painter.setFont(detail_font)
        painter.setPen(QColor("#a33b2b" if index.data(FAILED_ROLE) else "#8a7f70"))
        detail_metrics = QFontMetrics(detail_font)
        detail = detail_metrics.elidedText(
            str(index.data(DETAIL_ROLE) or ""), Qt.ElideRight, content.width()
        )
        painter.drawText(
            content.adjusted(0, name_metrics.height() + 3, 0, 0),
            Qt.AlignLeft | Qt.AlignTop,
            detail,
        )
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802 - Qt signature
        return QSize(0, 54)


class TaskRow:
    """Widgets backing one file in the task table."""

    ROW_HEIGHT = 54

    def __init__(self, tree: QTreeWidget, task_id: str) -> None:
        self.task_id = task_id
        self.item = QTreeWidgetItem()
        self.item.setData(0, Qt.UserRole, task_id)
        self.item.setSizeHint(0, QSize(0, self.ROW_HEIGHT))
        self.badge = QLabel()
        self.badge.setObjectName("statusBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedWidth(70)
        self.badge.setFixedHeight(22)
        self.badge_host = QWidget()
        self.badge_host.setFixedHeight(self.ROW_HEIGHT)
        badge_layout = QHBoxLayout(self.badge_host)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.addWidget(self.badge, 0, Qt.AlignVCenter)

        self.outputs = QWidget()
        self.outputs_layout = QHBoxLayout(self.outputs)
        self.outputs_layout.setContentsMargins(0, 16, 0, 16)
        self.outputs_layout.setSpacing(4)
        self.outputs_layout.addStretch(1)
        self.output_sig = ""

        self.remove = QPushButton("×")
        self.remove.setObjectName("rowRemove")
        self.remove.setFixedSize(24, 24)
        self.remove.setCursor(Qt.PointingHandCursor)
        self.remove.setToolTip("从列表移除")
        self.remove_connected = False
        self.remove_host = QWidget()
        self.remove_host.setFixedHeight(self.ROW_HEIGHT)
        remove_layout = QHBoxLayout(self.remove_host)
        remove_layout.setContentsMargins(0, 0, 0, 0)
        remove_layout.addWidget(self.remove, 0, Qt.AlignVCenter)

        tree.addTopLevelItem(self.item)
        tree.setItemWidget(self.item, 0, self.badge_host)
        tree.setItemWidget(self.item, 2, self.outputs)
        tree.setItemWidget(self.item, 3, self.remove_host)
        self.sig = ""


class MainWindow(QMainWindow):
    modelsReady = Signal(bool)

    def __init__(self, output_dir: str | None = None) -> None:
        super().__init__()
        self.manager = JobManager()
        self.settings = config.load_settings()
        if output_dir:
            self.settings["output_dir"] = str(Path(output_dir).expanduser())
        self._rows: dict[str, TaskRow] = {}
        self._order_key = ""
        self._log_text = ""
        self._models_ready: bool | None = None
        self._model_thread: threading.Thread | None = None
        self._last_dir = str(Path.home())
        self._job_finished = False
        self._running = False
        self._settings_store = QSettings("Fu Xiangming", "VideoToText")

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1024, 720)
        self.resize(1180, 860)
        icon_path = ASSETS / "icon.png"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setStyleSheet(stylesheet())
        self._build_ui()
        self._build_menu()
        self._load_window_state()
        self._apply_settings_to_ui()

        self.modelsReady.connect(self._on_models_ready)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(450)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()
        self._refresh(force=True)
        self._check_models()

    # ------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 18, 28, 10)
        outer.setSpacing(14)

        outer.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 2, 0)
        content_layout.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(16)
        splitter.addWidget(self._build_files_panel())
        splitter.addWidget(self._build_settings_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([700, 440])
        content_layout.addWidget(splitter)
        content_layout.addWidget(self._build_progress_panel())
        content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.setCentralWidget(root)

        self.statusBar().showMessage("全部在本机完成，不上传、不排队。")
        version_label = QLabel(f"v{__version__} · MIT")
        version_label.setObjectName("versionLabel")
        self.statusBar().addPermanentWidget(version_label)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(2, 0, 2, 6)
        layout.setSpacing(14)

        logo = QLabel()
        icon_path = ASSETS / "icon.png"
        if icon_path.is_file():
            pixmap = QPixmap(str(icon_path))
            logo.setPixmap(
                pixmap.scaled(46, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        logo.setFixedSize(46, 46)
        layout.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        eyebrow = QLabel("VIDEO → TEXT")
        eyebrow.setObjectName("eyebrow")
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        tagline = QLabel("把视频里的每一句话，变成可以读的文字。本地语音识别，导出 Markdown / Word / 音频。")
        tagline.setObjectName("tagline")
        titles.addWidget(eyebrow)
        titles.addWidget(title)
        titles.addWidget(tagline)
        layout.addLayout(titles)
        layout.addStretch(1)

        badge = QLabel("● 仅在本机运行")
        badge.setObjectName("localBadge")
        layout.addWidget(badge, 0, Qt.AlignVCenter)
        return header

    def _panel(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        return frame, layout

    def _panel_head(self, step: str, title: str) -> tuple[QHBoxLayout, QHBoxLayout]:
        row = QHBoxLayout()
        row.setSpacing(8)
        number = QLabel(step)
        number.setObjectName("step")
        name = QLabel(title)
        name.setObjectName("panelTitle")
        row.addWidget(number)
        row.addWidget(name)
        row.addStretch(1)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        row.addLayout(tools)
        return row, tools

    def _build_files_panel(self) -> QWidget:
        panel, layout = self._panel()
        head, tools = self._panel_head("01", "选择素材")
        self.file_count = QLabel("0 个文件")
        self.file_count.setObjectName("countLabel")
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("quiet")
        self.clear_button.clicked.connect(self._clear_files)
        tools.addWidget(self.file_count)
        tools.addWidget(self.clear_button)
        layout.addLayout(head)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.pick_files_button = QPushButton("选择视频 / 音频")
        self.pick_files_button.setIcon(_asset_icon("add.svg"))
        self.pick_files_button.setIconSize(QSize(16, 16))
        self.pick_files_button.clicked.connect(self._pick_files)
        self.pick_folder_button = QPushButton("选择文件夹")
        self.pick_folder_button.setIcon(_asset_icon("folder.svg"))
        self.pick_folder_button.setIconSize(QSize(16, 16))
        self.pick_folder_button.clicked.connect(self._pick_folder)
        actions.addWidget(self.pick_files_button)
        actions.addWidget(self.pick_folder_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        hint = QLabel("支持 mp4、mov、mkv、webm、mp3、m4a、wav 等常见格式；选择文件夹会递归读取。也可以把文件或文件夹拖进窗口。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.empty_page = QFrame()
        self.empty_page.setObjectName("dropZone")
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(20, 26, 20, 26)
        empty_layout.setSpacing(10)
        empty_icon = QLabel()
        empty_icon.setPixmap(_asset_icon("play-accent.svg").pixmap(30, 30))
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_title = QLabel("还没有选择素材")
        empty_title.setObjectName("dropTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_hint = QLabel("从上方按钮选择文件，或直接把文件、文件夹拖到这里。")
        empty_hint.setObjectName("dropHint")
        empty_hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch(1)

        self.table = QTreeWidget()
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["状态", "文件", "输出", ""])
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.setIndentation(0)
        self.table.setItemDelegateForColumn(1, FileCellDelegate(self.table))
        header = self.table.header()
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 78)
        self.table.setColumnWidth(2, 148)
        self.table.setColumnWidth(3, 30)
        for key in ("Delete", "Backspace"):
            remove_action = QAction(self.table)
            remove_action.setShortcut(QKeySequence(key))
            remove_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            remove_action.triggered.connect(self._remove_selected)
            self.table.addAction(remove_action)

        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.empty_page)
        self.table_stack.addWidget(self.table)
        self.table_stack.setMinimumHeight(220)
        layout.addWidget(self.table_stack, 1)

        tip = QLabel("选中一行按 Delete 可移除；转写完成后点 MD / DOCX / 音频按钮直接打开文件。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        return panel

    def _build_settings_panel(self) -> QWidget:
        panel, layout = self._panel()
        head, _ = self._panel_head("02", "输出设置")
        layout.addLayout(head)

        layout.addWidget(self._field_label("保存到"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setReadOnly(True)
        self.output_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.output_dir_button = QPushButton("更改")
        self.output_dir_button.clicked.connect(self._pick_output_dir)
        row.addWidget(self.output_dir_edit, 1)
        row.addWidget(self.output_dir_button)
        layout.addLayout(row)

        layout.addWidget(self._field_label("文稿格式"))
        formats_row = QHBoxLayout()
        formats_row.setSpacing(26)
        self.fmt_md = QCheckBox("Markdown  (.md)")
        self.fmt_docx = QCheckBox("Word  (.docx)")
        for box in (self.fmt_md, self.fmt_docx):
            box.toggled.connect(self._settings_changed)
            formats_row.addWidget(box)
        formats_row.addStretch(1)
        layout.addLayout(formats_row)

        layout.addWidget(self._field_label("同时导出音频"))
        self.audio_combo = QComboBox()
        self.audio_combo.addItem("M4A · 推荐，体积小", "m4a")
        self.audio_combo.addItem("WAV · 无损，体积大", "wav")
        self.audio_combo.addItem("不导出音频", "none")
        self.audio_combo.currentIndexChanged.connect(self._settings_changed)
        layout.addWidget(self.audio_combo)

        advanced_toggle = QToolButton()
        advanced_toggle.setObjectName("logToggle")
        advanced_toggle.setText("高级选项")
        advanced_toggle.setCheckable(True)
        advanced_toggle.setArrowType(Qt.RightArrow)
        advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        advanced_toggle.toggled.connect(
            lambda on: (
                advanced_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow),
                advanced_body.setVisible(on),
            )
        )
        layout.addWidget(advanced_toggle, 0, Qt.AlignLeft)

        advanced_body = QWidget()
        body = QVBoxLayout(advanced_body)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(8)
        body.addWidget(self._field_label("同时转写文件数"))
        self.workers_combo = QComboBox()
        for value, text in (
            (1, "1 · 低内存，适合 8 GB 内存"),
            (2, "2 · 推荐，适合 16 GB 内存"),
            (3, "3 · 适合 24 GB 以上"),
            (4, "4 · 适合 32 GB 以上"),
        ):
            self.workers_combo.addItem(text, value)
        self.workers_combo.currentIndexChanged.connect(self._settings_changed)
        body.addWidget(self.workers_combo)
        self.force_check = QCheckBox("重新转写已存在的文稿")
        self.force_check.toggled.connect(self._settings_changed)
        body.addWidget(self.force_check)
        advanced_body.setVisible(False)
        layout.addWidget(advanced_body)

        self.model_note = QFrame()
        self.model_note.setObjectName("modelNote")
        note_layout = QVBoxLayout(self.model_note)
        note_layout.setContentsMargins(12, 10, 12, 10)
        note_layout.setSpacing(3)
        self.model_note_title = QLabel("首次转写需要下载语音模型")
        self.model_note_title.setObjectName("modelNoteTitle")
        self.model_note_text = QLabel("约 2.1 GB，只需要一次；下载完成后可离线使用。")
        self.model_note_text.setObjectName("modelNoteText")
        self.model_note_text.setWordWrap(True)
        note_layout.addWidget(self.model_note_title)
        note_layout.addWidget(self.model_note_text)
        self.model_note.setVisible(False)
        layout.addWidget(self.model_note)

        layout.addStretch(1)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self.summary_label = QLabel("选择文件后即可开始转写")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.start_button = QPushButton("开始转写")
        self.start_button.setObjectName("startButton")
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.setIcon(_asset_icon("play-light.svg"))
        self.start_button.setIconSize(QSize(16, 16))
        self.start_button.setShortcut(QKeySequence("Ctrl+Return"))
        self.start_button.clicked.connect(self._start_job)
        layout.addWidget(self.start_button)
        self.start_hint = QLabel("先选择至少一个文件")
        self.start_hint.setObjectName("hint")
        self.start_hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.start_hint)
        return panel

    def _build_progress_panel(self) -> QWidget:
        panel, layout = self._panel()
        head, tools = self._panel_head("03", "转写进度")
        self.state_badge = QLabel("待开始")
        self.state_badge.setObjectName("stateBadge")
        tools.addWidget(self.state_badge)
        layout.addLayout(head)

        top = QHBoxLayout()
        top.setSpacing(12)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        self.progress_title = QLabel("等待开始")
        self.progress_title.setObjectName("progressTitle")
        self.progress_detail = QLabel("选择素材后，点击「开始转写」。")
        self.progress_detail.setObjectName("progressDetail")
        self.progress_detail.setWordWrap(True)
        copy.addWidget(self.progress_title)
        copy.addWidget(self.progress_detail)
        top.addLayout(copy, 1)

        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setObjectName("elapsedLabel")
        top.addWidget(self.elapsed_label, 0, Qt.AlignTop)
        self.open_output_button = QPushButton("打开输出文件夹")
        self.open_output_button.setIcon(_asset_icon("folder.svg"))
        self.open_output_button.clicked.connect(self._open_output_dir)
        top.addWidget(self.open_output_button, 0, Qt.AlignTop)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setIcon(_asset_icon("stop.svg"))
        self.cancel_button.clicked.connect(self._cancel_job)
        self.cancel_button.setVisible(False)
        top.addWidget(self.cancel_button, 0, Qt.AlignTop)
        layout.addLayout(top)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        stats = QHBoxLayout()
        stats.setSpacing(28)
        self.stat_done = self._stat(stats, "完成")
        self.stat_failed = self._stat(stats, "失败")
        self.stat_skipped = self._stat(stats, "跳过")
        self.stat_canceled = self._stat(stats, "取消")
        stats.addStretch(1)
        layout.addLayout(stats)

        log_row = QHBoxLayout()
        log_row.setSpacing(6)
        self.log_toggle = QToolButton()
        self.log_toggle.setObjectName("logToggle")
        self.log_toggle.setText("运行日志")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setArrowType(Qt.RightArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.log_toggle.toggled.connect(self._toggle_log)
        log_row.addWidget(self.log_toggle)
        log_row.addStretch(1)
        layout.addLayout(log_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(400)
        self.log_view.setFixedHeight(150)
        self.log_view.setVisible(False)
        layout.addWidget(self.log_view)
        return panel

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _stat(self, layout: QHBoxLayout, caption: str) -> QLabel:
        cell = QWidget()
        box = QVBoxLayout(cell)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        value = QLabel("0")
        value.setObjectName("statValue")
        label = QLabel(caption)
        label.setObjectName("statCaption")
        box.addWidget(value)
        box.addWidget(label)
        layout.addWidget(cell)
        return value

    # --------------------------------------------------------------- menu

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")

        open_files = QAction("选择视频 / 音频…", self)
        open_files.setShortcut(QKeySequence.Open)
        open_files.triggered.connect(self._pick_files)
        file_menu.addAction(open_files)

        open_folder = QAction("选择文件夹…", self)
        open_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        open_folder.triggered.connect(self._pick_folder)
        file_menu.addAction(open_folder)

        file_menu.addSeparator()
        open_output = QAction("打开输出文件夹", self)
        open_output.triggered.connect(self._open_output_dir)
        file_menu.addAction(open_output)

        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction(f"关于{APP_TITLE}", self)
        about_action.setMenuRole(QAction.AboutRole)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

        log_action = QAction("查看日志文件", self)
        log_action.triggered.connect(self._open_log_file)
        help_menu.addAction(log_action)

    # ------------------------------------------------------------- states

    def _apply_settings_to_ui(self) -> None:
        settings = self.settings
        self.output_dir_edit.setText(settings["output_dir"])
        self.output_dir_edit.setToolTip(settings["output_dir"])
        formats = settings.get("formats") or []
        self.fmt_md.setChecked("md" in formats)
        self.fmt_docx.setChecked("docx" in formats)
        index = self.audio_combo.findData(settings.get("audio_format", "m4a"))
        self.audio_combo.setCurrentIndex(max(0, index))
        index = self.workers_combo.findData(settings.get("workers", 1))
        self.workers_combo.setCurrentIndex(max(0, index))
        if settings["output_dir"]:
            self._last_dir = settings["output_dir"]

    def _read_settings(self) -> dict:
        formats = []
        if self.fmt_md.isChecked():
            formats.append("md")
        if self.fmt_docx.isChecked():
            formats.append("docx")
        return {
            "output_dir": self.output_dir_edit.text().strip(),
            "formats": formats,
            "audio_format": self.audio_combo.currentData(),
            "workers": self.workers_combo.currentData(),
        }

    def _settings_valid(self) -> bool:
        return bool(self.fmt_md.isChecked() or self.fmt_docx.isChecked()) or (
            self.audio_combo.currentData() != "none"
        )

    def _settings_changed(self, *_args) -> None:
        self.settings = config.save_settings(self._read_settings())
        self._update_controls()

    def _load_window_state(self) -> None:
        geometry = self._settings_store.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _save_window_state(self) -> None:
        self._settings_store.setValue("window/geometry", self.saveGeometry())

    # -------------------------------------------------------------- files

    def _pick_files(self) -> None:
        if self._running:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频或音频文件", self._last_dir, MEDIA_FILTER
        )
        if files:
            self._last_dir = str(Path(files[0]).parent)
            self._add_paths(files)

    def _pick_folder(self) -> None:
        if self._running:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择视频所在文件夹", self._last_dir)
        if folder:
            self._last_dir = folder
            self._add_paths([folder])

    def _add_paths(self, paths: list[str]) -> None:
        if self._running:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            added, skipped = self.manager.add_paths(
                paths, Path(self.settings["output_dir"]).expanduser()
            )
        except (RuntimeError, core.TranscriptionError) as exc:
            QMessageBox.warning(self, "无法添加素材", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        if added and skipped:
            message = f"已添加 {added} 个文件，{skipped} 个已在列表中"
        elif added:
            message = f"已添加 {added} 个文件"
        elif skipped:
            message = "这些文件已经在列表里了"
        else:
            message = "没有找到可处理的音视频文件"
        self.statusBar().showMessage(message, 6000)
        self._refresh(force=True)

    def _clear_files(self) -> None:
        if self._running:
            return
        self.manager.clear()
        self._refresh(force=True)

    def _remove_ids(self, ids: list[str]) -> None:
        if self._running:
            return
        for task_id in ids:
            try:
                self.manager.remove(task_id)
            except RuntimeError:
                return
        self._refresh(force=True)

    def _selected_ids(self) -> list[str]:
        ids = []
        for item in self.table.selectedItems():
            task_id = item.data(0, Qt.UserRole)
            if task_id and task_id not in ids:
                ids.append(task_id)
        return ids

    def _table_menu(self, position) -> None:
        item = self.table.itemAt(position)
        if item is not None:
            self.table.setCurrentItem(item)
        menu = QMenu(self)
        if item is not None:
            task_id = item.data(0, Qt.UserRole)
            task = self.manager.task_by_id(task_id)
            if task is not None:
                reveal = menu.addAction("在文件夹中显示源文件")
                reveal.triggered.connect(lambda: self._reveal(task.path))
                remove = menu.addAction("从列表移除")
                remove.setEnabled(not self._running)
                remove.triggered.connect(lambda: self._remove_ids([task_id]))
                menu.addSeparator()
        clear = menu.addAction("清空列表")
        clear.setEnabled(bool(self.manager.snapshot()["tasks"]) and not self._running)
        clear.triggered.connect(self._clear_files)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _remove_selected(self) -> None:
        ids = self._selected_ids()
        if ids:
            self._remove_ids(ids)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            event.acceptProposedAction()
            self._add_paths(paths)

    # ------------------------------------------------------------ actions

    def _pick_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择保存文件夹", self.output_dir_edit.text() or self._last_dir
        )
        if folder:
            self.output_dir_edit.setText(folder)
            self.output_dir_edit.setToolTip(folder)
            self._last_dir = folder
            self._settings_changed()

    def _start_job(self) -> None:
        if self._running:
            return
        if not self._settings_valid():
            self.statusBar().showMessage("请至少选择 Markdown、Word 或音频中的一种输出", 6000)
            return
        self.settings = config.save_settings(self._read_settings())
        snapshot = self.manager.snapshot()
        if not snapshot["tasks"]:
            self.statusBar().showMessage("请先选择视频或音频文件", 6000)
            return
        try:
            self.manager.start(
                Path(self.settings["output_dir"]).expanduser(),
                list(self.settings.get("formats") or []),
                self.settings.get("audio_format", "m4a"),
                int(self.settings.get("workers") or 1),
                self.force_check.isChecked(),
            )
        except (RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "无法开始转写", str(exc))
            return
        self._job_finished = False
        if self._models_ready is False:
            self.statusBar().showMessage(
                "首次运行需要下载语音模型（约 2.1 GB），请保持网络连接", 9000
            )
        self._refresh(force=True)

    def _cancel_job(self) -> None:
        if self.manager.cancel():
            self.statusBar().showMessage("正在取消，已完成的输出会保留…", 5000)

    def _output_dir(self) -> Path:
        snapshot = self.manager.snapshot()
        return Path(snapshot.get("output_dir") or self.settings["output_dir"]).expanduser()

    def _open_output_dir(self) -> None:
        folder = self._output_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            core.open_folder(folder)
        except OSError as exc:
            QMessageBox.warning(self, "无法打开文件夹", str(exc))

    def _open_output(self, task_id: str, kind: str) -> None:
        task = self.manager.task_by_id(task_id)
        if task is None:
            return
        filename = task.outputs.get(kind)
        if not filename:
            return
        path = self._output_dir() / filename
        if not path.is_file():
            QMessageBox.warning(self, "文件不存在", f"找不到输出文件：\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _reveal(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _toggle_log(self, visible: bool) -> None:
        self.log_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        self.log_view.setVisible(visible)
        if visible:
            self._scroll_log_to_end()

    def _scroll_log_to_end(self) -> None:
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _open_log_file(self) -> None:
        path = core.log_path()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return
        QMessageBox.information(self, "运行日志", f"日志文件还不存在：\n{path}")

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"关于{APP_TITLE}",
            (
                f"<b>{APP_TITLE}</b> {__version__}<br><br>"
                "把本地视频或音频里的说话声转成 Markdown / Word 文稿，"
                "并同时导出音频文件。所有处理都在本机完成，不上传、不排队。<br><br>"
                "语音识别：FunASR Paraformer / FSMN-VAD / CT-Punc<br>"
                "License: MIT"
            ),
        )

    # -------------------------------------------------------------- models

    def _check_models(self) -> None:
        if self._model_thread is not None and self._model_thread.is_alive():
            return

        def work() -> None:
            try:
                ready = core.models_cached()
            except Exception:
                ready = False
            self.modelsReady.emit(ready)

        self._model_thread = threading.Thread(target=work, daemon=True)
        self._model_thread.start()

    def _on_models_ready(self, ready: bool) -> None:
        self._models_ready = ready
        self._update_model_note()

    def _wants_text(self) -> bool:
        return self.fmt_md.isChecked() or self.fmt_docx.isChecked()

    def _update_model_note(self, running: bool | None = None,
                           model_state: str | None = None) -> None:
        if running is None:
            running = self._running
        if model_state is None:
            model_state = str(self.manager.snapshot()["job"].get("model_state") or "")
        downloading = running and model_state in {"checking", "downloading"}
        show = self._wants_text() and (self._models_ready is False or downloading)
        self.model_note.setVisible(show)
        if downloading:
            self.model_note_title.setText("正在准备语音模型")
            self.model_note_text.setText("首次运行需要下载约 2.1 GB 的模型，请保持网络连接。")
        else:
            self.model_note_title.setText("首次转写需要下载语音模型")
            self.model_note_text.setText("约 2.1 GB，只需要一次；下载完成后可离线使用。")

    # ---------------------------------------------------------- table view

    def _refresh(self, force: bool = False) -> None:
        snapshot = self.manager.snapshot()
        self._apply_job(snapshot)
        self._apply_tasks(snapshot["tasks"], snapshot["job"])
        self._apply_logs(snapshot["logs"])
        self._update_controls(snapshot)
        if self._job_finished:
            self._job_finished = False
            self._check_models()

    def _apply_tasks(self, tasks: list[dict], job: dict) -> None:
        order_key = ",".join(task["id"] for task in tasks)
        if order_key != self._order_key:
            self._order_key = order_key
            self._rebuild_rows(tasks)
            self.table_stack.setCurrentWidget(self.table if tasks else self.empty_page)
            self.file_count.setText(f"{len(tasks)} 个文件")
        for task in tasks:
            self._update_row(task, job)
        if not tasks:
            self.file_count.setText("0 个文件")

    def _rebuild_rows(self, tasks: list[dict]) -> None:
        self.table.clear()
        self._rows.clear()
        for task in tasks:
            self._rows[task["id"]] = TaskRow(self.table, task["id"])

    def _update_row(self, task: dict, job: dict) -> None:
        row = self._rows.get(task["id"])
        if row is None:
            return
        elapsed = int(float(task.get("elapsed") or 0))
        sig = "|".join(
            str(part)
            for part in (
                task["status"],
                task["stage"],
                int(float(task.get("duration") or 0)),
                elapsed,
                task.get("message", ""),
                task.get("error", ""),
                task.get("reused"),
                len(task.get("warnings") or []),
                task["outputs"],
            )
        )
        if sig == row.sig:
            self._update_remove_state(row)
            return
        row.sig = sig

        status = task["status"]
        if status == "queued":
            text = "排队中" if job["running"] else "待转写"
        elif status == "running":
            text = task.get("stage_label") or "转写中"
        else:
            text = STATUS_TEXT.get(status, status)
        if row.badge.text() != text:
            row.badge.setText(text)
        state = status if status in {"running", "done", "failed", "skipped", "canceled"} else "queued"
        if row.badge.property("state") != state:
            row.badge.setProperty("state", state)
            _repolish(row.badge)

        row.item.setText(1, task["name"])
        info = []
        if task.get("duration"):
            info.append(fmt_clock(task["duration"]))
        if task.get("size"):
            info.append(fmt_size(task["size"]))

        detail = ""
        if status == "running":
            detail = task.get("stage_label") or "处理中"
            if elapsed:
                detail += f" · {fmt_clock(elapsed)}"
        elif status == "queued":
            detail = "等待开始"
        elif status == "done":
            detail = f"用时 {fmt_clock(task.get('elapsed'))}" if task.get("elapsed") else "完成"
            if task.get("reused"):
                detail += " · 复用已有文稿"
        elif status == "failed":
            detail = task.get("error") or "失败"
        elif status == "skipped":
            detail = task.get("message") or "输出已存在"
        elif status == "canceled":
            detail = "已取消"
        line = " · ".join(info + ([detail] if detail else []))
        row.item.setData(1, DETAIL_ROLE, line)
        row.item.setData(1, FAILED_ROLE, status == "failed")

        tips = [task["path"], line]
        warnings = task.get("warnings") or []
        if warnings:
            tips.append("提示：" + "；".join(warnings))
        row.item.setToolTip(1, "\n".join(part for part in tips if part))

        outputs = task.get("outputs") or {}
        output_sig = "|".join(f"{kind}={outputs[kind]}" for kind in ("md", "docx", "audio") if kind in outputs)
        if output_sig != row.output_sig:
            row.output_sig = output_sig
            while row.outputs_layout.count():
                item = row.outputs_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            for kind in ("md", "docx", "audio"):
                filename = outputs.get(kind)
                if not filename:
                    continue
                label = KIND_LABEL.get(kind) or Path(filename).suffix.lstrip(".").upper() or "音频"
                chip = QPushButton(label)
                chip.setObjectName("outputChip")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                chip.setToolTip(f"打开 {filename}")
                chip.clicked.connect(
                    lambda _checked=False, tid=task["id"], k=kind: self._open_output(tid, k)
                )
                row.outputs_layout.addWidget(chip)
            row.outputs_layout.addStretch(1)

        self._update_remove_state(row)

    def _update_remove_state(self, row: TaskRow) -> None:
        row.remove.setEnabled(not self._running)
        if not row.remove_connected:
            row.remove.clicked.connect(
                lambda _checked=False, tid=row.task_id: self._remove_ids([tid])
            )
            row.remove_connected = True

    # ------------------------------------------------------------- job view

    def _apply_job(self, snapshot: dict) -> None:
        job = snapshot["job"]
        self._running = bool(job["running"])
        tasks = snapshot["tasks"]
        total = len(tasks)
        counts = {"done": 0, "failed": 0, "skipped": 0, "canceled": 0}
        for task in tasks:
            if task["status"] in counts:
                counts[task["status"]] += 1
        finished = sum(counts.values())
        percent = round(finished / total * 100) if total else 0
        if job["state"] == "done" and total:
            percent = 100

        self.progress_bar.setValue(percent)
        self.stat_done.setText(str(counts["done"]))
        self.stat_failed.setText(str(counts["failed"]))
        self.stat_skipped.setText(str(counts["skipped"]))
        self.stat_canceled.setText(str(counts["canceled"]))
        self.elapsed_label.setText(fmt_clock(job.get("elapsed") or 0))

        state = ""
        state_text = "待开始"
        if job["running"]:
            state = "running"
            state_text = "取消中" if job["canceling"] else "运行中"
        elif job["state"] == "canceled":
            state = "canceled"
            state_text = "已取消"
        elif job["state"] == "done":
            state = "done"
            state_text = "已完成"
        if state_text != self.state_badge.text():
            self.state_badge.setText(state_text)
        if self.state_badge.property("state") != state:
            self.state_badge.setProperty("state", state)
            _repolish(self.state_badge)

        title = "等待开始"
        detail = "选择素材后，点击「开始转写」。"
        if job["running"]:
            if job.get("model_state") == "downloading":
                title = "正在下载语音模型"
            elif job.get("model_state") == "checking":
                title = "正在检查语音模型"
            else:
                title = f"正在转写 · {percent}%"
            detail = job.get("message") or "准备中…"
        elif job["state"] == "canceled":
            title = "转写已停止"
            detail = "已停止剩余任务，已完成的输出会保留。"
        elif job["state"] == "done":
            if total and not counts["done"] and not counts["failed"]:
                title = "无需转写"
            elif counts["failed"]:
                title = "转写未完成"
            else:
                title = "转写完成"
            detail = job.get("message") or "全部任务已结束。"
        elif total:
            title = "准备就绪"
            detail = f"共 {total} 个文件，点击「开始转写」。"
        self.progress_title.setText(title)
        self.progress_detail.setText(detail)

        window_title = f"转写中 {percent}% · {APP_TITLE}" if job["running"] else APP_TITLE
        if window_title != self.windowTitle():
            self.setWindowTitle(window_title)

        finished_now = bool(job["state"] in {"done", "canceled"} and job["finished_at"])
        if finished_now and not self._job_finished:
            self._job_finished = True
            if counts["failed"] and not self.log_toggle.isChecked():
                self.log_toggle.setChecked(True)
        self._update_model_note(running=job["running"],
                                model_state=str(job.get("model_state") or ""))

    def _apply_logs(self, logs: list[dict]) -> None:
        lines = []
        for entry in logs:
            stamp = time.strftime("%H:%M:%S", time.localtime(entry.get("t") or 0))
            mark = {"error": "×", "warn": "!"}.get(entry.get("level"), "·")
            who = f'[{entry["task"]}] ' if entry.get("task") else ""
            lines.append(f"{stamp}  {mark} {who}{entry.get('message', '')}")
        text = "\n".join(lines)
        if text == self._log_text:
            return
        bar = self.log_view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        previous = bar.value()
        self._log_text = text
        self.log_view.setPlainText(text)
        if at_end:
            self._scroll_log_to_end()
        else:
            bar.setValue(previous)

    def _update_controls(self, snapshot: dict | None = None) -> None:
        if snapshot is None:
            snapshot = self.manager.snapshot()
        job = snapshot["job"]
        tasks = snapshot["tasks"]
        running = bool(job["running"])
        self._running = running

        for widget in (
            self.pick_files_button,
            self.pick_folder_button,
            self.output_dir_button,
            self.fmt_md,
            self.fmt_docx,
            self.audio_combo,
            self.workers_combo,
            self.force_check,
        ):
            widget.setEnabled(not running)
        for task_id in self._rows:
            row = self._rows[task_id]
            row.remove.setEnabled(not running)
        self.clear_button.setEnabled(bool(tasks) and not running)
        self.clear_button.setVisible(bool(tasks))

        self.start_button.setEnabled(bool(tasks) and not running and self._settings_valid())
        pieces = []
        if self.fmt_md.isChecked():
            pieces.append("Markdown")
        if self.fmt_docx.isChecked():
            pieces.append("Word")
        audio = self.audio_combo.currentData()
        if audio != "none":
            pieces.append(f"{str(audio).upper()} 音频")
        if not pieces:
            summary = "请至少选择一种输出内容"
        elif not tasks:
            summary = "选择文件后转写为 " + " + ".join(pieces)
        else:
            summary = f"{len(tasks)} 个文件 → " + " + ".join(pieces)
        self.summary_label.setText(summary)

        if running:
            hint = "正在转写中，请稍候"
        elif not self._settings_valid():
            hint = "请至少选择 Markdown、Word 或音频中的一种"
        elif not tasks:
            hint = "先选择至少一个文件"
        else:
            total_seconds = sum(float(task.get("duration") or 0) for task in tasks)
            hint = (
                f"共 {fmt_clock(total_seconds)} · Ctrl+Enter 开始"
                if total_seconds
                else "按 Ctrl+Enter 开始转写"
            )
        self.start_hint.setText(hint)

        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running and not job["canceling"])
        self.open_output_button.setEnabled(bool(self.settings["output_dir"]))

    # ------------------------------------------------------------ shutdown

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt signature
        snapshot = self.manager.snapshot()
        if snapshot["job"]["running"]:
            answer = QMessageBox.question(
                self,
                "退出",
                "正在转写，退出会中断任务。确定退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self._save_window_state()
        self._refresh_timer.stop()
        self.manager.shutdown()
        event.accept()


def run_gui(output_dir: str | None = None) -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.fuxiangming.videototext"
            )
        except Exception:
            pass

    QApplication.setApplicationName(APP_TITLE)
    QApplication.setApplicationDisplayName(APP_TITLE)
    QApplication.setOrganizationName("Fu Xiangming")
    app = QApplication.instance() or QApplication(sys.argv[:1])

    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Light)

    font = QFont()
    font.setFamilies(
        ["PingFang SC", "Microsoft YaHei UI", "Segoe UI", "Noto Sans CJK SC", "sans-serif"]
    )
    font.setPointSize(12 if sys.platform == "darwin" else 10)
    app.setFont(font)

    icon_path = ASSETS / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(output_dir=output_dir)
    window.show()
    return app.exec()
