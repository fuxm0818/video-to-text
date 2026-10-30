"""About window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from .. import __version__
from .common import APP_TITLE, display_path
from .. import core


def show_about(parent) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"关于{APP_TITLE}")
    dialog.setMinimumWidth(400)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 18, 20, 14)
    layout.setSpacing(8)

    title = QLabel(APP_TITLE)
    title.setObjectName("sheetTitle")
    layout.addWidget(title)

    version = QLabel(f"{__version__} · MIT License")
    version.setObjectName("sheetText")
    layout.addWidget(version)

    text = QLabel(
        "把本地视频或音频里的说话声转成 Markdown / Word 文稿，并同时导出音频文件。"
        "全部在本机完成，不上传、不联网。"
    )
    text.setObjectName("sheetText")
    text.setWordWrap(True)
    layout.addWidget(text)

    components = QLabel(
        "语音识别 FunASR（Paraformer / FSMN-VAD / CT-Punc）\n"
        "界面 Qt for Python（LGPL-3.0）\n"
        "音视频处理 FFmpeg"
    )
    components.setObjectName("sheetText")
    components.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(components)

    log_path = QLabel(f"运行日志：{display_path(str(core.log_path()))}")
    log_path.setObjectName("sheetPath")
    log_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(log_path)

    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
