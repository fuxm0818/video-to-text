"""Qt stylesheet for the desktop window."""
from __future__ import annotations

from pathlib import Path

_ASSETS = (Path(__file__).resolve().parent / "assets").as_posix()


def stylesheet() -> str:
    css = """
    QWidget {
        color: #241f19;
        font-size: 13px;
    }
    QMainWindow, QWidget#root {
        background: #f4efe6;
    }
    QScrollArea { background: transparent; border: none; }
    QWidget#content { background: transparent; }
    QSplitter::handle { background: transparent; }

    QLabel#eyebrow {
        color: #a23b2a;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 2px;
    }
    QLabel#appTitle {
        font-size: 22px;
        font-weight: 600;
    }
    QLabel#tagline {
        color: #7b7165;
        font-size: 12px;
    }
    QLabel#localBadge {
        color: #44624a;
        background: #e7eee4;
        border-radius: 9px;
        padding: 3px 10px;
        font-size: 11px;
    }
    QLabel#versionLabel {
        color: #9a8f80;
        font-size: 11px;
    }

    QFrame#headerLine {
        background: #e3dacb;
        max-height: 1px;
        border: none;
    }

    QFrame#panel {
        background: #fffdf9;
        border: 1px solid #e6ddcf;
        border-radius: 12px;
    }
    QLabel#step {
        color: #a23b2a;
        font-size: 11px;
        font-weight: 600;
    }
    QLabel#panelTitle {
        font-size: 15px;
        font-weight: 600;
    }
    QLabel#hint, QLabel#muted {
        color: #8a7f70;
        font-size: 11px;
    }
    QLabel#countLabel {
        color: #8a7f70;
        font-size: 11px;
    }
    QLabel#fieldLabel {
        color: #6b6153;
        font-size: 12px;
        font-weight: 500;
    }
    QLabel#summaryLabel {
        color: #7b7165;
        font-size: 11px;
    }
    QFrame#divider {
        background: #ece4d6;
        border: none;
        max-height: 1px;
    }
    QLabel#progressTitle {
        font-size: 16px;
        font-weight: 600;
    }
    QLabel#progressDetail {
        color: #7b7165;
        font-size: 12px;
    }
    QLabel#elapsedLabel {
        color: #8a7f70;
        font-size: 11px;
    }
    QLabel#stateBadge {
        border-radius: 9px;
        padding: 2px 10px;
        font-size: 11px;
        background: #f1ece2;
        color: #7b7165;
    }
    QLabel#stateBadge[state="running"] {
        background: #f6e7e2;
        color: #a23b2a;
    }
    QLabel#stateBadge[state="done"] {
        background: #e7eee4;
        color: #44624a;
    }
    QLabel#stateBadge[state="canceled"] {
        background: #f3efe6;
        color: #9a8f80;
    }

    QPushButton {
        background: #fffdf9;
        border: 1px solid #d9cfbf;
        border-radius: 8px;
        padding: 7px 14px;
    }
    QPushButton:hover {
        border-color: #a23b2a;
    }
    QPushButton:pressed {
        background: #f7efe8;
    }
    QPushButton:disabled {
        color: #b4a998;
        background: #f7f2e9;
        border-color: #e6ddcf;
    }
    QPushButton#primary {
        background: #a23b2a;
        border: 1px solid #a23b2a;
        color: #fffaf6;
        font-weight: 600;
    }
    QPushButton#primary:hover {
        background: #8d3324;
        border-color: #8d3324;
    }
    QPushButton#primary:disabled {
        background: #d9c2ba;
        border-color: #d9c2ba;
        color: #fff8f5;
    }
    QPushButton#startButton {
        background: #a23b2a;
        border: 1px solid #a23b2a;
        color: #fffaf6;
        padding: 12px 16px;
        font-size: 15px;
        font-weight: 600;
        border-radius: 10px;
    }
    QPushButton#startButton:hover {
        background: #8d3324;
        border-color: #8d3324;
    }
    QPushButton#startButton:pressed {
        background: #7c2c1f;
    }
    QPushButton#startButton:disabled {
        background: #d9c2ba;
        border-color: #d9c2ba;
        color: #fff8f5;
    }
    QPushButton#quiet {
        background: transparent;
        border: none;
        color: #7b7165;
        padding: 3px 6px;
    }
    QPushButton#quiet:hover {
        color: #a23b2a;
    }
    QPushButton#quiet:disabled {
        background: transparent;
        color: #c3b8a7;
    }
    QPushButton#rowRemove {
        background: transparent;
        border: none;
        color: #a89c8b;
        font-size: 15px;
        padding: 0;
    }
    QPushButton#rowRemove:hover {
        color: #a23b2a;
    }
    QPushButton#outputChip {
        background: #f6efe3;
        border: 1px solid #e2d6c3;
        border-radius: 6px;
        color: #6b5b45;
        font-size: 10px;
        font-weight: 600;
        padding: 2px 8px;
    }
    QPushButton#outputChip:hover {
        border-color: #a23b2a;
        color: #a23b2a;
    }

    QLineEdit, QComboBox {
        background: #fffdf9;
        border: 1px solid #d9cfbf;
        border-radius: 8px;
        padding: 6px 10px;
        min-height: 20px;
        selection-background-color: #a23b2a;
        selection-color: #fffaf6;
    }
    QLineEdit:focus, QComboBox:focus {
        border-color: #a23b2a;
    }
    QLineEdit:read-only {
        background: #f8f4ec;
        color: #5d5548;
    }
    QLineEdit:disabled, QComboBox:disabled {
        background: #f7f2e9;
        color: #a89c8b;
    }
    QComboBox {
        padding-right: 30px;
    }
    QComboBox::drop-down {
        border: none;
        width: 28px;
    }
    QComboBox::down-arrow {
        image: url("__ASSETS__/icons/chevron.svg");
        width: 11px;
        height: 11px;
    }
    QComboBox QAbstractItemView {
        background: #fffdf9;
        border: 1px solid #d9cfbf;
        selection-background-color: #f3e4dc;
        selection-color: #241f19;
        outline: none;
    }
    QCheckBox {
        spacing: 7px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #cec2b0;
        border-radius: 4px;
        background: #fffdf9;
    }
    QCheckBox::indicator:hover {
        border-color: #a23b2a;
    }
    QCheckBox::indicator:checked {
        background: #a23b2a;
        border-color: #a23b2a;
        image: url("__ASSETS__/icons/check.svg");
    }
    QCheckBox::indicator:disabled {
        background: #f4eee3;
        border-color: #e2d7c6;
    }
    QCheckBox:disabled {
        color: #a89c8b;
    }

    QTreeWidget {
        background: transparent;
        border: none;
        outline: none;
    }
    QHeaderView {
        background: transparent;
        border: none;
    }
    QTreeWidget::item {
        border-bottom: 1px solid #efe8db;
        padding: 4px 2px;
    }
    QTreeWidget::item:selected {
        background: #f6ece6;
        color: #241f19;
    }
    QHeaderView::section {
        background: transparent;
        border: none;
        border-bottom: 1px solid #e6ddcf;
        color: #8a7f70;
        font-size: 11px;
        padding: 6px 3px;
    }

    QLabel#statusBadge {
        border-radius: 9px;
        padding: 2px 8px;
        font-size: 11px;
        background: #f1ece2;
        color: #7b7165;
    }
    QLabel#statusBadge[state="running"] {
        background: #f6e7e2;
        color: #a23b2a;
    }
    QLabel#statusBadge[state="done"] {
        background: #e7eee4;
        color: #44624a;
    }
    QLabel#statusBadge[state="failed"] {
        background: #f8e4e0;
        color: #a33b2b;
    }
    QLabel#statusBadge[state="skipped"] {
        background: #edf0f2;
        color: #6b7280;
    }
    QLabel#statusBadge[state="canceled"] {
        background: #f3efe6;
        color: #9a8f80;
    }

    QFrame#dropZone {
        background: #fcfaf5;
        border: 1px dashed #d9cfbf;
        border-radius: 10px;
    }
    QLabel#dropTitle {
        color: #6b6153;
        font-size: 13px;
        font-weight: 500;
    }
    QLabel#dropHint {
        color: #9a8f80;
        font-size: 11px;
    }

    QFrame#modelNote {
        background: #fdf4e4;
        border: 1px solid #f0dfc0;
        border-radius: 8px;
    }
    QLabel#modelNoteTitle {
        color: #8a5a17;
        font-size: 12px;
        font-weight: 600;
    }
    QLabel#modelNoteText {
        color: #8a6a3a;
        font-size: 11px;
    }

    QProgressBar {
        border: none;
        background: #ece4d6;
        border-radius: 5px;
        min-height: 10px;
        max-height: 10px;
    }
    QProgressBar::chunk {
        background: #a23b2a;
        border-radius: 5px;
    }

    QFrame#statCell {
        background: transparent;
        border: none;
    }
    QLabel#statValue {
        font-size: 18px;
        font-weight: 600;
    }
    QLabel#statCaption {
        color: #8a7f70;
        font-size: 10px;
    }

    QPlainTextEdit#log {
        background: #fbf7ef;
        border: 1px solid #e6ddcf;
        border-radius: 8px;
        color: #5d5548;
        font-size: 11px;
        padding: 6px;
    }

    QToolButton#logToggle {
        background: transparent;
        border: none;
        color: #7b7165;
        padding: 2px 4px;
    }
    QToolButton#logToggle:hover {
        color: #a23b2a;
    }

    QStatusBar {
        background: #f4efe6;
        color: #8a7f70;
        font-size: 11px;
    }
    QStatusBar::item { border: none; }

    QMenu {
        background: #fffdf9;
        border: 1px solid #d9cfbf;
        padding: 4px;
    }
    QMenu::item {
        padding: 5px 22px 5px 18px;
        border-radius: 5px;
    }
    QMenu::item:selected {
        background: #f3e4dc;
    }

    QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #d8cdbb;
        border-radius: 5px;
        min-height: 32px;
    }
    QScrollBar::handle:vertical:hover {
        background: #c4b7a3;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
    """
    return css.replace("__ASSETS__", _ASSETS)
