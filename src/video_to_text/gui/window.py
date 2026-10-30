"""Main window: toolbar, sidebar, task table, status strip and log drawer."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QSize, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import config, core, styles, tokens
from ..jobs import JobManager
from . import about as about_dialog
from .common import (
    APP_TITLE,
    ASSETS,
    MEDIA_FILTER,
    display_path,
    fmt_clock,
    fmt_decimal_size,
    fmt_size,
    media_paths,
    open_path,
    output_summary,
    repolish,
    reveal_path,
)
from .icons import drop_pixmap, icon
from .modelsheet import ModelSheet
from .prefs import TAB_FORMAT, PreferencesDialog
from .sidebar import Sidebar
from .statusbar import LogDrawer, StatusStrip
from .tasklist import TaskList


class DropOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        accent = QApplication.palette().color(QPalette.Highlight)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        fill = QColor(accent)
        fill.setAlpha(18)
        painter.fillRect(self.rect(), fill)
        pen = QPen(accent, 1.0, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 8, 8)


class ContentArea(QWidget):
    pathsDropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("contentArea")
        self.setAcceptDrops(True)
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentStack")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack)
        self.overlay = DropOverlay(self)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        paths = media_paths(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self.overlay.setGeometry(self.rect())
            self.overlay.raise_()
            self.overlay.show()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if media_paths(event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.overlay.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.overlay.hide()
        paths = media_paths(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self.pathsDropped.emit(paths)
        else:
            event.ignore()


class MainWindow(QMainWindow):
    def __init__(self, output_dir: str | None = None) -> None:
        super().__init__()
        self.manager = JobManager()
        self.settings = config.load_settings()
        if output_dir:
            self.settings["output_dir"] = str(Path(output_dir).expanduser())
        state_dir = config.config_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        self._store = QSettings(str(state_dir / "window.ini"), QSettings.IniFormat)
        self._last_dir = str(Path.home())
        self._running = False
        self._job_finished = False
        self._job: dict = {}
        self._tasks: list[dict] = []
        self._counts: dict[str, int] = {}
        self._prefs: PreferencesDialog | None = None
        self._model_sheet: ModelSheet | None = None
        self._model_sheet_dismissed = False
        self._flash_message = ""
        self._flash_until = 0.0
        self._flash_token = 0
        self._applying_theme = False
        self._log_height = 180
        self._icon_key = None

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(900, 600)
        self.resize(980, 660)
        icon_path = Path(ASSETS) / "icon.png"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        if hasattr(self, "setUnifiedTitleAndToolBarOnMac"):
            self.setUnifiedTitleAndToolBarOnMac(True)

        self._build_actions()
        self._build_toolbar()
        self._build_central()
        self._build_menus()
        self._connect()
        self._restore_state()
        self._apply_settings_ui()
        self._install_theme()
        self._refresh(force=True)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()

    # ------------------------------------------------------------- build

    def _build_actions(self) -> None:
        self.add_files_action = QAction("选择文件…", self)
        self.add_files_action.setShortcut(QKeySequence.Open)
        self.add_files_action.triggered.connect(self._pick_files)

        self.add_folder_action = QAction("选择文件夹…", self)
        self.add_folder_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.add_folder_action.triggered.connect(self._pick_folder)

        self.open_output_action = QAction(
            "在访达中显示" if sys.platform == "darwin" else "打开输出文件夹", self
        )
        self.open_output_action.triggered.connect(self._open_output_dir)

        self.clear_action = QAction("清空列表", self)
        self.clear_action.triggered.connect(self._clear_files)

        self.close_action = QAction("关闭窗口", self)
        self.close_action.setShortcut(QKeySequence.Close)
        self.close_action.triggered.connect(self.close)

        self.remove_action = QAction("移除选中", self)
        self.remove_action.setShortcuts([QKeySequence("Backspace"), QKeySequence("Delete")])
        self.remove_action.triggered.connect(self._remove_selected)

        self.start_action = QAction("开始转写", self)
        self.start_action.setShortcut(QKeySequence("Ctrl+Return"))
        self.start_action.triggered.connect(self._start_job)

        self.stop_action = QAction("停止", self)
        self.stop_action.setShortcut(QKeySequence("Ctrl+."))
        self.stop_action.triggered.connect(self._cancel_job)

        self.force_action = QAction("重新转写已存在的文稿", self)
        self.force_action.setCheckable(True)
        self.force_action.toggled.connect(self._force_toggled)

        self.log_action = QAction("查看日志", self)
        self.log_action.setCheckable(True)
        self.log_action.setShortcut(QKeySequence("Ctrl+L"))
        self.log_action.toggled.connect(self._set_log_visible)

        self.open_log_action = QAction("打开日志文件", self)
        self.open_log_action.setShortcut(QKeySequence("Ctrl+Alt+L"))
        self.open_log_action.triggered.connect(self._open_log_file)

        self.prefs_action = QAction("偏好设置…", self)
        self.prefs_action.setShortcut(QKeySequence("Ctrl+,"))
        self.prefs_action.setMenuRole(QAction.PreferencesRole)
        self.prefs_action.triggered.connect(self._open_prefs)

        self.about_action = QAction(f"关于{APP_TITLE}", self)
        self.about_action.setMenuRole(QAction.AboutRole)
        self.about_action.triggered.connect(lambda: about_dialog.show_about(self))

    def _build_toolbar(self) -> None:
        bar = QToolBar("主工具栏")
        bar.setObjectName("mainToolBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(bar)

        self.add_button = QToolButton()
        self.add_button.setText("添加")
        self.add_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.add_button.setPopupMode(QToolButton.InstantPopup)
        self.add_button.setToolTip("添加文件或文件夹")
        add_menu = QMenu(self.add_button)
        add_menu.addAction(self.add_files_action)
        add_menu.addAction(self.add_folder_action)
        self.add_button.setMenu(add_menu)
        bar.addWidget(self.add_button)

        self.remove_button = QToolButton()
        self.remove_button.setText("移除")
        self.remove_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.remove_button.setToolTip("从列表移除选中的文件")
        self.remove_button.clicked.connect(self.remove_action.trigger)
        bar.addWidget(self.remove_button)

        bar.addSeparator()

        self.start_button = QPushButton("开始转写")
        self.start_button.setObjectName("primary")
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.setMinimumWidth(104)
        self.start_button.clicked.connect(self._start_or_stop)
        bar.addWidget(self.start_button)

        bar.addSeparator()

        self.output_button = QToolButton()
        self.output_button.setText("输出")
        self.output_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.output_button.setToolTip("打开输出文件夹")
        self.output_button.clicked.connect(self._open_output_dir)
        bar.addWidget(self.output_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        self.prefs_button = QToolButton()
        self.prefs_button.setToolTip("偏好设置")
        self.prefs_button.clicked.connect(lambda: self._open_prefs(0))
        bar.addWidget(self.prefs_button)

    def _build_central(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(1)

        self.sidebar = Sidebar()
        self.main_splitter.addWidget(self.sidebar)

        self.content = ContentArea()
        self.empty_page = self._build_empty_page()
        self.table = TaskList()
        self.content.stack.addWidget(self.empty_page)
        self.content.stack.addWidget(self.table)
        self.main_splitter.addWidget(self.content)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([200, 780])

        self.log_drawer = LogDrawer()
        self.log_drawer.hide()
        self.log_splitter = QSplitter(Qt.Vertical)
        self.log_splitter.setObjectName("logSplitter")
        self.log_splitter.setChildrenCollapsible(False)
        self.log_splitter.setHandleWidth(1)
        self.log_splitter.addWidget(self.main_splitter)
        self.log_splitter.addWidget(self.log_drawer)
        self.log_splitter.setStretchFactor(0, 1)
        self.log_splitter.setStretchFactor(1, 0)

        self.status = StatusStrip()
        layout.addWidget(self.log_splitter, 1)
        layout.addWidget(self.status)
        self.setCentralWidget(central)

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("emptyPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)

        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_icon)
        self.empty_title = QLabel("把视频或音频拖到这里")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_title)
        self.empty_hint = QLabel("支持 mp4 / mov / mkv / mp3 / m4a / wav 等，文件夹会递归读取")
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        pick_files = QPushButton("选择文件…")
        pick_files.clicked.connect(self.add_files_action.trigger)
        pick_folder = QPushButton("选择文件夹…")
        pick_folder.clicked.connect(self.add_folder_action.trigger)
        buttons.addWidget(pick_files)
        buttons.addWidget(pick_folder)
        buttons.addStretch(1)
        layout.addSpacing(4)
        layout.addLayout(buttons)
        layout.addStretch(2)
        return page

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.add_files_action)
        file_menu.addAction(self.add_folder_action)
        file_menu.addSeparator()
        file_menu.addAction(self.open_output_action)
        file_menu.addAction(self.clear_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_action)

        edit_menu = self.menuBar().addMenu("编辑")
        edit_menu.addAction(self.remove_action)
        select_all = QAction("全选", self.table)
        select_all.setShortcut(QKeySequence.SelectAll)
        select_all.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        select_all.triggered.connect(self.table.selectAll)
        self.table.addAction(select_all)
        edit_menu.addAction(select_all)

        task_menu = self.menuBar().addMenu("任务")
        task_menu.addAction(self.start_action)
        task_menu.addAction(self.stop_action)
        task_menu.addSeparator()
        task_menu.addAction(self.force_action)

        view_menu = self.menuBar().addMenu("显示")
        view_menu.addAction(self.log_action)
        view_menu.addAction(self.open_log_action)

        settings_menu = self.menuBar().addMenu("设置")
        settings_menu.addAction(self.prefs_action)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self.about_action)

    def _connect(self) -> None:
        self.sidebar.filterChanged.connect(self._set_filter)
        self.sidebar.locationClicked.connect(self._pick_output_dir)
        self.sidebar.openFolderClicked.connect(self._open_output_dir)
        self.sidebar.formatClicked.connect(lambda: self._open_prefs(TAB_FORMAT))
        self.content.pathsDropped.connect(self._add_paths)
        self.table.openOutputRequested.connect(self._open_output)
        self.table.outputFolderRequested.connect(self._open_output_dir)
        self.table.revealRequested.connect(lambda path: reveal_path(Path(path)))
        self.table.retryRequested.connect(self._retry_task)
        self.table.copyPathRequested.connect(self._copy_path)
        self.table.removeRequested.connect(self._remove_ids)
        self.table.clearRequested.connect(self._clear_files)
        self.table.selectionChanged.connect(self._update_actions)
        self.status.openOutputClicked.connect(self._open_output_dir)
        self.status.viewModelsClicked.connect(self._show_model_sheet)
        self.status.continueClicked.connect(self._continue_unfinished)
        self.status.logClicked.connect(lambda: self._set_log_visible(not self.log_drawer.isVisible()))
        self.log_drawer.openLogFileRequested.connect(self._open_log_file)

    # ------------------------------------------------------------- theme

    def _install_theme(self) -> None:
        self._theme_timer = QTimer(self)
        self._theme_timer.setSingleShot(True)
        self._theme_timer.setInterval(60)
        self._theme_timer.timeout.connect(self._apply_theme)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._scheme_changed)
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._palette_changed)
        self._apply_theme()

    def _scheme_changed(self, _scheme) -> None:
        self._theme_timer.start()

    def _palette_changed(self, _palette) -> None:
        if not self._applying_theme:
            self._theme_timer.start()

    def _dark_mode(self) -> bool:
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
        app = QApplication.instance()
        if app is not None:
            return app.palette().color(QPalette.Window).lightness() < 128
        return False

    def _apply_theme(self) -> None:
        dark = self._dark_mode()
        tokens.set_dark(dark)
        app = QApplication.instance()
        if app is not None:
            self._applying_theme = True
            app.setPalette(styles.build_palette(dark))
            app.setStyleSheet(styles.build(dark))
            self._applying_theme = False
        self._icon_key = None
        self._tint_icons()
        self.sidebar.refresh_theme()
        self.table.refresh_theme()
        self.status.refresh_theme()
        self.log_drawer.refresh_theme()

    def _tint_icons(self) -> None:
        accent = styles.accent_hex()
        key = (
            tokens.is_dark(), self._running, accent,
            self.start_button.isEnabled(),
        )
        if key == self._icon_key:
            return
        self._icon_key = key
        colors = tokens.active()
        self.add_button.setIcon(icon("plus", colors["text.primary"], 16))
        self.remove_button.setIcon(icon("minus", colors["text.primary"], 16))
        self.output_button.setIcon(icon("folder", colors["text.primary"], 16))
        self.prefs_button.setIcon(icon("gear", colors["text.secondary"], 16))
        accent_fg = styles.accent_text(accent)
        if not self._running and not self.start_button.isEnabled():
            accent_fg = colors["text.tertiary"]
        self.start_button.setIcon(
            icon("stop" if self._running else "play", accent_fg, 16)
        )
        pixmap = drop_pixmap(colors["text.secondary"], 32)
        if pixmap is not None:
            self.empty_icon.setPixmap(pixmap)

    # ------------------------------------------------------------ settings

    def _settings_valid(self) -> bool:
        return bool(self.settings.get("formats")) or self.settings.get("audio_format") != "none"

    def _apply_settings_ui(self) -> None:
        formats = list(self.settings.get("formats") or [])
        audio = str(self.settings.get("audio_format") or "m4a")
        self.sidebar.set_output(
            str(self.settings.get("output_dir") or ""),
            output_summary(formats, audio),
        )
        self.output_button.setToolTip(
            f"打开输出文件夹\n{self.settings.get('output_dir') or ''}"
        )
        self.force_action.blockSignals(True)
        self.force_action.setChecked(bool(self.settings.get("force")))
        self.force_action.blockSignals(False)
        if self.settings.get("output_dir"):
            self._last_dir = str(self.settings["output_dir"])
        if self._prefs is not None and not self._prefs.isVisible():
            self._prefs.load(self.settings)

    def _force_toggled(self, checked: bool) -> None:
        self.settings = config.save_settings({**self.settings, "force": bool(checked)})

    def _set_filter(self, key: str) -> None:
        self._refresh(force=True)

    def _open_prefs(self, tab: int = 0) -> None:
        if self._prefs is None:
            self._prefs = PreferencesDialog(self, self.settings)
            self._prefs.changed.connect(self._settings_changed)
        else:
            self._prefs.load(self.settings)
        self._prefs.open_tab(tab)
        self._prefs.show()
        self._prefs.raise_()
        self._prefs.activateWindow()

    def _settings_changed(self) -> None:
        self.settings = config.load_settings()
        self._apply_settings_ui()
        self._refresh(force=True)

    def _pick_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择保存文件夹", str(self.settings.get("output_dir") or self._last_dir)
        )
        if not folder:
            return
        self.settings = config.save_settings({**self.settings, "output_dir": folder})
        self._last_dir = folder
        self._apply_settings_ui()
        if self._running:
            self._flash("输出位置已更新，将在下一批生效", 4000)
        else:
            self._flash("输出位置已更新", 3000)

    # --------------------------------------------------------------- files

    def _pick_files(self) -> None:
        if self._running:
            self._flash("正在转写，停止后可添加", 3000)
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频或音频文件", self._last_dir, MEDIA_FILTER
        )
        if files:
            self._last_dir = str(Path(files[0]).parent)
            self._add_paths(files)

    def _pick_folder(self) -> None:
        if self._running:
            self._flash("正在转写，停止后可添加", 3000)
            return
        folder = QFileDialog.getExistingDirectory(self, "选择视频所在文件夹", self._last_dir)
        if folder:
            self._last_dir = folder
            self._add_paths([folder])

    def _add_paths(self, paths: list[str]) -> None:
        if self._running:
            self._flash("正在转写，停止后可添加", 3000)
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
        self._flash(message, 4000)
        self._refresh(force=True)

    def _remove_selected(self) -> None:
        self._remove_ids(self.table.selected_ids())

    def _remove_ids(self, ids: list[str]) -> None:
        if self._running or not ids:
            return
        for task_id in ids:
            try:
                self.manager.remove(task_id)
            except RuntimeError:
                return
        self._refresh(force=True)

    def _clear_files(self) -> None:
        if self._running:
            return
        self.manager.clear()
        self._refresh(force=True)

    # --------------------------------------------------------------- job

    def _start_or_stop(self) -> None:
        if self._running:
            self._cancel_job()
        else:
            self._start_job()

    def _start_job(self, only_ids: list[str] | None = None,
                   force: bool | None = None) -> None:
        if self._running:
            return
        if not self._settings_valid():
            self._flash("请至少选择 Markdown、Word 或音频中的一种输出", 5000)
            return
        snapshot = self.manager.snapshot()
        if not snapshot["tasks"]:
            self._flash("请先选择视频或音频文件", 5000)
            return
        if force is None:
            force = self.force_action.isChecked()
        try:
            self.manager.start(
                Path(self.settings["output_dir"]).expanduser(),
                list(self.settings.get("formats") or []),
                str(self.settings.get("audio_format") or "m4a"),
                int(self.settings.get("workers") or 1),
                bool(force),
                only_ids=only_ids,
            )
        except (RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "无法开始转写", str(exc))
            return
        self._job_finished = False
        self._model_sheet_dismissed = False
        if self._model_sheet is not None:
            self._model_sheet.reset()
            self._model_sheet.hide()
        self._refresh(force=True)

    def _cancel_job(self) -> None:
        self.manager.cancel()
        self._refresh(force=True)

    def _continue_unfinished(self) -> None:
        unfinished = [
            task["id"] for task in self._tasks
            if task["status"] in {"queued", "canceled", "failed"}
        ]
        if unfinished:
            self._start_job(only_ids=unfinished)

    def _retry_task(self, task_id: str) -> None:
        if not self._running:
            self._start_job(only_ids=[task_id], force=True)

    # -------------------------------------------------------------- output

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
        open_path(path)

    def _copy_path(self, path: str) -> None:
        QApplication.clipboard().setText(str(path))
        self._flash("路径已复制", 2000)

    def _open_log_file(self) -> None:
        path = core.log_path()
        if path.exists():
            open_path(path)
            return
        QMessageBox.information(self, "运行日志", f"日志文件还不存在：\n{path}")

    # ---------------------------------------------------------------- log

    def _set_log_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self.log_action.isChecked() != visible:
            self.log_action.blockSignals(True)
            self.log_action.setChecked(visible)
            self.log_action.blockSignals(False)
        if visible == self.log_drawer.isVisible():
            self._update_status()
            return
        if visible:
            self.log_drawer.show()
            total = max(320, self.log_splitter.height())
            self.log_splitter.setSizes([max(200, total - self._log_height), self._log_height])
        else:
            if self.log_drawer.height() > 60:
                self._log_height = self.log_drawer.height()
            self.log_drawer.hide()
        self._update_status()

    # ------------------------------------------------------------- models

    def _sync_model_sheet(self, job: dict) -> None:
        state = str(job.get("model_state") or "")
        needed = (
            bool(job.get("running"))
            and bool(job.get("needs_model"))
            and state in {"pending", "checking", "downloading"}
        )
        if not needed:
            if self._model_sheet is not None and self._model_sheet.isVisible():
                self._model_sheet.hide()
            return
        if self._model_sheet_dismissed:
            return
        if self._model_sheet is None:
            self._model_sheet = ModelSheet(self)
            self._model_sheet.cancelRequested.connect(self._cancel_job)
            self._model_sheet.finished.connect(self._model_sheet_closed)
        self._model_sheet.update_state(job)
        if not self._model_sheet.isVisible():
            self._model_sheet.show()
            self._model_sheet.raise_()

    def _model_sheet_closed(self, _result: int) -> None:
        self._model_sheet_dismissed = True
        self._update_status()

    def _show_model_sheet(self) -> None:
        if self._model_sheet is None:
            self._model_sheet = ModelSheet(self)
            self._model_sheet.cancelRequested.connect(self._cancel_job)
            self._model_sheet.finished.connect(self._model_sheet_closed)
        self._model_sheet_dismissed = False
        self._model_sheet.update_state(self._job)
        self._model_sheet.show()
        self._model_sheet.raise_()

    # ------------------------------------------------------------- refresh

    def _refresh(self, force: bool = False) -> None:
        snapshot = self.manager.snapshot()
        job = snapshot["job"]
        tasks = snapshot["tasks"]
        was_running = self._running
        self._job = job
        self._tasks = tasks
        self._running = bool(job["running"])
        counts = {"done": 0, "failed": 0, "skipped": 0, "canceled": 0, "queued": 0}
        for task in tasks:
            status = task["status"]
            if status in counts:
                counts[status] += 1
        counts["queued"] += sum(1 for task in tasks if task["status"] == "running")
        counts["all"] = len(tasks)
        self._counts = counts
        self.sidebar.set_counts(counts)

        filtered = self._filtered(tasks)
        self.table.sync(filtered, [task["id"] for task in tasks], self._running)
        self._update_empty(tasks, filtered)
        self.log_drawer.set_entries(snapshot["logs"])
        self._sync_model_sheet(job)
        self._update_status()
        self._update_actions()

        if job["finished_at"]:
            self._job_finished = True
        if was_running and not self._running and job.get("state") == "done":
            made = counts.get("done", 0) + counts.get("skipped", 0)
            if made:
                self._flash(
                    f"已生成 {made} 个输出 · {display_path(str(self._output_dir()))}",
                    6000,
                )

    def _filtered(self, tasks: list[dict]) -> list[dict]:
        key = self.sidebar.current_filter()
        if key == "all":
            return tasks
        if key == "queued":
            return [task for task in tasks if task["status"] in {"queued", "running"}]
        return [task for task in tasks if task["status"] == key]

    def _update_empty(self, tasks: list[dict], filtered: list[dict]) -> None:
        if tasks and filtered:
            self.content.stack.setCurrentWidget(self.table)
            return
        self.content.stack.setCurrentWidget(self.empty_page)
        if not tasks:
            self.empty_title.setText("把视频或音频拖到这里")
            self.empty_hint.setText("支持 mp4 / mov / mkv / mp3 / m4a / wav 等，文件夹会递归读取")
        else:
            self.empty_title.setText("这个筛选下没有文件")
            self.empty_hint.setText("切换到其他筛选，或继续添加素材。")

    def _update_status(self) -> None:
        job = self._job
        tasks = self._tasks
        if not job:
            return
        running = bool(job.get("running"))
        counts = self._counts
        total = len(tasks)
        model_state = str(job.get("model_state") or "")
        percent = None
        speed_text = ""
        summary = ""
        tooltip = ""

        if running:
            if model_state in {"pending", "checking", "downloading"}:
                percent = None
                size = int(job.get("model_bytes") or 0)
                total_bytes = int(job.get("model_total_bytes") or 0)
                summary = (
                    f"正在准备语音模型 · {fmt_decimal_size(size)} / "
                    f"约 {fmt_decimal_size(total_bytes)}"
                )
                speed_text = "首次下载后即可离线使用"
            elif job.get("canceling"):
                summary = "正在停止…"
            else:
                percent = self._progress_percent(tasks)
                active = [task for task in tasks if task["status"] == "running"]
                if active:
                    current = active[0]
                    position = next(
                        (index + 1 for index, task in enumerate(tasks)
                         if task["id"] == current["id"]), 0
                    )
                    stage = current.get("stage_label") or "准备中"
                    summary = (
                        f"正在转写 {position}/{total} · {current['name']} · "
                        f"{stage} {fmt_clock(current.get('elapsed') or 0)}"
                    )
                    if len(active) > 1:
                        summary += f" 等 {len(active)} 个"
                else:
                    summary = "正在准备…"
                speed, eta = self._speed_eta(tasks, job)
                if speed:
                    speed_text = f"{speed:.1f}× 实时 · 预计还剩 {fmt_clock(eta)}"
                else:
                    speed_text = "预计中"
        elif job.get("state") == "canceled":
            finished = counts.get("done", 0) + counts.get("skipped", 0)
            pending = counts.get("queued", 0) + counts.get("canceled", 0)
            summary = f"已取消 · 完成 {finished}，未开始 {pending}"
        elif job.get("state") == "done":
            parts = [f"完成 {counts.get('done', 0)}"]
            if counts.get("skipped"):
                parts.append(f"跳过 {counts['skipped']}")
            if counts.get("failed"):
                parts.append(f"失败 {counts['failed']}")
            if counts.get("canceled"):
                parts.append(f"取消 {counts['canceled']}")
            summary = " · ".join(parts) + f" · 共 {fmt_clock(job.get('elapsed') or 0)}"
            percent = self._progress_percent(tasks)
        elif total:
            duration = sum(float(task.get("duration") or 0) for task in tasks)
            size = sum(float(task.get("size") or 0) for task in tasks)
            summary = f"{total} 个文件 · {fmt_clock(duration)} · {fmt_size(size)}"
            speed_text = "输出：" + output_summary(
                list(self.settings.get("formats") or []),
                str(self.settings.get("audio_format") or "m4a"),
            )
        else:
            summary = "拖入文件开始"

        tooltip = "\n".join(part for part in (
            summary,
            f"输出目录：{display_path(str(self.settings.get('output_dir') or ''))}",
        ) if part)

        flash = self._flash_active()
        if flash:
            summary = flash
            tooltip = flash

        self.status.update_state(
            summary=summary,
            tooltip=tooltip,
            percent=percent,
            rate=speed_text,
            show_output=bool(tasks) and not running,
            show_download=(
                running
                and model_state in {"checking", "downloading"}
                and not (self._model_sheet is not None and self._model_sheet.isVisible())
            ),
            show_continue=(
                job.get("state") == "canceled"
                and any(task["status"] in {"queued", "canceled", "failed"} for task in tasks)
            ),
            log_visible=self.log_drawer.isVisible(),
        )

    def _progress_percent(self, tasks: list[dict]) -> int:
        if not tasks:
            return 0
        durations = [float(task.get("duration") or 0) for task in tasks]
        known = [value for value in durations if value > 0]
        fallback = sum(known) / len(known) if known else 1.0
        total = 0.0
        done = 0.0
        for task, duration in zip(tasks, durations):
            weight = duration if duration > 0 else fallback
            total += weight
            if task["status"] in {"done", "skipped"}:
                done += weight
        return round(done / total * 100) if total else 0

    def _speed_eta(self, tasks: list[dict], job: dict) -> tuple[float, float]:
        wall = float(job.get("elapsed") or 0)
        done_duration = sum(
            float(task.get("duration") or 0)
            for task in tasks if task["status"] == "done"
        )
        speed = done_duration / wall if wall > 0 and done_duration > 0 else 0.0
        if speed <= 0:
            return 0.0, 0.0
        remaining = 0.0
        for task in tasks:
            duration = float(task.get("duration") or 0)
            if task["status"] == "queued":
                remaining += duration
            elif task["status"] == "running":
                remaining += max(0.0, duration - float(task.get("elapsed") or 0))
        return speed, remaining / speed

    def _update_actions(self) -> None:
        running = self._running
        has_tasks = bool(self._tasks)
        selected = bool(self.table.selected_ids())
        self.add_button.setEnabled(not running)
        self.add_files_action.setEnabled(not running)
        self.add_folder_action.setEnabled(not running)
        self.remove_button.setEnabled(not running and selected)
        self.remove_action.setEnabled(not running and selected)
        self.clear_action.setEnabled(has_tasks and not running)
        self.force_action.setEnabled(not running)
        self.start_action.setEnabled(has_tasks and not running and self._settings_valid())
        self.stop_action.setEnabled(running)
        self.start_button.setEnabled(
            running or (has_tasks and self._settings_valid())
        )
        self.start_button.setText("停止" if running else "开始转写")
        if running:
            self.start_button.setToolTip(
                "立即停止：终止转写进程，当前文件不会留下产物；"
                "已完成的输出保留，未开始的不再开始。"
            )
        else:
            self.start_button.setToolTip("开始转写（⌘⏎）" if sys.platform == "darwin"
                                         else "开始转写（Ctrl+Enter）")
        self._tint_icons()
        self.status.output_button.setEnabled(has_tasks)

    # --------------------------------------------------------------- flash

    def _flash(self, message: str, ms: int = 3000) -> None:
        self._flash_token += 1
        token = self._flash_token
        self._flash_message = message
        self._flash_until = time.monotonic() + ms / 1000
        QTimer.singleShot(ms, lambda: self._expire_flash(token))
        self._update_status()

    def _flash_active(self) -> str:
        if self._flash_message and time.monotonic() < self._flash_until:
            return self._flash_message
        return ""

    def _expire_flash(self, token: int) -> None:
        if token != self._flash_token:
            return
        self._flash_message = ""
        self._update_status()

    # ------------------------------------------------------------ window state

    def _restore_state(self) -> None:
        geometry = self._store.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        try:
            height = int(self._store.value("window/logHeight", 180))
        except (TypeError, ValueError):
            height = 180
        self._log_height = max(120, min(320, height))
        visible = self._store.value("window/logVisible")
        if str(visible).lower() in {"true", "1"}:
            self._set_log_visible(True)

    def _save_state(self) -> None:
        if self.log_drawer.isVisible() and self.log_drawer.height() > 60:
            self._log_height = self.log_drawer.height()
        self._store.setValue("window/geometry", self.saveGeometry())
        self._store.setValue("window/logVisible", self.log_drawer.isVisible())
        self._store.setValue("window/logHeight", self._log_height)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.manager.snapshot()["job"]["running"]:
            answer = QMessageBox.question(
                self,
                "退出",
                "正在转写，退出会立即中断任务，当前文件不会留下产物。确定退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self._save_state()
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

    icon_path = Path(ASSETS) / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(output_dir=output_dir)
    window.show()
    return app.exec()
