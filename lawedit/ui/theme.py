"""앱 전체 테마 — 색상 토큰, 스타일시트, 아이콘."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QIcon, QPalette

# 색상 토큰
C = {
    "bg": "#f4f6fa",          # 창 바탕
    "surface": "#ffffff",     # 카드·편집기
    "surface2": "#f8fafc",    # 리본·머리글
    "border": "#e3e8ef",
    "border2": "#cfd8e3",
    "text": "#1e293b",
    "muted": "#64748b",
    "primary": "#2459c7",
    "primary_dark": "#1c46a0",
    "primary_soft": "#e8effc",
    "accent": "#0f766e",
    "danger": "#c2410c",
    "selection": "#d6e4ff",
}

UI_FONTS = ["Pretendard", "Pretendard Variable", "Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", "Segoe UI"]

QSS = """
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {bg}; }}
QWidget {{ color: {text}; }}
QToolTip {{ background: #1e293b; color: white; border: 0; padding: 6px 8px; border-radius: 6px; }}

/* ---------- 앱 머리 ---------- */
#AppHeader {{ background: {primary}; }}
#AppHeader QLabel#AppTitle {{ color: white; font-size: 15px; font-weight: 700; }}
#AppHeader QLabel#AppDoc {{ color: #dbe6ff; font-size: 13px; }}
#AppHeader QLabel#AppBadge {{ color: {primary}; background: white; border-radius: 10px; padding: 0 10px; font-size: 11px; font-weight: 700; }}

/* ---------- 리본 ---------- */
#Ribbon::pane {{ border: 0; border-bottom: 1px solid {border}; background: {surface}; }}
#Ribbon > QTabBar {{ background: {primary}; }}
#Ribbon > QTabBar::tab {{ background: transparent; color: #dbe6ff; padding: 7px 18px; margin: 0 2px; border: 0;
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600; }}
#Ribbon > QTabBar::tab:hover {{ color: white; background: rgba(255,255,255,0.12); }}
#Ribbon > QTabBar::tab:selected {{ background: {surface}; color: {primary}; }}
#RibbonGroup QLabel#RibbonGroupTitle {{ color: {muted}; font-size: 11px; padding-top: 2px; }}
#RibbonSep {{ background: {border}; max-width: 1px; min-width: 1px; margin: 8px 2px; }}
#RibbonButton {{ border: 0; border-radius: 8px; padding: 4px 6px; color: {text}; font-size: 12px; }}
#RibbonButton:hover {{ background: {primary_soft}; color: {primary_dark}; }}
#RibbonButton:pressed {{ background: {selection}; }}

/* ---------- 문서 탭 ---------- */
QTabWidget#DocTabs::pane {{ border: 0; background: {bg}; }}
QTabWidget#DocTabs > QTabBar {{ background: {bg}; }}
QTabWidget#DocTabs > QTabBar::tab {{ background: transparent; color: {muted}; padding: 8px 16px; margin: 6px 2px 0 2px;
    border: 0; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabWidget#DocTabs > QTabBar::tab:hover {{ color: {text}; }}
QTabWidget#DocTabs > QTabBar::tab:selected {{ color: {primary}; border-bottom: 2px solid {primary}; }}

/* 일반 탭 (도우미·규정집) */
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; background: {surface}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {muted}; padding: 6px 9px; border: 0; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {text}; }}
QTabBar::tab:selected {{ color: {primary}; border-bottom: 2px solid {primary}; font-weight: 600; }}
QTabWidget#SideTabs > QTabBar::tab {{ padding: 6px 7px; }}
QTabWidget#SideTabs > QTabBar::tab:selected {{ font-weight: 400; }}   /* 굵게 하면 탭 폭보다 글자가 넓어져 잘린다 */

/* ---------- 패널(카드) ---------- */
#Card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
#CardHeader {{ background: transparent; border-bottom: 1px solid {border}; }}
#CardHeader QLabel#CardTitle {{ font-weight: 700; color: {text}; font-size: 13px; }}
#CardHeader QLabel#CardSub {{ color: {muted}; font-size: 11px; }}
#CardDot {{ border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }}

/* ---------- 도크 ---------- */
QDockWidget {{ titlebar-close-icon: none; font-weight: 700; color: {text}; }}
QDockWidget::title {{ background: {bg}; padding: 8px 10px 4px 12px; text-align: left; }}
QDockWidget > QWidget {{ background: {bg}; }}

/* ---------- 입력·편집기 ---------- */
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: {surface}; border: 0; selection-background-color: {selection};
    selection-color: {text}; padding: 6px; }}
QLineEdit, QComboBox, QSpinBox {{ background: {surface}; border: 1px solid {border2}; border-radius: 7px; padding: 5px 9px;
    selection-background-color: {selection}; selection-color: {text}; min-height: 18px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {primary}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; selection-background-color: {primary_soft};
    selection-color: {text}; outline: 0; }}

