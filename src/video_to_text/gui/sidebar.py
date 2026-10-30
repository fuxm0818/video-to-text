"""Queue filters and output summary shown left of the task table."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .. import tokens
from .common import ElidedLabel, display_path, repolish

COUNT_ROLE = Qt.UserRole + 1
KEY_ROLE = Qt.UserRole

FILTERS = (
    ("all", "全部"),
    ("queued", "待转写"),
    ("done", "已完成"),
    ("failed", "失败"),
    ("skipped", "已跳过"),
    ("canceled", "已取消"),
)

FILTER_ROW = 26


class _FilterDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        colors = tokens.active()
        rect = QRectF(option.rect.adjusted(0, 1, 0, -1))
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected or hover:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors["bg.selected"] if selected else colors["bg.hover"]))
            painter.drawRoundedRect(rect, 6, 6)
            painter.restore()

        font = QFont(option.font)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor(colors["text.primary"] if selected else colors["text.secondary"]))
        painter.drawText(
            option.rect.adjusted(8, 0, -36, 0),
            Qt.AlignLeft | Qt.AlignVCenter,
            str(index.data(Qt.DisplayRole) or ""),
        )
        painter.setPen(QColor(colors["text.secondary"] if selected else colors["text.tertiary"]))
        painter.drawText(
            option.rect.adjusted(0, 0, -10, 0),
            Qt.AlignRight | Qt.AlignVCenter,
            str(index.data(COUNT_ROLE) or 0),
        )

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(0, FILTER_ROW)


class FilterList(QListWidget):
    filterChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("filterList")
        self.setItemDelegate(_FilterDelegate(self))
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(len(FILTERS) * FILTER_ROW + 4)
        for key, label in FILTERS:
            item = QListWidgetItem(label)
            item.setData(KEY_ROLE, key)
            item.setData(COUNT_ROLE, 0)
            item.setSizeHint(QSize(0, FILTER_ROW))
            self.addItem(item)
        self.setCurrentRow(0)
        self.currentRowChanged.connect(self._row_changed)

    def _row_changed(self, row: int) -> None:
        item = self.item(row)
        if item is not None:
            self.filterChanged.emit(str(item.data(KEY_ROLE)))

    def current_filter(self) -> str:
        item = self.currentItem()
        return str(item.data(KEY_ROLE)) if item is not None else "all"

    def set_filter(self, key: str) -> None:
        for row in range(self.count()):
            if self.item(row).data(KEY_ROLE) == key:
                if row != self.currentRow():
                    self.setCurrentRow(row)
                return

    def set_counts(self, counts: dict[str, int]) -> None:
        for row in range(self.count()):
            item = self.item(row)
            value = int(counts.get(str(item.data(KEY_ROLE)), 0))
            if int(item.data(COUNT_ROLE) or 0) != value:
                item.setData(COUNT_ROLE, value)
        self.viewport().update()


class OutputRow(QWidget):
    clicked = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("sideValueRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("hover", False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("sideTitle")
        label.setFixedWidth(24)
        self.value = ElidedLabel()
        self.value.setObjectName("sideValue")
        layout.addWidget(label)
        layout.addWidget(self.value, 1)

    def set_value(self, text: str, tooltip: str = "") -> None:
        self.value.set_value(text)
        self.setToolTip(tooltip or text)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.setProperty("hover", True)
        repolish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("hover", False)
        repolish(self)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Sidebar(QFrame):
    filterChanged = Signal(str)
    locationClicked = Signal()
    formatClicked = Signal()
    openFolderClicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(4)

        queue_label = QLabel("队列")
        queue_label.setObjectName("groupLabel")
        layout.addWidget(queue_label)

        self.filters = FilterList()
        self.filters.filterChanged.connect(self.filterChanged)
        layout.addWidget(self.filters)

        divider = QFrame()
        divider.setObjectName("sideDivider")
        divider.setFixedHeight(1)
        layout.addSpacing(8)
        layout.addWidget(divider)
        layout.addSpacing(8)

        output_label = QLabel("输出")
        output_label.setObjectName("groupLabel")
        layout.addWidget(output_label)

        self.location_row = OutputRow("位置")
        self.location_row.clicked.connect(self.locationClicked)
        layout.addWidget(self.location_row)

        self.open_row = OutputRow("打开")
        self.open_row.clicked.connect(self.openFolderClicked)
        layout.addWidget(self.open_row)

        self.format_row = OutputRow("格式")
        self.format_row.clicked.connect(self.formatClicked)
        layout.addWidget(self.format_row)

        layout.addStretch(1)

    def set_counts(self, counts: dict[str, int]) -> None:
        self.filters.set_counts(counts)

    def current_filter(self) -> str:
        return self.filters.current_filter()

    def set_filter(self, key: str) -> None:
        self.filters.set_filter(key)

    def set_output(self, location: str, formats: str) -> None:
        self.location_row.set_value(
            display_path(location), f"{location}\n点击更改保存位置"
        )
        self.open_row.set_value("输出文件夹", "在文件管理器中打开输出文件夹")
        self.format_row.set_value(formats or "未选择", formats)

    def refresh_theme(self) -> None:
        self.filters.viewport().update()
        repolish(self.location_row)
        repolish(self.open_row)
        repolish(self.format_row)
