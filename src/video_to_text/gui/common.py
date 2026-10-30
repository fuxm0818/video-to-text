"""Shared constants and small helpers for the GUI package."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

APP_TITLE = "视频转文字"
ASSETS = (Path(__file__).resolve().parents[1] / "assets").as_posix()
MEDIA_FILTER = (
    "视频和音频 (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.ts *.flv *.wmv "
    "*.m4a *.mp3 *.wav *.aac *.flac *.ogg *.opus *.wma);;所有文件 (*)"
)

ROLE_ID = Qt.UserRole
ROLE_STATUS = Qt.UserRole + 1
ROLE_DETAIL = Qt.UserRole + 2
ROLE_FAILED = Qt.UserRole + 3
ROLE_RUNNING = Qt.UserRole + 4
ROLE_COVER = Qt.UserRole + 5
ROLE_PATH = Qt.UserRole + 6

TEXT_FORMAT_LABELS = {"md": "Markdown", "docx": "Word"}
AUDIO_LABELS = {"m4a": "M4A", "wav": "WAV"}
CHIP_LABELS = {"md": "MD", "docx": "DOCX"}
OUTPUT_KINDS = ("md", "docx", "audio")

ERROR_HINTS = (
    ("没有音轨", "文件没有音轨", "可能是下载不完整，请重新下载后重试"),
    ("ffmpeg", "无法读取音频", "文件可能已损坏或格式不受支持"),
    ("No space left", "磁盘空间不足", "清理磁盘后重试"),
    ("磁盘", "磁盘空间不足", "清理磁盘后重试"),
    ("模型", "语音模型加载失败", "删除 ~/.cache/modelscope 后重新下载"),
)


def fmt_clock(seconds: float) -> str:
    total = max(0, int(round(seconds or 0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def fmt_size(size: float) -> str:
    value = float(size or 0)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024:
            return f"{value:.0f} {unit}" if value >= 100 else f"{value:.1f} {unit}"
    return f"{value:.0f} TB"


def fmt_decimal_size(size: float) -> str:
    """Decimal units, matching how model repositories quote download sizes."""
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.0f} {unit}" if value >= 100 else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.0f} TB"


def output_summary(formats: list[str], audio_format: str) -> str:
    pieces = [TEXT_FORMAT_LABELS[f] for f in ("md", "docx") if f in formats]
    if audio_format in AUDIO_LABELS:
        pieces.append(AUDIO_LABELS[audio_format])
    return " · ".join(pieces)


def display_path(path: str) -> str:
    text = str(path or "")
    home = str(Path.home())
    if text == home:
        return "~"
    if text.startswith(home + "/"):
        return "~" + text[len(home):]
    return text


def friendly_error(error: str) -> tuple[str, str]:
    message = (error or "").strip()
    for needle, title, hint in ERROR_HINTS:
        if needle.lower() in message.lower():
            return title, hint
    title = message.splitlines()[0] if message else "转写失败"
    return title[:120], ""


def media_paths(urls) -> list[str]:
    from .. import core

    paths = []
    for url in urls:
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.is_dir() or path.suffix.lower() in core.MEDIA_EXT:
            paths.append(str(path))
    return paths


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_path(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
    except OSError:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class ElidedLabel(QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.set_value(text)

    def set_value(self, text: str) -> None:
        self._full = text
        self._update_elided()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_elided()

    def _update_elided(self) -> None:
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(self._full, Qt.ElideMiddle, max(20, self.width())))