/* ---------- 버튼 ---------- */
QPushButton {{ background: {surface}; border: 1px solid {border2}; border-radius: 7px; padding: 6px 14px; color: {text}; }}
QPushButton:hover {{ background: {surface2}; border-color: {primary}; color: {primary_dark}; }}
QPushButton:pressed {{ background: {primary_soft}; }}
QPushButton:disabled {{ color: #a0aec0; border-color: {border}; }}
QPushButton[primary="true"] {{ background: {primary}; border: 1px solid {primary}; color: white; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {primary_dark}; color: white; }}
QToolButton {{ border-radius: 6px; padding: 3px; }}
QToolButton:hover {{ background: {primary_soft}; }}

/* ---------- 트리·목록·표 ---------- */
QTreeWidget, QListWidget, QTableWidget {{ background: {surface}; border: 0; alternate-background-color: #fafbfd;
    selection-background-color: {primary_soft}; selection-color: {text}; }}
QTreeWidget::item, QListWidget::item {{ padding: 4px 2px; border-radius: 6px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: #f1f5fb; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {primary_soft}; color: {primary_dark}; }}
QHeaderView::section {{ background: {surface2}; color: {muted}; border: 0; border-bottom: 1px solid {border};
    padding: 6px 8px; font-weight: 600; }}
QTableWidget {{ gridline-color: #eef2f7; }}
QTableWidget::item {{ padding: 4px 6px; }}
QTableWidget::item:selected {{ background: {primary_soft}; color: {text}; }}
QTableCornerButton::section {{ background: {surface2}; border: 0; }}

/* ---------- 스크롤바 ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #cbd5e1; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #94a3b8; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #cbd5e1; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 기타 ---------- */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QMenuBar {{ background: {surface}; border-bottom: 1px solid {border}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {primary_soft}; color: {primary_dark}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {primary_soft}; color: {primary_dark}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QStatusBar {{ background: {surface}; border-top: 1px solid {border}; color: {muted}; }}
QStatusBar QLabel {{ color: {muted}; padding: 0 8px; }}
QProgressBar {{ background: {border}; border: 0; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {primary}; border-radius: 4px; }}
QGroupBox {{ border: 1px solid {border}; border-radius: 8px; margin-top: 14px; padding: 10px; background: {surface}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {muted}; font-weight: 600; }}
QCheckBox {{ spacing: 6px; }}
QLabel#Hint {{ color: {muted}; }}
QLabel#Pill {{ background: {primary_soft}; color: {primary_dark}; border-radius: 9px; padding: 2px 10px; font-weight: 600; }}
""".format(**C)

# 비교표·관련정보 등 QTextBrowser 안 HTML 스타일
HTML_CSS = f"""
body {{ font-family: '함초롬바탕','HCR Batang','바탕'; color:{C['text']}; }}
h3 {{ color:{C['primary_dark']}; font-family:'Malgun Gothic'; }}
table {{ border-collapse: collapse; }}
th {{ background:{C['primary_soft']}; color:{C['primary_dark']}; font-family:'Malgun Gothic'; padding:7px; border:1px solid {C['border2']}; }}
td {{ border:1px solid {C['border2']}; padding:7px 9px; vertical-align: top; }}
p {{ margin: 0 0 4px 0; }}
u {{ text-decoration: underline; color:#b42318; }}
a {{ color:{C['primary']}; text-decoration:none; }}
.muted {{ color:{C['muted']}; }}
"""


def apply(app):
    app.setStyle("Fusion")
    f = QFont()
    f.setFamilies(UI_FONTS)
    f.setPointSize(9)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(f)
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(C["bg"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(C["surface"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#fafbfd"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(C["selection"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(C["surface"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#94a3b8"))
    app.setPalette(pal)
    app.setStyleSheet(QSS + _spin_qss())


def _spin_qss() -> str:
    """QSpinBox 에 테두리 QSS를 주면 Fusion 화살표가 사라지므로 화살표 그림을 직접 그려 붙인다."""
    import os
    import tempfile
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QPixmap, QPainter, QPolygonF
    d = os.path.join(tempfile.gettempdir(), "LawEdit")
    os.makedirs(d, exist_ok=True)
    paths = {}
    for name, pts in (("up", [(2, 9), (6, 4), (10, 9)]), ("down", [(2, 4), (6, 9), (10, 4)])):
        pm = QPixmap(12, 12)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["muted"]))
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
        p.end()
        paths[name] = os.path.join(d, f"spin_{name}.png").replace("\\", "/")
        pm.save(paths[name])
    return f"""
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 20px; border: 0;
    border-left: 1px solid {C["border2"]}; background: {C["surface"]}; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 7px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 7px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {C["surface2"]}; }}
QSpinBox::up-arrow {{ image: url("{paths["up"]}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url("{paths["down"]}"); width: 10px; height: 10px; }}
"""


_ICON_DIR = None
_ICON_CACHE: dict = {}


def _icon_dir():
    global _ICON_DIR
    if _ICON_DIR is None:
        import sys
        from pathlib import Path
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        cand = [base / "lawedit" / "resources" / "icons", Path(__file__).resolve().parent.parent / "resources" / "icons"]
        _ICON_DIR = next((c for c in cand if c.exists()), cand[-1])
    return _ICON_DIR


def icon(name: str, color: str | None = None) -> QIcon:
    """아이콘: 빌드 때 저장한 PNG(빠름) → 없으면 qtawesome."""
    key = (name, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    tag = "w" if color in ("white", "#ffffff", "#fff") else "p" if color in (None, C["primary"]) else ""
    ic = QIcon()
    if tag:
        f = _icon_dir() / f"{name}_{tag}.png"
        if f.exists():
            ic = QIcon(str(f))
    if ic.isNull():
        try:
            import qtawesome as qta
            ic = qta.icon("mdi6." + name, color=color or C["primary"], color_active=C["primary_dark"])
        except Exception:
            ic = QIcon()
    _ICON_CACHE[key] = ic
    return ic


def primary(button):
    button.setProperty("primary", True)
    button.style().unpolish(button)
    button.style().polish(button)
    return button

# 대화상자 확인 버튼 강조
QSS += """
QDialogButtonBox QPushButton:default {{ background: {primary}; border: 1px solid {primary}; color: white; font-weight: 600; }}
QDialogButtonBox QPushButton:default:hover {{ background: {primary_dark}; }}
""".format(**C)
