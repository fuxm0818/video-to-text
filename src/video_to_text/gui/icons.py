"""Colour-tinted SVG icons and painted status glyphs."""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, Qt

_TEMPLATES = Path(__file__).resolve().parents[1] / "assets" / "icons"
_CACHE = Path(tempfile.gettempdir()) / "video-to-text-icons"
_LOCK = threading.Lock()


def _safe_color(color: str) -> str:
    return color.lstrip("#").lower() or "000000"


def svg_path(name: str, color: str) -> Path:
    source = _TEMPLATES / f"{name}.svg"
    if not source.is_file():
        return source
    text = source.read_text(encoding="utf-8")
    if "%ICON_COLOR%" not in text:
        return source
    _CACHE.mkdir(parents=True, exist_ok=True)
    target = _CACHE / f"{name}-{_safe_color(color)}.svg"
    with _LOCK:
        if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
            target.write_text(text.replace("%ICON_COLOR%", color), encoding="utf-8")
    return target


def icon(name: str, color: str, size: int = 20) -> QIcon:
    path = svg_path(name, color)
    result = QIcon(str(path)) if path.is_file() else QIcon()
    if not result.isNull() and size:
        result.addPixmap(result.pixmap(size, size))
    return result


def qss_url(name: str, color: str) -> str:
    return svg_path(name, color).as_posix()


def paint_status(painter: QPainter, rect: QRectF, status: str,
                 colors: dict[str, str], phase: float = 0.0) -> None:
    """Draw a 16 px status glyph centred in ``rect``."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    size = 16.0
    x = rect.center().x() - size / 2
    y = rect.center().y() - size / 2
    box = QRectF(x, y, size, size)
    inner = box.adjusted(2.0, 2.0, -2.0, -2.0)

    color_key = {
        "done": "state.ok",
        "failed": "state.error",
    }.get(status, "text.secondary")
    color = QColor(colors[color_key])
    pen = QPen(color)
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    if status == "pending":
        painter.drawEllipse(inner.adjusted(0.5, 0.5, -0.5, -0.5))
    elif status == "running":
        arc = QRectF(inner)
        painter.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap))
        start = int((-90 + phase * 360) * 16)
        painter.drawArc(arc, start, -260 * 16)
    elif status == "done":
        path = QPainterPath(QPointF(inner.left() + 1.0, inner.center().y()))
        path.lineTo(inner.center().x() - 0.8, inner.bottom() - 1.0)
        path.lineTo(inner.right() + 0.2, inner.top() + 0.8)
        painter.drawPath(path)
    elif status == "skipped":
        painter.drawLine(QPointF(inner.left() + 2.0, inner.center().y()),
                         QPointF(inner.right() - 2.0, inner.center().y()))
    elif status == "failed":
        path = QPainterPath(QPointF(inner.center().x(), inner.top()))
        path.lineTo(inner.right(), inner.bottom() - 0.6)
        path.lineTo(inner.left(), inner.bottom() - 0.6)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(inner.center().x(), inner.top() + 3.2),
                         QPointF(inner.center().x(), inner.bottom() - 3.6))
        painter.drawPoint(QPointF(inner.center().x(), inner.bottom() - 2.0))
    elif status == "canceled":
        painter.drawEllipse(inner.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.drawLine(QPointF(inner.left() + 1.2, inner.bottom() - 1.2),
                         QPointF(inner.right() - 1.2, inner.top() + 1.2))
    else:
        painter.drawLine(QPointF(inner.left() + 2.0, inner.center().y()),
                         QPointF(inner.right() - 2.0, inner.center().y()))
    painter.restore()


def spin_phase() -> float:
    import time

    return (time.monotonic() % 1.6) / 1.6


def drop_pixmap(color: str, size: int = 32):
    path = svg_path("drop", color)
    if not path.is_file():
        return None
    return QIcon(str(path)).pixmap(size, size)
