"""Non-modal progress sheet for the one-time speech-model download."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..jobs import model_cache_dir
from .common import display_path, fmt_clock, fmt_decimal_size


class ModelSheet(QDialog):
    cancelRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("下载语音模型")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumWidth(430)
        self._sample_at = 0.0
        self._sample_bytes = 0
        self._speed = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("首次使用需要下载语音模型")
        title.setObjectName("sheetTitle")
        layout.addWidget(title)

        detail = QLabel("Paraformer 识别 953 MB · CT-Punc 标点 1.1 GB · VAD 4 MB")
        detail.setObjectName("sheetText")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.bytes_label = QLabel("正在检查语音模型…")
        self.bytes_label.setObjectName("sheetText")
        self.eta_label = QLabel("")
        self.eta_label.setObjectName("sheetText")
        self.eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.bytes_label, 1)
        row.addWidget(self.eta_label)
        layout.addLayout(row)

        path = QLabel(f"下载位置：{display_path(str(model_cache_dir()))}")
        path.setObjectName("sheetPath")
        layout.addWidget(path)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def reset(self) -> None:
        self._sample_at = 0.0
        self._sample_bytes = 0
        self._speed = 0.0
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.bytes_label.setText("正在检查语音模型…")
        self.eta_label.setText("")
        self.cancel_button.setEnabled(True)

    def update_state(self, job: dict) -> None:
        state = str(job.get("model_state") or "")
        size = int(job.get("model_bytes") or 0)
        total = int(job.get("model_total_bytes") or 0)
        downloading = state == "downloading" and size > 0 and total > 0

        if downloading:
            now = time.monotonic()
            if self._sample_at and size > self._sample_bytes:
                elapsed = now - self._sample_at
                if elapsed >= 1.0:
                    self._speed = (size - self._sample_bytes) / elapsed
                    self._sample_at = now
                    self._sample_bytes = size
            elif not self._sample_at:
                self._sample_at = now
                self._sample_bytes = size
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, int(size / total * 1000)))
            self.bytes_label.setText(
                f"{fmt_decimal_size(size)} / 约 {fmt_decimal_size(total)}"
            )
            if self._speed > 0:
                remaining = max(0, total - size) / self._speed
                self.eta_label.setText(f"预计还剩 {fmt_clock(remaining)}")
            else:
                self.eta_label.setText("预计中")
        elif state in {"pending", "checking"}:
            self.progress.setRange(0, 0)
            self.bytes_label.setText("正在检查语音模型…")
            self.eta_label.setText("")

        self.cancel_button.setEnabled(not job.get("canceling"))

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancelRequested.emit()
