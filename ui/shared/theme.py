"""Shared Qt application theme helpers.

A theme is just a *template* of four base colours — background, surface, text,
accent. There are two templates (light and dark); switching the app between
light and dark simply swaps which template is active. Cards, borders, buttons
and hover states are derived from those four so the user only picks four
swatches per mode in Settings → App.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QToolTip

import config

# Per-mode template defaults. Editable via THEME_<MODE>_<ROLE> config keys.
_TEMPLATE_DEFAULTS = {
    "dark": {
        "bg": "#16181b",
        "surface": "#1c1f23",
        "text": "#e9e6e0",
        "accent": "#d8a145",
    },
    "light": {
        "bg": "#f2efe6",
        "surface": "#e7e2d5",
        "text": "#201e1a",
        "accent": "#a06c10",
    },
}


def is_dark_mode() -> bool:
    """Return True if dark mode should be active right now."""
    mode = getattr(config, "THEME_MODE", "dark")
    if mode == "dark":
        return True
    if mode == "light":
        return False
    # "system" — ask Qt for the OS colour scheme
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def _hex(c: QColor) -> str:
    """Handle hex for UI shared theme."""
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


def _color(value: str, fallback: str) -> QColor:
    """Parse a user colour string, tolerating both #RRGGBB and #RRGGBBAA."""
    s = (value or "").strip()
    if s.startswith("#") and len(s) == 9:  # #RRGGBBAA — drop alpha for the palette
        s = s[:7]
    c = QColor(s)
    return c if c.isValid() else QColor(fallback)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Blend two colours: t=0 → a, t=1 → b."""
    return QColor(
        round(a.red() * (1 - t) + b.red() * t),
        round(a.green() * (1 - t) + b.green() * t),
        round(a.blue() * (1 - t) + b.blue() * t),
    )


def template_base(dark: bool) -> dict[str, str]:
    """The four user-chosen base colours for one mode, as hex strings."""
    mode = "dark" if dark else "light"
    d = _TEMPLATE_DEFAULTS[mode]
    out: dict[str, str] = {}
    for role, default in d.items():
        key = f"THEME_{mode.upper()}_{role.upper()}"
        out[role] = _hex(_color(getattr(config, key, default), default))
    return out


def theme_colors(dark: bool | None = None) -> dict[str, str]:
    """Derive the full palette for the active (or requested) mode.

    Cards, borders, buttons and hover states are computed from the four base
    colours so the user only chooses background, surface, text and accent.
    """
    if dark is None:
        dark = is_dark_mode()
    base = template_base(dark)
    bg = QColor(base["bg"])
    surface = QColor(base["surface"])
    accent = QColor(base["accent"])

    if dark:
        well = QColor("#0e1013")
        card = QColor("#1c1f23")
        border = QColor("#30353b")
        button = well
        button_hover = QColor("#141619")
        button_pressed = QColor("#22262b")
        tab = bg
        tab_selected = well
        tooltip_bg = QColor("#22262b")
        tooltip_border = border
        scroll_handle = QColor("#3a3f46")
        text_dim = QColor("#8b8a86")
        accent_hover = accent.lighter(120)
        accent_fill = accent
        accent_fill_hover = accent_hover
    else:
        well = QColor("#ddd7c7")
        card = surface
        border = QColor("#d1c9b7")
        button = well
        button_hover = QColor("#d8cfba")
        button_pressed = QColor("#cec3aa")
        tab = surface
        tab_selected = QColor("#d8a145")
        tooltip_bg = surface
        tooltip_border = border
        scroll_handle = QColor("#b8ae99")
        text_dim = QColor("#6c6659")
        accent_hover = QColor("#865906")
        accent_fill = QColor("#d8a145")
        accent_fill_hover = QColor("#c68f32")

    return {
        "bg": base["bg"],
        "surface": base["surface"],
        "text": base["text"],
        "accent": base["accent"],
        "accent_fill": _hex(accent_fill),
        "accent_fill_hover": _hex(accent_fill_hover),
        "over_budget": "#c4553d" if dark else "#a3391c",
        "on_accent": base["bg"] if dark else base["text"],
        "well": _hex(well),
        "raised": "#22262b" if dark else "#ddd7c7",
        "rule": "#262a2f" if dark else _hex(border),
        "label": "#b8b4ac" if dark else "#6c6659",
        "disabled": "#5f574f" if dark else _hex(text_dim),
        "card": _hex(card),
        "border": _hex(border),
        "button": _hex(button),
        "button_hover": _hex(button_hover),
        "button_pressed": _hex(button_pressed),
        "tab": _hex(tab),
        "tab_selected": _hex(tab_selected),
        "tab_selected_text": _hex(accent) if dark else base["text"],
        "tooltip_bg": _hex(tooltip_bg),
        "tooltip_border": _hex(tooltip_border),
        "text_dim": _hex(text_dim),
        "accent_hover": _hex(accent_hover),
        "scroll_handle": _hex(scroll_handle),
        # Accent washes blended to opaque colours for Qt stylesheet portability.
        "accent_hint": _hex(_mix(bg, accent, 0.08)),
        "accent_soft": _hex(_mix(bg, accent, 0.12)),
        "accent_strong": _hex(_mix(bg, accent, 0.22)),
    }


def _apply_color_scheme_hint(app: QApplication) -> None:
    """Tell Qt our preferred colour scheme so native window chrome matches.

    On macOS this drives the NSWindow appearance (title bar), which otherwise
    stays light while the styled content is dark — the mismatch that makes the
    overridden dark theme look broken. "system" sets Unknown so the OS decides
    (and so is_dark_mode()'s system path keeps reading the real OS scheme).
    """
    hints = app.styleHints()
    if not hasattr(hints, "setColorScheme"):
        return
    mode = getattr(config, "THEME_MODE", "dark")
    scheme = {
        "dark": Qt.ColorScheme.Dark,
        "light": Qt.ColorScheme.Light,
    }.get(mode, Qt.ColorScheme.Unknown)
    try:
        hints.setColorScheme(scheme)
    except (AttributeError, TypeError):
        pass


def _app_stylesheet(c: dict[str, str]) -> str:
    """Handle app stylesheet for UI shared theme."""
    return f"""
        QWidget {{
            background-color: {c["bg"]};
            color: {c["text"]};
        }}
        QToolTip {{
            color: {c["text"]};
            background-color: {c["tooltip_bg"]};
            border: 1px solid {c["tooltip_border"]};
            padding: 4px;
        }}
        QTabWidget::pane {{
            border: 1px solid {c["border"]};
        }}
        QTabBar::tab {{
            background: {c["tab"]};
            color: {c["text_dim"]};
            padding: 6px 12px;
            border: 1px solid {c["border"]};
            border-bottom: none;
        }}
        QTabBar::tab:selected {{
            background: {c["tab_selected"]};
            color: {c["tab_selected_text"]};
            font-weight: 600;
        }}
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
            background: {c["well"]};
            color: {c["text"]};
            border: 1px solid {c["border"]};
            border-radius: 4px;
            padding: 4px;
            selection-background-color: {c["accent_fill"]};
            selection-color: {c["on_accent"]};
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
            border-color: {c["accent"]};
        }}
        QComboBox QAbstractItemView {{
            background-color: {c["well"]};
            color: {c["text"]};
            border: 1px solid {c["border"]};
            selection-background-color: {c["accent_fill"]};
            selection-color: {c["on_accent"]};
            outline: 0;
        }}
        QPushButton {{
            background: {c["well"]};
            color: {c["accent"]};
            border: 1px solid {c["border"]};
            border-radius: 4px;
            padding: 5px 12px;
        }}
        QPushButton:hover {{
            background: {c["button_hover"]};
        }}
        QPushButton:pressed {{
            background: {c["button_pressed"]};
        }}
        QRadioButton, QCheckBox, QLabel, QGroupBox {{
            color: {c["text"]};
        }}
        QRadioButton::indicator, QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            background: {c["well"]};
            border: 1px solid {c["border"]};
        }}
        QRadioButton::indicator {{
            border-radius: 8px;
        }}
        QRadioButton::indicator:checked {{
            background: {c["on_accent"]};
            border: 5px solid {c["accent"]};
        }}
        QCheckBox::indicator {{
            border-radius: 3px;
        }}
        QCheckBox::indicator:checked {{
            background: {c["accent_fill"]};
            border-color: {c["accent_fill"]};
        }}
        QGroupBox {{
            border: 1px solid {c["border"]};
            border-radius: 4px;
            margin-top: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
            background-color: {c["bg"]};
        }}
        QScrollArea, QFrame {{
            background: transparent;
        }}
        QScrollBar:vertical, QScrollBar:horizontal {{
            background: {c["bg"]};
            border: none;
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background: {c["scroll_handle"]};
            border-radius: 4px;
            min-height: 24px;
            min-width: 24px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
        }}
        """


def apply_tooltip_palette() -> None:
    """Apply the active theme colours to Qt's tooltip palette."""
    c = theme_colors()
    palette = QToolTip.palette()
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["tooltip_bg"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    QToolTip.setPalette(palette)


def show_tooltip_text(pos, text: str, widget=None, *args) -> None:
    """Show a tooltip using the current OpenWand theme palette."""
    apply_tooltip_palette()
    QToolTip.showText(pos, text, widget, *args)


def apply_app_theme(app: QApplication | None = None) -> None:
    """Apply the active mode's template to the whole Qt application."""
    app = app or QApplication.instance()
    if app is None:
        return

    _apply_color_scheme_hint(app)

    c = theme_colors()
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(c["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(c["well"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["card"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["tooltip_bg"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(c["well"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c["accent"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor(c["accent_hover"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c["accent_fill"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c["on_accent"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["text_dim"]))
    palette.setColor(QPalette.ColorRole.Mid, QColor(c["border"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c["text_dim"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c["text_dim"]))

    app.setPalette(palette)
    app.setStyleSheet(_app_stylesheet(c))
    apply_tooltip_palette()
