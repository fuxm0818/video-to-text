"""The task table: six columns, painted status glyphs, inline error details."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from .. import tokens
from .common import (
    CHIP_LABELS,
    OUTPUT_KINDS,
    ROLE_DETAIL,
    ROLE_FAILED,
    ROLE_ID,
    ROLE_STATUS,
    fmt_clock,
    fmt_size,
    friendly_error,
)
from .icons import paint_status, spin_phase

ROW_HEIGHT = 44
CHILD_HEIGHT = 104


def _status_glyph(status: str) -> str:
    return {
        "queued": "pending",
        "running": "running",
        "done": "done",
        "skipped": "skipped",
        "failed": "failed",
        "canceled": "canceled",
    }.get(status, "pending")


class TaskDelegate(QStyledItemDelegate):
    def __init__(self, tree: "TaskList") -> None:
        super().__init__(tree)
        self.tree = tree

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        if index.parent().isValid():
            super().paint(painter, option, index)
            return

        colors = tokens.active()
        item = self.tree.itemFromIndex(index)
        if item is None:
            return
        task_id = str(item.data(0, ROLE_ID) or "")
        status = str(item.data(0, ROLE_STATUS) or "queued")

        painter.save()
        painter.setClipRect(option.rect)
        row_rect = self.tree.visualItemRect(item).adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovering = self.tree.hover_id() == task_id
        if selected or hovering:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            if selected:
                key = "bg.selected" if self.tree.hasFocus() else "bg.selected_inactive"
            else:
                key = "bg.hover"
            painter.setBrush(QColor(colors[key]))
            painter.drawRoundedRect(QRectF(row_rect), 6, 6)

        column = index.column()
        if item.parent() is None and index.row() < self.tree.topLevelItemCount() - 1:
            painter.setPen(QColor(colors["line.hair"]))
            painter.drawLine(
                option.rect.left(), option.rect.bottom(),
                option.rect.right(), option.rect.bottom(),
            )

        if column == 0:
            paint_status(painter, QRectF(option.rect), _status_glyph(status),
                         colors, spin_phase())
        elif column == 1:
            self._paint_name(painter, option, item, status, colors)
        elif column in (2, 3, 4):
            self._paint_value(painter, option, item.text(column), colors)
        painter.restore()

    def _paint_name(self, painter, option, item, status, colors) -> None:
        rect = option.rect.adjusted(4, 5, -8, -5)
        name_font = QFont(option.font)
        name_font.setPixelSize(13)
        if status == "running":
            name_font.setWeight(QFont.Medium)
        painter.setFont(name_font)
        name_color = "text.secondary" if status in {"skipped", "canceled"} else "text.primary"
        painter.setPen(QColor(colors[name_color]))
        name = QFontMetrics(name_font).elidedText(item.text(1), Qt.ElideMiddle, rect.width())
        painter.drawText(rect.left(), rect.top(), rect.width(), 18,
                         int(Qt.AlignLeft | Qt.AlignVCenter), name)

        detail_font = QFont(option.font)
        detail_font.setPixelSize(11)
        painter.setFont(detail_font)
        detail_color = "state.error" if status == "failed" else "text.secondary"
        painter.setPen(QColor(colors[detail_color]))
        detail = QFontMetrics(detail_font).elidedText(
            str(item.data(1, ROLE_DETAIL) or ""), Qt.ElideRight, rect.width()
        )
        painter.drawText(rect.left(), rect.top() + 20, rect.width(), 15,
                         int(Qt.AlignLeft | Qt.AlignVCenter), detail)

    def _paint_value(self, painter, option, text: str, colors) -> None:
        font = QFont(option.font)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor(colors["text.secondary"]))
        painter.drawText(option.rect.adjusted(0, 0, -8, 0),
                         int(Qt.AlignRight | Qt.AlignVCenter), text)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        if index.parent().isValid():
            return QSize(0, CHILD_HEIGHT)
        return QSize(0, ROW_HEIGHT)


class ErrorDetail(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 4, 10, 8)
        layout.setSpacing(8)
        self.view = QPlainTextEdit()
        self.view.setObjectName("errorDetail")
        self.view.setReadOnly(True)
        self.view.setFrameShape(QPlainTextEdit.NoFrame)
        self.view.setFixedHeight(92)
        self.view.document().setDocumentMargin(0)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPixelSize(11)
        self.view.setFont(font)
        layout.addWidget(self.view, 1)
        self.copy = QPushButton("复制")
        self.copy.setObjectName("link")
        self.copy.setCursor(Qt.PointingHandCursor)
        self.copy.clicked.connect(self._copy)
        layout.addWidget(self.copy, 0, Qt.AlignTop)
        self._text = ""

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self.view.setPlainText(text)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)


class _Row:
    def __init__(self, tree: QTreeWidget, task_id: str) -> None:
        self.task_id = task_id
        self.item = QTreeWidgetItem()
        self.item.setData(0, ROLE_ID, task_id)
        self.item.setSizeHint(0, QSize(0, ROW_HEIGHT))
        tree.addTopLevelItem(self.item)
        self.outputs = QWidget()
        self.outputs.setAttribute(Qt.WA_TranslucentBackground, True)
        self.layout = QHBoxLayout(self.outputs)
        self.layout.setContentsMargins(0, 0, 6, 0)
        self.layout.setSpacing(4)
        self.layout.addStretch(1)
        tree.setItemWidget(self.item, 5, self.outputs)
        self.output_sig = ""
        self.error_item: QTreeWidgetItem | None = None
        self.error_widget: ErrorDetail | None = None
        self.error_sig = ""


class TaskList(QTreeWidget):
    openOutputRequested = Signal(str, str)
    outputFolderRequested = Signal()
    revealRequested = Signal(str)
    retryRequested = Signal(str)
    copyPathRequested = Signal(str)
    removeRequested = Signal(list)
    clearRequested = Signal()
    selectionChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("taskList")
        self.setColumnCount(6)
        self.setHeaderLabels(["", "名称", "时长", "大小", "用时", "产物"])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAllColumnsShowFocus(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setItemDelegate(TaskDelegate(self))

        header = self.header()
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        header.setFixedHeight(28)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
        self.setColumnWidth(0, 28)
        self.setColumnWidth(2, 72)
        self.setColumnWidth(3, 80)
        self.setColumnWidth(4, 76)
        self.setColumnWidth(5, 160)

        self._rows: dict[str, _Row] = {}
        self._tasks: dict[str, dict] = {}
        self._order_key = ""
        self._order: list[str] = []
        self._running = False
        self._has_running = False
        self._hover = ""

        self.itemClicked.connect(self._item_clicked)
        self.itemDoubleClicked.connect(self._item_double_clicked)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemSelectionChanged.connect(self.selectionChanged)
        self._spin = QTimer(self)
        self._spin.setInterval(80)
        self._spin.timeout.connect(self._tick)
        self._spin.start()

        self.itemExpanded.connect(lambda _item: self._position_errors())
        self.itemCollapsed.connect(lambda _item: self._position_errors())
        self.verticalScrollBar().valueChanged.connect(self._position_errors)

    # ------------------------------------------------------------- public

    def sync(self, tasks: list[dict], order: list[str], running: bool) -> None:
        ids = "|".join(task["id"] for task in tasks)
        if ids != self._order_key:
            self._rebuild(tasks)
            self._order_key = ids
        self._order = order
        self._running = running
        self._tasks = {task["id"]: task for task in tasks}
        self._has_running = any(task["status"] == "running" for task in tasks)
        positions = {task_id: index + 1 for index, task_id in enumerate(order)}
        for task in tasks:
            self._update_row(task, positions.get(task["id"], 0))
        self._position_errors()

    def selected_ids(self) -> list[str]:
        ids: list[str] = []
        for item in self.selectedItems():
            if item.parent() is not None:
                continue
            task_id = str(item.data(0, ROLE_ID) or "")
            if task_id and task_id not in ids:
                ids.append(task_id)
        return ids

    def hover_id(self) -> str:
        return self._hover

    def refresh_theme(self) -> None:
        self.viewport().update()

    # ------------------------------------------------------------ rows

    def _rebuild(self, tasks: list[dict]) -> None:
        selected = set(self.selected_ids())
        scroll = self.verticalScrollBar().value()
        for row in self._rows.values():
            if row.error_widget is not None:
                row.error_widget.deleteLater()
        self.clear()
        self._rows.clear()
        for task in tasks:
            self._rows[task["id"]] = _Row(self, task["id"])
        self.verticalScrollBar().setValue(scroll)
        if selected:
            for task in tasks:
                row = self._rows.get(task["id"])
                if row is not None and task["id"] in selected:
                    row.item.setSelected(True)

    def _update_row(self, task: dict, position: int) -> None:
        row = self._rows.get(task["id"])
        if row is None:
            return
        status = str(task["status"])
        item = row.item
        item.setData(0, ROLE_STATUS, status)
        item.setText(1, task["name"])
        item.setData(1, ROLE_DETAIL, self._detail(task, position))
        item.setData(1, ROLE_FAILED, status == "failed")
        item.setText(2, fmt_clock(task["duration"]) if task.get("duration") else "—")
        item.setText(3, fmt_size(task["size"]) if task.get("size") else "—")
        if status in {"running", "done"} and task.get("elapsed"):
            item.setText(4, fmt_clock(task["elapsed"]))
        else:
            item.setText(4, "—")
        for column in (2, 3, 4):
            item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)

        tips = [str(task.get("path") or ""), str(item.data(1, ROLE_DETAIL) or "")]
        if status in {"done", "skipped"} and task.get("outputs"):
            tips.append("双击打开文稿")
        warnings = task.get("warnings") or []
        if warnings:
            tips.append("提示：" + "；".join(warnings))
        if status == "failed" and task.get("error"):
            tips.append(str(task["error"]))
        if status == "failed" and task.get("error_detail"):
            tips.append("点击左侧状态图标展开完整错误")
        tooltip = "\n".join(part for part in tips if part)
        for column in range(6):
            item.setToolTip(column, tooltip)

        self._sync_outputs(row, task)
        self._sync_error(row, task)

    def _detail(self, task: dict, position: int) -> str:
        status = str(task["status"])
        if status == "queued":
            return f"排队中 · 第 {position} 个" if self._running and position else "待转写"
        if status == "running":
            stage = task.get("stage_label") or "准备中"
            elapsed = task.get("elapsed") or 0
            return f"{stage} · {fmt_clock(elapsed)}" if elapsed else stage
        if status == "done":
            cover = float(task.get("cover") or 0)
            duration = float(task.get("duration") or 0)
            detail = f"覆盖 {round(min(1.0, cover / duration) * 100)}%" if cover and duration else "完成"
            if task.get("reused"):
                detail += " · 复用已有文稿"
            return detail
        if status == "skipped":
            return "输出已存在"
        if status == "failed":
            title, hint = friendly_error(str(task.get("error") or ""))
            return f"{title} · {hint}" if hint else title
        if status == "canceled":
            return "已取消"
        return ""

    def _sync_outputs(self, row: _Row, task: dict) -> None:
        outputs = task.get("outputs") or {}
        key = "|".join(f"{kind}={outputs[kind]}" for kind in OUTPUT_KINDS if kind in outputs)
        if key == row.output_sig:
            return
        row.output_sig = key
        while row.layout.count() > 1:
            item = row.layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for kind in OUTPUT_KINDS:
            filename = outputs.get(kind)
            if not filename:
                continue
            label = CHIP_LABELS.get(kind) or Path(filename).suffix.lstrip(".").upper() or "音频"
            chip = QToolButton()
            chip.setObjectName("chip")
            chip.setText(label)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip(f"打开 {filename}")
            chip.clicked.connect(
                lambda _checked=False, tid=task["id"], k=kind: self.openOutputRequested.emit(tid, k)
            )
            row.layout.addWidget(chip, 0, Qt.AlignVCenter)

    def _sync_error(self, row: _Row, task: dict) -> None:
        text = ""
        if task["status"] == "failed":
            text = str(task.get("error_detail") or task.get("error") or "")
        if not text:
            if row.error_item is not None:
                if row.error_widget is not None:
                    row.error_widget.hide()
                    row.error_widget.deleteLater()
                row.item.removeChild(row.error_item)
                row.error_item = None
                row.error_widget = None
                row.error_sig = ""
            return
        if row.error_item is None:
            child = QTreeWidgetItem()
            child.setFirstColumnSpanned(True)
            row.item.addChild(child)
            widget = ErrorDetail(self.viewport())
            widget.hide()
            row.error_item = child
            row.error_widget = widget
            row.item.setExpanded(False)
        if row.error_widget is not None and text != row.error_sig:
            row.error_sig = text
            row.error_widget.set_text(text)

    def _position_errors(self) -> None:
        width = self.viewport().width()
        for row in self._rows.values():
            if row.error_item is None or row.error_widget is None:
                continue
            if not row.item.isExpanded():
                row.error_widget.hide()
                continue
            rect = self.visualItemRect(row.error_item)
            if rect.isNull() or rect.bottom() < 0 or rect.top() > self.viewport().height():
                row.error_widget.hide()
                continue
            row.error_widget.setGeometry(0, rect.top(), width, rect.height())
            row.error_widget.show()
            row.error_widget.raise_()

    # ---------------------------------------------------------- interaction

    def _item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is None and column == 0 and item.childCount():
            item.setExpanded(not item.isExpanded())
            self._position_errors()

    def _item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.parent() is not None:
            item = item.parent()
        task = self._tasks.get(str(item.data(0, ROLE_ID) or ""))
        if task is None or task["status"] not in {"done", "skipped"}:
            return
        outputs = task.get("outputs") or {}
        for kind in OUTPUT_KINDS:
            if kind in outputs:
                self.openOutputRequested.emit(task["id"], kind)
                return

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_errors()

    def _tick(self) -> None:
        if self._has_running:
            self.viewport().update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        while item is not None and item.parent() is not None:
            item = item.parent()
        hover = str(item.data(0, ROLE_ID) or "") if item is not None else ""
        if hover != self._hover:
            self._hover = hover
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover:
            self._hover = ""
            self.viewport().update()
        super().leaveEvent(event)

    def _context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is not None and item.parent() is not None:
            item = item.parent()
        if item is not None and not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
            self.setCurrentItem(item)
        task = self._tasks.get(str(item.data(0, ROLE_ID) or "")) if item is not None else None
        menu = QMenu(self)
        if task is not None:
            open_folder = menu.addAction("打开输出文件夹")
            open_folder.triggered.connect(lambda: self.outputFolderRequested.emit())
            reveal = menu.addAction(
                "在访达中显示源文件" if sys.platform == "darwin" else "打开源文件所在文件夹"
            )
            reveal.triggered.connect(lambda: self.revealRequested.emit(str(task["path"])))
            outputs = task.get("outputs") or {}
            if outputs:
                open_menu = menu.addMenu("打开文稿")
                for kind in OUTPUT_KINDS:
                    filename = outputs.get(kind)
                    if not filename:
                        continue
                    label = CHIP_LABELS.get(kind) or Path(filename).suffix.lstrip(".").upper()
                    action = open_menu.addAction(label)
                    action.triggered.connect(
                        lambda _checked=False, tid=task["id"], k=kind:
                        self.openOutputRequested.emit(tid, k)
                    )
            retry = menu.addAction("重新转写")
            retry.setEnabled(not self._running)
            retry.triggered.connect(lambda: self.retryRequested.emit(task["id"]))
            copy = menu.addAction("复制路径")
            copy.triggered.connect(lambda: self.copyPathRequested.emit(str(task["path"])))
            menu.addSeparator()
            remove = menu.addAction("从列表移除")
            remove.setEnabled(not self._running)
            remove.triggered.connect(lambda: self.removeRequested.emit(self.selected_ids()))
            menu.addSeparator()
        clear = menu.addAction("清空列表")
        clear.setEnabled(bool(self._tasks) and not self._running)
        clear.triggered.connect(self.clearRequested.emit)
        menu.exec(self.viewport().mapToGlobal(pos))
