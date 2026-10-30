"""QPalette and QSS built from the tokens."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import tokens
from .gui.icons import qss_url


def accent_hex() -> str:
    app = QApplication.instance()
    if app is None:
        return "#007AFF"
    palette = app.palette()
    highlight = palette.color(QPalette.Highlight)
    accent = palette.color(QPalette.Accent)
    # Accent falls back to Highlight on platforms without a separate accent color.
    if accent.isValid() and accent != highlight:
        return accent.name()
    return highlight.name()


def accent_text(accent: str) -> str:
    color = QColor(accent)
    return "#1C1C1E" if color.lightness() > 160 else "#FFFFFF"


def build_palette(dark: bool) -> QPalette:
    colors = tokens.palette(dark)
    app = QApplication.instance()
    result = QPalette(app.palette() if app is not None else QPalette())
    roles = {
        QPalette.Window: "bg.app",
        QPalette.WindowText: "text.primary",
        QPalette.Base: "bg.control",
        QPalette.AlternateBase: "bg.sidebar",
        QPalette.Text: "text.primary",
        QPalette.Button: "bg.control",
        QPalette.ButtonText: "text.primary",
        QPalette.BrightText: "bg.content",
        QPalette.ToolTipBase: "bg.control",
        QPalette.ToolTipText: "text.primary",
        QPalette.PlaceholderText: "text.tertiary",
        QPalette.Mid: "line",
        QPalette.Dark: "border",
        QPalette.Light: "line.hair",
        QPalette.Shadow: "line",
    }
    for role, key in roles.items():
        result.setColor(role, QColor(colors[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        result.setColor(QPalette.Disabled, role, QColor(colors["text.tertiary"]))
    result.setColor(QPalette.Disabled, QPalette.Base, QColor(colors["bg.sidebar"]))
    result.setColor(QPalette.Disabled, QPalette.Button, QColor(colors["bg.sidebar"]))
    return result


def build(dark: bool) -> str:
    colors = tokens.palette(dark)
    accent = accent_hex()
    chevron = qss_url("chevron-down", colors["text.secondary"])
    css = """
    QWidget {
        color: %text.primary%;
        font-size: 13px;
    }
    QMainWindow, QDialog, QWidget#root {
        background: %bg.app%;
    }
    QToolBar {
        background: transparent;
        border: none;
        spacing: 6px;
        padding: 4px 10px;
    }
    QToolBar::separator {
        background: %line%;
        width: 1px;
        margin: 7px 5px;
    }
    QToolButton {
        background: transparent;
        border: none;
        border-radius: 5px;
        padding: 4px;
    }
    QToolButton:hover {
        background: %bg.hover%;
    }
    QToolButton:pressed {
        background: %bg.selected%;
    }
    QToolButton:disabled {
        background: transparent;
    }
    QToolButton::menu-indicator {
        image: none;
        width: 0;
    }
    QPushButton {
        background: %bg.control%;
        border: 1px solid %border%;
        border-radius: %radius%;
        padding: 3px 12px;
        min-height: 18px;
    }
    QPushButton:hover {
        background: %bg.hover%;
    }
    QPushButton:pressed {
        background: %bg.selected%;
    }
    QPushButton:disabled {
        color: %text.tertiary%;
        background: %bg.sidebar%;
        border: 1px solid transparent;
    }
    QPushButton#primary {
        background: %accent%;
        border: 1px solid %accent%;
        color: %accent_fg%;
        font-weight: 600;
        padding: 3px 14px;
    }
    QPushButton#primary:hover {
        background: %accent%;
    }
    QPushButton#primary:disabled {
        background: %bg.sidebar%;
        border: 1px solid transparent;
        color: %text.tertiary%;
    }
    QPushButton#link {
        background: transparent;
        border: none;
        color: %text.secondary%;
        padding: 1px 2px;
        min-height: 0;
    }
    QPushButton#link:hover {
        color: %text.primary%;
    }
    QToolButton#link {
        background: transparent;
        border: none;
        color: %text.secondary%;
        font-size: 11px;
        padding: 0 4px;
    }
    QToolButton#link:hover {
        color: %text.primary%;
    }
    QToolButton#link:disabled {
        color: %text.tertiary%;
    }
    QToolButton#chip {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        color: %text.secondary%;
        font-size: 11px;
        font-weight: 600;
        padding: 1px 5px;
    }
    QToolButton#chip:hover {
        border: 1px solid %border%;
        color: %text.primary%;
    }
    QFrame#sidebar {
        background: %bg.sidebar%;
        border-right: 1px solid %line%;
    }
    QFrame#contentArea {
        background: %bg.content%;
    }
    QLabel#groupLabel {
        color: %text.secondary%;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
    }
    QLabel#sideTitle {
        color: %text.secondary%;
        font-size: 11px;
    }
    QLabel#sideValue {
        color: %text.primary%;
        font-size: 11px;
    }
    QWidget#sideValueRow {
        border-radius: %radius%;
        background: transparent;
    }
    QWidget#sideValueRow[hover="true"] {
        background: %bg.hover%;
    }
    QFrame#sideDivider {
        background: %line%;
        border: none;
    }
    QListWidget#filterList {
        background: transparent;
        border: none;
        outline: none;
    }
    QListWidget#filterList::item {
        background: transparent;
        border: none;
    }
    QTreeWidget {
        background: %bg.content%;
        border: none;
        outline: none;
    }
    QTreeWidget::item {
        background: transparent;
        border: none;
        padding: 0;
    }
    QTreeWidget::item:selected {
        background: transparent;
    }
    QTreeWidget::branch {
        background: transparent;
    }
    QHeaderView {
        background: %bg.content%;
        border: none;
    }
    QHeaderView::section {
        background: %bg.content%;
        border: none;
        border-bottom: 1px solid %line%;
        color: %text.secondary%;
        font-size: 11px;
        font-weight: 400;
        padding: 5px 4px;
    }
    QLineEdit, QComboBox {
        background: %bg.control%;
        border: 1px solid %border%;
        border-radius: %radius%;
        padding: 3px 8px;
        min-height: 18px;
        selection-background-color: %accent%;
        selection-color: %accent_fg%;
    }
    QLineEdit:focus, QComboBox:focus {
        border: 1px solid %accent%;
    }
    QLineEdit:read-only {
        background: %bg.sidebar%;
        color: %text.secondary%;
    }
    QLineEdit:disabled, QComboBox:disabled {
        background: %bg.sidebar%;
        color: %text.tertiary%;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
    }
    QComboBox::down-arrow {
        image: url("%CHEVRON%");
        width: 12px;
        height: 12px;
    }
    QComboBox QAbstractItemView {
        background: %bg.control%;
        border: 1px solid %border%;
        selection-background-color: %accent%;
        selection-color: %accent_fg%;
        outline: none;
    }
    QCheckBox {
        spacing: 6px;
    }
    QTextEdit#logView {
        background: %bg.content%;
        border: none;
        border-top: 1px solid %line%;
        color: %text.secondary%;
        padding: 4px 8px;
        selection-background-color: %accent%;
        selection-color: %accent_fg%;
    }
    QWidget#logHeader {
        background: %bg.sidebar%;
        border-top: 1px solid %line%;
    }
    QWidget#statusBar {
        background: %bg.sidebar%;
        border-top: 1px solid %line%;
    }
    QLabel#statusText {
        color: %text.secondary%;
        font-size: 11px;
    }
    QLabel#statusStrong {
        color: %text.primary%;
        font-size: 11px;
    }
    QProgressBar {
        background: %track%;
        border: none;
        border-radius: 2px;
        min-height: 4px;
        max-height: 4px;
    }
    QProgressBar::chunk {
        background: %accent%;
        border-radius: 2px;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: %border%;
        border-radius: 5px;
        min-height: 28px;
    }
    QScrollBar::handle:vertical:hover {
        background: %text.tertiary%;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 10px;
        margin: 0;
    }
    QScrollBar::handle:horizontal {
        background: %border%;
        border-radius: 5px;
        min-width: 28px;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
    }
    QMenu {
        background: %bg.control%;
        border: 1px solid %border%;
        padding: 4px;
    }
    QMenu::item {
        padding: 5px 24px 5px 12px;
        border-radius: 4px;
    }
    QMenu::item:selected {
        background: %accent%;
        color: %accent_fg%;
    }
    QMenu::separator {
        height: 1px;
        background: %line.hair%;
        margin: 4px 8px;
    }
    QSplitter#mainSplitter::handle {
        background: %line%;
        width: 1px;
    }
    QSplitter#rightSplitter::handle {
        background: %line.hair%;
        height: 1px;
    }
    QSplitter#logSplitter::handle {
        background: %line%;
        height: 1px;
    }
    QSplitter::handle:horizontal:hover, QSplitter::handle:vertical:hover {
        background: %accent%;
    }
    QTabWidget::pane {
        border: none;
        background: %bg.content%;
        border-radius: %radius%;
    }
    QTabBar::tab {
        background: transparent;
        color: %text.secondary%;
        padding: 5px 14px;
        margin-right: 2px;
        border-radius: %radius%;
    }
    QTabBar::tab:selected {
        background: %bg.hover%;
        color: %text.primary%;
    }
    QLabel#emptyTitle {
        color: %text.primary%;
        font-size: 13px;
    }
    QLabel#emptyHint {
        color: %text.secondary%;
        font-size: 11px;
    }
    QWidget#emptyPage, QStackedWidget#contentStack {
        background: %bg.content%;
    }
    QWidget#logPanel {
        background: %bg.content%;
    }
    QLabel#percent, QLabel#rate {
        color: %text.secondary%;
        font-size: 11px;
    }
    QLabel#sheetPath {
        color: %text.tertiary%;
        font-size: 11px;
    }
    QWidget#modelSheet {
        background: %bg.content%;
    }
    QDialog#prefsDialog {
        background: %bg.app%;
    }
    QLabel#sheetTitle {
        font-size: 15px;
        font-weight: 600;
    }
    QLabel#sheetText {
        color: %text.secondary%;
        font-size: 11px;
    }
    QLabel#prefsTitle {
        font-size: 15px;
        font-weight: 600;
    }
    QLabel#fieldLabel {
        color: %text.secondary%;
        font-size: 11px;
    }
    QTextEdit#errorDetail, QPlainTextEdit#errorDetail {
        background: %bg.sidebar%;
        border: none;
        border-radius: 4px;
        color: %text.secondary%;
        padding: 6px 8px;
    }
    QToolTip {
        background: %bg.control%;
        color: %text.primary%;
        border: 1px solid %border%;
        padding: 4px 6px;
    }
    """
    replacements = {f"%{key}%": value for key, value in colors.items()}
    replacements.update({
        "%accent%": accent,
        "%accent_fg%": accent_text(accent),
        "%CHEVRON%": chevron,
        "%radius%": str(tokens.SIZES["radius"]),
    })
    for key, value in replacements.items():
        css = css.replace(key, value)
    return css
