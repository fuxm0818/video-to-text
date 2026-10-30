"""One-line status strip and the collapsible run-log drawer."""
from __future__ import annotations

import sys
import time
from html import escape

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import tokens
from .common import ElidedLabel, repolish


class SmoothProgressBar(QProgressBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedSize(120, 4)
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Linear)

    def animate_to(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self._anim.stop()
        if not self.isVisible() or self.value() == value:
            super().setValue(value)
            return
        self._anim.setStartValue(self.value())
        self._anim.setEndValue(value)
        self._anim.start()


class StatusStrip(QWidget):
    openOutputClicked = Signal()
    viewModelsClicked = Signal()
    continueClicked = Signal()
    logClicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("statusBar")
        self.setFixedHeight(26)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(8)

        self.summary = ElidedLabel("拖入文件开始")
        self.summary.setObjectName("statusText")
        layout.addWidget(self.summary, 1)

        self.progress = SmoothProgressBar()
        layout.addWidget(self.progress, 0, Qt.AlignVCenter)
        self.percent = QLabel("0%")
        self.percent.setObjectName("percent")
        self.percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent.setFixedWidth(34)
        layout.addWidget(self.percent, 0, Qt.AlignVCenter)

        self.rate = QLabel("")
        self.rate.setObjectName("rate")
        self.rate.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.rate, 0, Qt.AlignVCenter)

        self.download_button = self._link("查看下载进度")
        self.download_button.clicked.connect(self.viewModelsClicked)
        self.continue_button = self._link("继续未完成的")
        self.continue_button.clicked.connect(self.continueClicked)
        self.output_button = self._link(
            "在访达中显示" if sys.platform == "darwin" else "打开输出文件夹"
        )
        self.output_button.clicked.connect(self.openOutputClicked)
        self.log_button = self._link("查看日志")
        self.log_button.clicked.connect(self.logClicked)

        for button in (
            self.download_button,
            self.continue_button,
            self.output_button,
            self.log_button,
        ):
            layout.addWidget(button, 0, Qt.AlignVCenter)
        self.progress.hide()
        self.percent.hide()
        self.download_button.hide()
        self.continue_button.hide()
        self.output_button.hide()

    def _link(self, text: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("link")
        button.setText(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.TabFocus)
        return button

    def update_state(
        self,
        *,
        summary: str,
        tooltip: str,
        percent: int | None,
        rate: str,
        show_output: bool,
        show_download: bool,
        show_continue: bool,
        log_visible: bool,
    ) -> None:
        self.summary.set_value(summary)
        self.summary.setToolTip(tooltip or summary)
        self.rate.setText(rate)
        if percent is None:
            self.progress.hide()
            self.percent.hide()
        else:
            self.progress.show()
            self.percent.show()
            self.progress.animate_to(percent)
            self.percent.setText(f"{percent}%")
        self.output_button.setVisible(show_output)
        self.download_button.setVisible(show_download)
        self.continue_button.setVisible(show_continue)
        self.log_button.setText("隐藏日志" if log_visible else "查看日志")
        self.setAccessibleDescription(" ".join(part for part in (summary, rate) if part))

    def refresh_theme(self) -> None:
        for button in (
            self.download_button,
            self.continue_button,
            self.output_button,
            self.log_button,
        ):
            repolish(button)
        repolish(self.summary)
        repolish(self.rate)
        repolish(self.percent)


class LogDrawer(QWidget):
    openLogFileRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("logPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("logHeader")
        header.setFixedHeight(26)
        head_layout = QHBoxLayout(header)
        head_layout.setContentsMargins(10, 0, 8, 0)
        head_layout.setSpacing(8)
        title = QLabel("运行日志")
        title.setObjectName("statusText")
        head_layout.addWidget(title)
        head_layout.addStretch(1)
        self.latest = QToolButton()
        self.latest.setObjectName("link")
        self.latest.setText("回到最新")
        self.latest.setCursor(Qt.PointingHandCursor)
        self.latest.hide()
        self.latest.clicked.connect(self._scroll_to_end)
        head_layout.addWidget(self.latest)
        self.open_file = QToolButton()
        self.open_file.setObjectName("link")
        self.open_file.setText("打开日志文件")
        self.open_file.setCursor(Qt.PointingHandCursor)
        self.open_file.clicked.connect(self.openLogFileRequested)
        head_layout.addWidget(self.open_file)
        layout.addWidget(header)

        self.view = QTextEdit()
        self.view.setObjectName("logView")
        self.view.setReadOnly(True)
        self.view.setAcceptDrops(False)
        self.view.setFrameShape(QTextEdit.NoFrame)
        self.view.document().setDocumentMargin(6)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPixelSize(11)
        self.view.setFont(font)
        layout.addWidget(self.view, 1)

        self._logs: list[dict] = []
        self._sig: tuple = ()
        self.view.verticalScrollBar().valueChanged.connect(self._update_latest)

    def set_entries(self, logs: list[dict]) -> None:
        sig = tuple(
            (entry.get("t"), entry.get("level"), entry.get("message"), entry.get("task"))
            for entry in logs
        )
        if sig == self._sig:
            return
        self._logs = list(logs)
        self._sig = sig
        self._render()

    def _render(self) -> None:
        colors = tokens.active()
        parts = []
        for entry in self._logs:
            stamp = time.strftime("%H:%M:%S", time.localtime(entry.get("t") or 0))
            level = entry.get("level")
            color = colors["state.error"] if level == "error" else (
                colors["state.warn"] if level == "warn" else colors["text.secondary"]
            )
            who = ""
            if entry.get("task"):
                who = (
                    f'<span style="color:{colors["text.tertiary"]}">'
                    f'[{escape(str(entry["task"]))}]</span> '
                )
            message = escape(str(entry.get("message", ""))).replace("\n", "<br>")
            parts.append(
                f'<div style="color:{color};">{stamp}  {who}{message}</div>'
            )
        bar = self.view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        previous = bar.value()
        self.view.setHtml("".join(parts))
        if at_end:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(previous, bar.maximum()))
        QTimer.singleShot(0, self._update_latest)

    def _update_latest(self) -> None:
        bar = self.view.verticalScrollBar()
        self.latest.setVisible(bar.maximum() > 0 and bar.value() < bar.maximum() - 4)

    def _scroll_to_end(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def refresh_theme(self) -> None:
        repolish(self)
        repolish(self.latest)
        repolish(self.open_file)
        self._render()
