"""메인 창 — 법령안편집기."""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QSettings
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QTextCursor, QColor, QBrush, QCloseEvent
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QDockWidget, QTableWidget, QTableWidgetItem, QHeaderView, QTextBrowser,
                               QPlainTextEdit, QLabel, QFileDialog, QMessageBox, QInputDialog, QPushButton, QLineEdit,
                               QListWidget, QListWidgetItem, QComboBox, QAbstractItemView, QStatusBar, QProgressBar,
                               QApplication, QMenu, QCheckBox, QGridLayout)

from .. import __version__
from ..core import checks, numbering, fileio, docs, standards, otherlaw, lawapi
from ..core.amend import compare, build_amendment_lines, build_compare_table, compare_table_html, apply_amendment
from ..core.dictionary import load_default, DEFAULT_CATEGORIES, add_user_term, read_user_terms, write_user_terms, add_ignored
from ..core.model import LawDoc, Unit, Appendix, DIVISION_LABEL
from ..core.parser import parse_text, guess_law_type
from ..core.korean import josa
from ..core.render import render_doc
from ..core.refs import extract_refs, law_names_cited
from .dialogs import (NewDocDialog, SettingsDialog, LawSearchDialog, FindReplaceDialog, ArticlePicker, DocPreviewDialog,
                      NoticeOptionsDialog, BatchDialog, export_text_or_html)
from .widgets import LawEditor, Ribbon, run_job, text_icon, law_font, Card, fit_to_screen
from . import theme
from PySide6.QtWidgets import QFrame, QSizePolicy, QToolButton

APP_TITLE = "법령안편집기"
# 리본 아이콘 (Material Design Icons)
ICONS = {
    "새": "file-plus-outline", "열": "folder-open-outline", "저": "content-save-outline", "다": "content-save-edit-outline",
    "현": "file-import-outline", "예": "bullhorn-outline", "관": "newspaper-variant-outline", "이": "text-box-outline",
    "한": "file-export-outline", "개": "file-document-edit-outline", "대": "table-large", "법": "scale-balance",
    "찾": "text-search", "분": "compare-horizontal", "적": "file-replace-outline", "신": "plus-box-outline",
    "삭": "delete-outline", "이동": "arrow-right-bold-box-outline", "맞": "swap-vertical", "일": "format-list-numbered",
    "표": "map-marker-path", "전": "file-document-multiple-outline", "자": "format-letter-case", "취": "undo-variant",
    "조": "check-decagram-outline", "용": "spellcheck", "스": "format-paint", "괄": "layers-triple-outline",
    "설": "cog-outline", "?": "information-outline", "규": "book-open-page-variant-outline", "영": "sitemap-outline",
    "충": "alert-octagon-outline", "AI개": "robot-outline", "AI제": "file-star-outline", "AI설": "tune-variant",
}
FILE_FILTER = "법령 문서 (*.lawj *.hwp *.hwpx *.txt *.pdf *.html);;LawEdit 프로젝트 (*.lawj);;모든 파일 (*.*)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1440, 900)
        self.project = fileio.Project()
        self.current: LawDoc | None = None          # 현행
        self.revised: LawDoc = LawDoc(name="", law_type="규정", amend_type="제정")
        self.changes = []
        self.dirty = False
        self.dictionary = None
        self.regbook = None
        self.reg_graph = None
        self.reg_corpus = None
        self.reg_window = None
        self.issues = []
        self.settings = lawapi.load_settings()
        self._building = False
        self._build_ui()
        self._update_title()
        self._dict_waiters = []          # 용어 사전은 처음 쓸 때 읽는다(시작 속도)

    # ================================================================ UI
    def _act(self, text, fn, icon="", shortcut=None, tip="") -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(theme.icon(ICONS.get(icon, icon)))
        a.triggered.connect(fn)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        tip = tip or text
        a.setToolTip(f"<b>{text}</b>" + (f" <span style='color:#94a3b8'>({shortcut})</span>" if shortcut else "") +
                     (f"<br>{tip}" if tip != text else ""))
        a.setStatusTip(tip)
        return a

    def _build_ui(self):
        A = self._act
        self.acts = {
            "new": A("신규", self.new_doc, "새", "Ctrl+N", "새 법령안을 만듭니다."),
            "open": A("불러오기", self.open_file, "열", "Ctrl+O", "법령안(.lawj)이나 HWP/HWPX/TXT/PDF 문서를 불러옵니다."),
            "save": A("저장", self.save_file, "저", "Ctrl+S", "법령안을 저장합니다(.lawj)."),
            "saveas": A("다른 이름", self.save_file_as, "다", "Ctrl+Shift+S"),
            "cur": A("현행추가", self.load_current, "현", None, "개정 대상 현행 법령(규정)을 불러옵니다."),
            "notice": A("입법예고문", self.make_notice, "예", None, "입법예고문을 만듭니다."),
            "gazette": A("관보게재문", self.make_gazette, "관", None, "관보(공포·발령) 게재문을 만듭니다."),
            "reason": A("제개정이유", self.make_reason, "이", None, "제정·개정이유 및 주요내용"),
            "hwpx": A("한글로 저장", lambda: self.export("법령안"), "한", None, "법령안·개정문·대비표를 HWPX/HWP/PDF로 내보냅니다."),
            "exp_amend": A("개정문 내보내기", lambda: self.export("개정문"), "개", None),
            "exp_table": A("대비표 내보내기", lambda: self.export("대비표"), "대", None),
            "search": A("법령검색", self.law_search, "법", "Ctrl+L", "국가법령정보센터에서 법령을 검색합니다."),
            "find": A("찾기", self.find_replace, "찾", "Ctrl+F"),
            "analyze": A("개정분석", self.analyze, "분", "F5", "현행과 개정안을 비교해 개정문·대비표를 만듭니다(필수)."),
            "swap": A("맞교환", self.swap_articles, "맞"),
            "delete": A("삭제", self.delete_article, "삭", None, "커서가 있는 조문을 삭제합니다."),
            "insert": A("조문신설", self.insert_article, "신", "Ctrl+Shift+N", "커서가 있는 조문 뒤에 가지조문을 신설합니다."),
            "move": A("조문이동", self.move_article, "이동"),
            "renum": A("일괄변경", self.batch_change, "일", None, "조문 번호를 차례로 다시 매기거나 자구를 한꺼번에 바꿉니다."),
            "movemark": A("이동표시", self.toggle_move_mark, "표"),
            "whole": A("전문개정", self.whole_amend, "전", None, "전부개정으로 바꾸고 조문 번호를 정리합니다."),
            "reset": A("자구재설정", self.reset_phrasing, "자", None, "개정문의 자구 묶음 방식을 바꿔 다시 만듭니다."),
            "revert": A("개정취소", self.revert_article, "취", None, "커서가 있는 조문을 현행대로 되돌립니다."),
            "apply": A("개정문분석", self.apply_amendment_text, "적", None, "개정문을 현행에 적용해 개정 본문을 만듭니다."),
            "check": A("조문 검사", self.check_structure, "조", "F7", "번호·인용·부호·형식을 검사합니다."),
            "terms": A("용어 검사", self.check_terms, "용", "F8", "용어·띄어쓰기·맞춤법을 검사합니다."),
            "style": A("스타일링", self.styling, "스", None, "부호·띄어쓰기를 표준 서식으로 정리합니다."),
            "batch": A("일괄처리", self.batch, "괄"),
            "settings": A("설정", self.open_settings, "설"),
            "regbook": A("규정집 분석", self.open_regbook, "규", "F9", "규정집 PDF를 불러와 상·하위 체계, 영향, 상충을 분석합니다."),
            "impact": A("개정 영향분석", self.impact_of_revision, "영", None, "지금 개정안이 상·하위 규정에 미치는 영향을 찾습니다."),
            "conflict": A("상충 검사", self.conflicts_of_revision, "충", None, "개정안과 상·하위 규정의 상충을 검사합니다."),
            "about": A("정보", self.about, "?"),
            "ai_amend": A("AI 개정안", self.ai_amend, "AI개", "Ctrl+Shift+A", "개정 의도를 적으면 AI가 조문 수정안을 쓰고, 엔진이 개정문·대비표를 만들고 검증합니다."),
            "ai_new": A("AI 제정안", self.ai_new, "AI제", None, "제정 목적과 위임 조항으로 AI가 규정 초안을 씁니다."),
            "ai_settings": A("AI 설정", self.ai_settings, "AI설", None, "Claude 또는 Ollama 등 연결할 AI 모델을 고릅니다."),
        }
        self.ribbon = Ribbon()
        home = self.ribbon.page("홈")
        g = Ribbon.group(home, "파일 (필수)")
        for k in ("new", "open", "save", "saveas", "cur"):
            g.add(self.acts[k])
        g = Ribbon.group(home, "문서처리")
        for k in ("notice", "gazette", "reason"):
            g.add(self.acts[k])
        g = Ribbon.group(home, "한글도구")
        for k in ("hwpx", "exp_amend", "exp_table"):
            g.add(self.acts[k])
        g = Ribbon.group(home, "법령검색")
        g.add(self.acts["search"])
        g = Ribbon.group(home, "검색도구")
        g.add(self.acts["find"])
        g = Ribbon.group(home, "부가기능")
        g.add(self.acts["settings"])
        g.add(self.acts["about"])
        am = self.ribbon.page("개정도구")
        g = Ribbon.group(am, "개정분석 (필수)")
        g.add(self.acts["analyze"])
        g.add(self.acts["apply"])
        g = Ribbon.group(am, "개정도구")
        for k in ("insert", "delete", "move", "swap", "renum", "movemark", "whole", "reset", "revert"):
            g.add(self.acts[k])
        rv = self.ribbon.page("조문검토")
        g = Ribbon.group(rv, "조문검토")
        for k in ("check", "terms", "style"):
            g.add(self.acts[k])
        g = Ribbon.group(rv, "일괄업무")
        g.add(self.acts["batch"])
        ai = self.ribbon.page("AI 도우미")
        g = Ribbon.group(ai, "AI 초안 (엔진 검증)")
        g.add(self.acts["ai_amend"])
        g.add(self.acts["ai_new"])
        g = Ribbon.group(ai, "모델")
        g.add(self.acts["ai_settings"])
        rg = self.ribbon.page("규정집 분석")
        g = Ribbon.group(rg, "규정집")
        for k in ("regbook", "impact", "conflict"):
            g.add(self.acts[k])

        # ---- 가운데
        self.ed_rev = LawEditor()
        self.ed_rev.setPlaceholderText("법령안(개정안) 본문을 입력하거나 [불러오기]·[현행추가]로 문서를 여세요.\n\n예)\n제1조(목적) 이 규정은 …\n제2조(정의) …")
        self.ed_rev.changed_debounced.connect(self.on_revised_changed)
        self.ed_rev.textChanged.connect(self._mark_dirty)
        self.ed_cur = LawEditor(read_only=True)
        self.ed_cur.setPlaceholderText("현행 법령(규정)이 없습니다. [현행추가]로 불러오면 개정문과 대비표가 만들어집니다.")
        self.ed_rev2 = LawEditor()
        self.ed_rev2.share_document(self.ed_rev)
        self.ed_cur2 = LawEditor(read_only=True)
        self.ed_cur2.share_document(self.ed_cur)
        self.view_amend = LawEditor(read_only=True)
        self.view_table_small = QTextBrowser()
        self.view_table_small.setFont(law_font(10))
        self.view_table = QTextBrowser()
        self.view_table.setFont(law_font(10))
        self.view_amend_full = LawEditor(read_only=True)
        self.ed_addenda = QPlainTextEdit()
        self.ed_addenda.setFont(law_font(11))
        self.ed_addenda.setPlaceholderText("이번 개정의 부칙 (예: 이 규정은 발령한 날부터 시행한다.)")
        self.ed_addenda.textChanged.connect(self._refresh_amend_full)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("DocTabs")
        self.tabs.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)
        self.tabs.addTab(Card(self.ed_rev, "법령안", "편집", theme.C["primary"]), theme.icon("file-document-edit-outline"), "법령안")
        s1 = QSplitter(Qt.Orientation.Horizontal)
        for w, t, c in ((self.ed_cur, "현행", "#64748b"), (self.ed_rev2, "개정", theme.C["primary"]), (self.view_amend, "개정문", "#c2410c")):
            s1.addWidget(self._titled(w, t, c))
        self.tabs.addTab(s1, theme.icon("compare-horizontal"), "현행 / 개정 / 개정문")
        s2 = QSplitter(Qt.Orientation.Horizontal)
        for w, t, c in ((self.ed_cur2, "현행", "#64748b"), (self.view_table_small, "신ㆍ구조문대비표", "#0f766e")):
            s2.addWidget(self._titled(w, t, c))
        self.tabs.addTab(s2, theme.icon("table-large"), "현행 / 개정 / 대비표")
        s3 = QSplitter(Qt.Orientation.Vertical)
        s3.addWidget(self._titled(self.view_amend_full, "개정문(본문)", "#c2410c"))
        s3.addWidget(self._titled(self.ed_addenda, "부칙", "#7c3aed"))
        s3.setSizes([600, 180])
        self.tabs.addTab(s3, theme.icon("text-box-outline"), "개정문(본문)")
        self.tabs.addTab(self._titled(self.view_table, "신ㆍ구조문대비표", "#0f766e"), theme.icon("table-large"), "신ㆍ구조문대비표")
        for tb in (self.view_table, self.view_table_small):
            tb.document().setDefaultStyleSheet(theme.HTML_CSS)
        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        tv.addWidget(self._build_header())
        tv.addWidget(self.ribbon)
        self.setMenuWidget(top)            # 창 전체 폭으로
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(4, 0, 4, 6)
        bl.addWidget(self.tabs)
        mv.addWidget(body, 1)
        self.setCentralWidget(main)

        # ---- 왼쪽: 조문 구조
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["조문", "상태"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.setMinimumWidth(270)
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setColumnWidth(1, 44)
        d = QDockWidget("조문 구조", self)
        d.setObjectName("dock_tree")
        d.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        d.setWidget(self._dock_body(self.tree, (10, 0, 0, 6)))
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, d)

        # ---- 오른쪽: 도우미
        self.side = QTabWidget()
        self.side.setObjectName("SideTabs")
        for wdg, ic, t in ((self._build_examples(), "gavel", "입법례"), (self._build_standards(), "lightbulb-on-outline", "표준문장"),
                           (self._build_related(), "link-variant", "연관정보"), (self._build_appendix(), "paperclip", "별표·서식"),
                           (self._build_terms(), "book-alphabet", "용어관리"), (self._build_otherlaw(), "source-branch", "타법개정")):
            # 좁은 도우미 칸에 탭 6개가 다 보이도록 글자만(아이콘은 풍선 도움말 대신 생략)
            self.side.addTab(wdg, t)
        self.side.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.side.setUsesScrollButtons(True)
        d2 = QDockWidget("도우미", self)
        d2.setObjectName("dock_side")
        d2.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(0, 0, 10, 6)
        sl.addWidget(self.side)
        d2.setWidget(sw)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, d2)
        self.side.setMinimumWidth(400)
        QTimer.singleShot(0, lambda: self.resizeDocks([d, d2], [290, 420], Qt.Orientation.Horizontal))

        # ---- 아래: 검사 결과
        self.issue_table = QTableWidget(0, 5)
        self.issue_table.setHorizontalHeaderLabels(["수준", "분류", "위치", "내용", "제안"])
        self.issue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.issue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.issue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.issue_table.itemDoubleClicked.connect(self._issue_clicked)
        self.issue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.issue_table.customContextMenuRequested.connect(self._issue_menu)
        d3 = QDockWidget("검사 결과", self)
        d3.setObjectName("dock_issues")
        d3.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                       | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.issue_table.verticalHeader().setVisible(False)
        self.issue_table.setAlternatingRowColors(True)
        self.issue_table.setShowGrid(False)
        w3 = QWidget()
        v3 = QVBoxLayout(w3)
        v3.setContentsMargins(10, 0, 10, 6)
        row = QHBoxLayout()
        self.issue_filter = QComboBox()
        self.issue_filter.addItems(["전체", "오류", "경고", "참고"])
        self.issue_filter.currentTextChanged.connect(lambda *_: self._show_issues(self.issues))
        self.issue_label = QLabel("")
        fix = theme.primary(QPushButton(theme.icon("check-decagram-outline", "white"), " 선택 제안 적용"))
        fix.clicked.connect(self._apply_selected_suggestions)
        row.addWidget(QLabel("보기"))
        row.addWidget(self.issue_filter)
        row.addWidget(self.issue_label, 1)
        row.addWidget(fix)
        v3.addLayout(row)
        card3 = QFrame()
        card3.setObjectName("Card")
        c3 = QVBoxLayout(card3)
        c3.setContentsMargins(1, 1, 1, 1)
        c3.addWidget(self.issue_table)
        v3.addWidget(card3)
        d3.setWidget(w3)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, d3)
        self.dock_issues = d3

        # ---- 단축키는 창에 등록 (메뉴줄 대신 머리의 ≡ 메뉴)
        for a in self.acts.values():
            self.addAction(a)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.prog = QProgressBar()
        self.prog.setMaximumWidth(220)
        self.prog.setVisible(False)
        self.status.addPermanentWidget(self.prog)
        self.pos_label = QLabel("")
        self.status.addPermanentWidget(self.pos_label)
        self.ed_rev.cursorPositionChanged.connect(self._cursor_moved)
        self.findrep = None

    def _titled(self, w, title, color=""):
        return Card(w, title, "", color)

    def _build_header(self):
        h = QFrame()
        h.setObjectName("AppHeader")
        h.setFixedHeight(44)
        l = QHBoxLayout(h)
        l.setContentsMargins(16, 0, 16, 0)
        l.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.icon("scale-balance", "white").pixmap(22, 22))
        t = QLabel("법령안편집기")
        t.setObjectName("AppTitle")
        sep = QLabel("·")
        sep.setObjectName("AppDoc")
        self.h_doc = QLabel("빈문서")
        self.h_doc.setObjectName("AppDoc")
        self.h_badge = QLabel("규정 · 제정")
        self.h_badge.setObjectName("AppBadge")
        self.h_badge.setFixedHeight(20)
        for x in (logo, t, sep, self.h_doc, self.h_badge):
            l.addWidget(x)
        l.addStretch(1)
        menu = QMenu(self)
        for k in ("new", "open", "cur", "save", "saveas"):
            menu.addAction(self.acts[k])
        menu.addSeparator()
        menu.addAction(self._act("문서 정보…", self.edit_meta, "", None))
        menu.addAction(self._act("본문 정리(다시 그리기)", self.reformat, "", None))
        menu.addSeparator()
        for k in ("settings", "about"):
            menu.addAction(self.acts[k])
        menu.addAction(self._act("끝내기", self.close, "", "Ctrl+Q"))
        self.h_menu = QToolButton()
        self.h_menu.setText("≡")
        self.h_menu.setMenu(menu)
        self.h_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.h_menu.setStyleSheet("QToolButton{color:white;border:0;font-size:20px;padding:0 10px;border-radius:6px}"
                                  "QToolButton:hover{background:rgba(255,255,255,0.15)}QToolButton::menu-indicator{image:none}")
        l.insertWidget(0, self.h_menu)
        for key in ("save", "analyze", "regbook"):
            b = QToolButton()
            b.setDefaultAction(self.acts[key])
            b.setIcon(theme.icon(ICONS[{"save": "저", "analyze": "분", "regbook": "규"}[key]], "white"))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setStyleSheet("QToolButton{color:white;border:0;padding:4px 10px;border-radius:6px;font-weight:600}"
                            "QToolButton:hover{background:rgba(255,255,255,0.15)}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            l.addWidget(b)
        return h

    def _dock_body(self, w, margins=(10, 0, 10, 10)):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(*margins)
        card = QFrame()
        card.setObjectName("Card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(1, 1, 1, 1)
        cv.addWidget(w)
        v.addWidget(card)
        return box

    # ---- 도우미 패널들
    def _build_examples(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.ex_query = QLineEdit()
        self.ex_query.setPlaceholderText("조 제목 또는 문구 (예: 위원회의 구성)")
        self.ex_scope = QComboBox()
        self.ex_scope.addItems(["규정집", "국가법령(API)"])
        b = QPushButton("검색")
        b.clicked.connect(self.search_examples)
        self.ex_query.returnPressed.connect(self.search_examples)
        row.addWidget(self.ex_query, 1)
        row.addWidget(self.ex_scope)
        row.addWidget(b)
        v.addLayout(row)
        self.ex_list = QListWidget()
        self.ex_list.currentItemChanged.connect(lambda it, _: self.ex_view.setPlainText(it.data(Qt.ItemDataRole.UserRole) if it else ""))
        v.addWidget(self.ex_list, 1)
        self.ex_view = LawEditor(read_only=True)
        v.addWidget(self.ex_view, 1)
        ins = theme.primary(QPushButton("커서 위치에 넣기"))
        ins.clicked.connect(lambda: self.insert_text(self.ex_view.textCursor().selectedText().replace(" ", "\n") or self.ex_view.toPlainText()))
        v.addWidget(ins)
        return w

    def _build_standards(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.std_tree = QTreeWidget()
        self.std_tree.setHeaderHidden(True)
        for cat, items in standards.STANDARDS.items():
            top = QTreeWidgetItem([cat])
            for name, tpl in items:
                c = QTreeWidgetItem([name])
                c.setData(0, Qt.ItemDataRole.UserRole, tpl)
                top.addChild(c)
            self.std_tree.addTopLevelItem(top)
        self.std_tree.expandAll()
        self.std_view = LawEditor(read_only=True)
        self.std_tree.currentItemChanged.connect(self._std_preview)
        self.std_tree.itemDoubleClicked.connect(lambda *_: self.insert_text(self.std_view.toPlainText()))
        v.addWidget(self.std_tree, 1)
        v.addWidget(self.std_view, 1)
        b = theme.primary(QPushButton("커서 위치에 넣기"))
        b.clicked.connect(lambda: self.insert_text(self.std_view.toPlainText()))
        v.addWidget(b)
        return w

    def _std_preview(self, it, _=None):
        if it and it.data(0, Qt.ItemDataRole.UserRole):
            self.std_view.setPlainText(standards.fill(it.data(0, Qt.ItemDataRole.UserRole), self.revised.law_type,
                                                      self.settings.get("org", "공사") and "공사"))

    def _build_related(self):
        self.related = QTextBrowser()
        self.related.document().setDefaultStyleSheet(theme.HTML_CSS)
        self.related.setOpenExternalLinks(True)
        self.related.setFont(law_font(10))
        return self.related

    def _build_appendix(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.ap_list = QListWidget()
        self.ap_list.currentRowChanged.connect(self._ap_select)
        v.addWidget(self.ap_list, 1)
        self.ap_title = QLineEdit()
        self.ap_title.setPlaceholderText("제목")
        self.ap_ref = QLineEdit()
        self.ap_ref.setPlaceholderText("관련 조문 (예: 제3조 관련)")
        self.ap_text = QPlainTextEdit()
        self.ap_text.setFont(law_font(10))
        v.addWidget(self.ap_title)
        v.addWidget(self.ap_ref)
        v.addWidget(self.ap_text, 1)
        row = QGridLayout()           # 좁은 도우미 창에서도 글자가 잘리지 않게 두 줄로
        row.setSpacing(4)
        for k, (t, fn) in enumerate([("별표 신설", lambda: self._ap_add("별표")), ("별지 신설", lambda: self._ap_add("별지")),
                                     ("적용", self._ap_apply), ("목록 삭제", self._ap_clear),
                                     ("위로", lambda: self._ap_move(-1)), ("아래로", lambda: self._ap_move(1)),
                                     ("삭제", self._ap_delete)]):
            b = QPushButton(t)
            b.setStyleSheet("padding: 5px 6px;")
            b.clicked.connect(fn)
            row.addWidget(b, k // 4, k % 4)
        v.addLayout(row)
        return w

    def _build_terms(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("사용자 용어 사전 (찾을말 → 바꿀말). 법령안편집기 사전 문법(~, ∨, [a|b]) 사용 가능"))
        self.term_table = QTableWidget(0, 3)
        self.term_table.setHorizontalHeaderLabels(["찾을말", "바꿀말", "설명"])
        self.term_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.term_table, 1)
        row = QHBoxLayout()
        for t, fn in [("용어추가", self._term_add), ("행 삭제", self._term_del), ("저장", self._term_save)]:
            b = QPushButton(t)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self.dict_info = QLabel("용어 사전은 [용어 검사]를 처음 실행할 때 읽습니다.")
        self.dict_info.setWordWrap(True)
        v.addWidget(self.dict_info)
        self._term_load()
        return w

    def _build_otherlaw(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("이 개정 때문에 함께 고쳐야 할 다른 규정 (규정집 필요)"))
        row = QHBoxLayout()
        self.ol_terms = QLineEdit()
        self.ol_terms.setPlaceholderText("추가로 바꿀 명칭: 옛말=새말; 옛말2=새말2")
        row.addWidget(self.ol_terms, 1)
        b1 = QPushButton("타법목록 추출")
        b1.clicked.connect(self.other_list)
        b2 = QPushButton("타법개정 문안")
        b2.clicked.connect(self.other_amend)
        row.addWidget(b1)
        row.addWidget(b2)
        v.addLayout(row)
        self.ol_view = QTextBrowser()
        self.ol_view.setFont(law_font(10))
        v.addWidget(self.ol_view, 1)
        b3 = QPushButton("부칙에 넣기")
        b3.clicked.connect(self._ol_to_addenda)
        v.addWidget(b3)
        self._ol_text = ""
        return w

    # ================================================================ 상태
    def _update_title(self):
        name = self.revised.name or (self.current.name if self.current else "") or "빈문서"
        if hasattr(self, "h_doc"):
            self.h_doc.setText(name + (" •" if self.dirty else ""))
            self.h_badge.setText(f"{self.revised.law_type} · {self.revised.amend_type}")
        self.setWindowTitle(f"{APP_TITLE} - {name} [{self.revised.law_type}, {self.revised.amend_type}]"
                            + (" *" if self.dirty else "") + (f" — {self.project.path}" if self.project.path else ""))

    def _mark_dirty(self):
        if not self._building and not self.dirty:
            self.dirty = True
            self._update_title()

    def _load_dictionary_async(self):
        self.status.showMessage("용어 사전 읽는 중…")
        run_job(load_default, self.settings.get("conf_dir") or None, on_done=self._dict_loaded,
                on_fail=lambda e: self.status.showMessage("사전 읽기 실패: " + e.split("\n")[0], 8000))

    def _with_dictionary(self, fn):
        """사전이 준비되면 fn 실행 (처음이면 백그라운드로 읽는다)."""
        if self.dictionary is not None:
            fn()
            return
        self._dict_waiters.append(fn)
        if len(self._dict_waiters) == 1:
            self._load_dictionary_async()

    def _dict_loaded(self, d):
        self.dictionary = d
        waiters, self._dict_waiters = self._dict_waiters, []
        for fn in waiters:
            fn()
        self.dict_info.setText(f"사전 {len(d.rules):,}개 규칙 — " + ", ".join(Path(s).name if os.sep in s or "/" in s else s for s in d.sources))
        self.status.showMessage(f"용어 사전 준비 완료 ({len(d.rules):,}개 규칙)", 5000)

    def _doc_from_editor(self) -> LawDoc:
        meta = (self.revised.name, self.revised.law_type, self.revised.amend_type, self.revised.org)
        d = parse_text(self.ed_rev.toPlainText(), name="")
        if not d.name:
            d.name = meta[0]
        d.law_type, d.amend_type, d.org = meta[1], meta[2], meta[3]
        if not d.name and meta[0]:
            d.name = meta[0]
        d.appendices = d.appendices or self.revised.appendices
        return d

    def set_revised_text(self, text: str, undoable: bool = True):
        self._building = True
        if undoable and self.ed_rev.toPlainText():
            c = self.ed_rev.textCursor()
            pos = c.position()
            c.beginEditBlock()
            c.select(QTextCursor.SelectionType.Document)
            c.insertText(text)
            c.endEditBlock()
            c.setPosition(min(pos, len(text)))
            self.ed_rev.setTextCursor(c)
        else:
            self.ed_rev.setPlainText(text)
        self._building = False
        self.on_revised_changed()

    def set_revised_doc(self, d: LawDoc, undoable=True):
        self.revised = d
        self.set_revised_text(render_doc(d), undoable)
        self._mark_dirty()

    # ================================================================ 갱신
    def on_revised_changed(self):
        new = self._doc_from_editor()
        name, lt, at, org = self.revised.name, self.revised.law_type, self.revised.amend_type, self.revised.org
        self.revised = new
        if not new.name:
            new.name = name
        self._refresh_amend()     # self.changes 를 먼저 갱신해야 트리 상태(신설·개정)가 맞다
        self._refresh_tree()
        self._refresh_appendix_list()
        self._update_title()

    def _refresh_amend(self):
        if self.current is None:
            self.changes = []
            self.view_amend.setPlainText("현행이 없습니다. (제정안이면 [문서처리]에서 공포문을 만들 수 있습니다.)")
            self.view_table_small.setHtml("")
            self.view_table.setHtml("")
            self._refresh_amend_full()
            self.ed_rev.mark_lines(set())
            return
        try:
            self.changes = compare(self.current, self.revised)
            lines = build_amendment_lines(self.current, self.revised, self.changes, group_same=self.settings.get("group_same", True))
            if not self.changes and self.revised.amend_type == "일부개정":
                lines.append("(아직 바뀐 조문이 없습니다. 가운데 [개정] 칸이나 [법령안] 탭에서 조문을 고치면 개정문이 여기에 만들어집니다.)")
            self.view_amend.set_text_keep_scroll("\n".join(lines))
            html_t = compare_table_html(self.current, self.revised)
            self.view_table_small.setHtml(html_t)
            self.view_table.setHtml(html_t)
        except Exception as e:     # noqa: BLE001
            self.view_amend.setPlainText(f"개정 분석 중 오류: {e}")
        self._refresh_amend_full()
        self._mark_changed_lines()

    def _refresh_amend_full(self):
        if self.current is None:
            self.view_amend_full.setPlainText("")
            return
        lines = [docs.amended_title(self.revised), ""] + build_amendment_lines(self.current, self.revised, self.changes,
                                                                               group_same=self.settings.get("group_same", True))
        add = self.ed_addenda.toPlainText().strip() or docs.default_addenda(self.revised)
        lines += ["", "부칙", add]
        self.view_amend_full.set_text_keep_scroll("\n".join(lines))

    def _mark_changed_lines(self):
        """개정안 편집기에서 바뀐 조문 줄 칠하기."""
        arts = set()
        for c in self.changes:
            if c.art_path:
                arts.add(c.art_path if c.kind != "renumber" else c.new_label)
                if c.new_unit is not None and c.new_unit.kind == "article":
                    arts.add(c.new_unit.number_label())
        lines = set()
        doc = self.ed_rev.document()
        cur_art = None
        for i in range(doc.blockCount()):
            t = doc.findBlockByNumber(i).text()
            m = re.match(r"^\s*(제\d+조(?:의\d+)?)", t)
            if m:
                cur_art = m.group(1)
            elif re.match(r"^\s*(제\d+(장|절|편|관)|부\s*칙)", t):
                cur_art = None
            if cur_art and cur_art in arts:
                lines.add(i)
        self.ed_rev.mark_lines(lines, "#fff7e6")

    def _refresh_tree(self):
        self.tree.clear()
        status = {}
        for c in self.changes:
            key = c.new_unit.number_label() if c.new_unit is not None and c.new_unit.kind == "article" else c.art_path
            lab = {"add": "신설", "delete": "삭제", "whole": "개정", "phrase": "개정", "title": "개정", "renumber": "이동"}.get(c.kind, "")
            if key and lab:
                status.setdefault(key, lab if c.path == c.art_path or c.kind == "renumber" else "개정")
        colors = {"신설": "#047857", "삭제": "#b42318", "개정": "#c2410c", "이동": "#2459c7"}

        def add(parent, u: Unit):
            if u.kind in DIVISION_LABEL:
                it = QTreeWidgetItem([u.heading(), ""])
                it.setForeground(0, QBrush(QColor("#9a3412")))
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                for c in u.children:
                    add(it, c)
            elif u.kind == "article":
                st = "삭제" if u.deleted else status.get(u.number_label(), "")
                it = QTreeWidgetItem([u.heading() if not u.deleted else u.number_label() + " 삭제", st])
                if st:
                    it.setForeground(1, QBrush(QColor(colors.get(st, "#000"))))
            else:
                return
            it.setData(0, Qt.ItemDataRole.UserRole, u.number_label() if u.kind == "article" else u.heading())
            (parent.addChild(it) if parent is not None else self.tree.addTopLevelItem(it))
        for u in self.revised.body:
            add(None, u)
        if self.revised.addenda:
            it = QTreeWidgetItem(["부칙", ""])
            it.setData(0, Qt.ItemDataRole.UserRole, "부칙")
            self.tree.addTopLevelItem(it)
        self.tree.expandAll()

    def _tree_clicked(self, it, col):
        lab = it.data(0, Qt.ItemDataRole.UserRole) or ""
        ed = self.active_editor()
        if lab.startswith("제") and "조" in lab:
            ln = ed.find_unit_line(lab)
        else:
            ln = next((i for i in range(ed.document().blockCount()) if ed.document().findBlockByNumber(i).text().strip().startswith(lab)), -1)
        if ln >= 0:
            ed.goto_line(ln)

    def _tree_menu(self, pos):
        m = QMenu(self)
        for k in ("insert", "delete", "move", "swap", "revert"):
            m.addAction(self.acts[k])
        it = self.tree.itemAt(pos)
        if it:
            self._tree_clicked(it, 0)
        m.exec(self.tree.mapToGlobal(pos))

    def active_editor(self) -> LawEditor:
        i = self.tabs.currentIndex()
        return self.ed_rev2 if i == 1 else self.ed_rev

    def _cursor_article(self) -> Unit | None:
        ed = self.ed_rev if self.tabs.currentIndex() != 1 else self.ed_rev2
        c = ed.textCursor()
        b = c.block()
        while b.isValid():
            m = re.match(r"^\s*제(\d+)조(?:의(\d+))?", b.text())
            if m:
                return self.revised.find_article(int(m.group(1)), int(m.group(2) or 0))
            if re.match(r"^\s*(제\d+(장|절|편|관)|부\s*칙)", b.text()):
                return None
            b = b.previous()
        return None

    def _cursor_moved(self):
        a = self._cursor_article()
        self.pos_label.setText(a.heading() if a else "")
        if a is not None and getattr(self, "_last_rel", None) != a.number_label():
            self._last_rel = a.number_label()
            QTimer.singleShot(300, lambda a=a: self._show_related(a))

    # ================================================================ 파일
    def maybe_save(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, APP_TITLE, "변경 내용을 저장할까요?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save_file()
        return r == QMessageBox.StandardButton.Discard

    def new_doc(self):
        if not self.maybe_save():
            return
        dlg = NewDocDialog(self, "", "규정", "제정", self.settings.get("dept", ""))
        if not dlg.exec():
            return
        name, lt, at, org = dlg.values()
        self.project = fileio.Project()
        self.current = None
        self.ed_cur.setPlainText("")
        self.revised = LawDoc(name=name, law_type=lt, amend_type=at, org=org)
        tpl = f"{name}\n\n제1장 총칙\n제1조(목적) {standards.subject_word(lt)}은(는) …을 목적으로 한다.\n제2조(정의) {standards.subject_word(lt)}에서 사용하는 용어의 뜻은 다음과 같다.\n  1. “…”이란 …을 말한다.\n"
        self.ed_addenda.setPlainText(docs.default_addenda(self.revised))
        self.set_revised_text(tpl.replace("이 규정은(는)", "이 규정은"), undoable=False)
        self.dirty = False
        self._update_title()

    def open_file(self, path: str | None = None):
        if not path:
            if not self.maybe_save():
                return
            path, _ = QFileDialog.getOpenFileName(self, "불러오기", self._last_dir(), FILE_FILTER)
            if not path:
                return
        self._remember_dir(path)
        if path.lower().endswith(".pdf"):
            self._open_pdf(path, as_current=False)
            return
        try:
            if path.lower().endswith(".lawj"):
                pr = fileio.Project.load(path)
                self.project = pr
                self.current = pr.current
                self.ed_cur.setPlainText(render_doc(pr.current) if pr.current else "")
                self.revised = pr.revised or LawDoc()
                self.ed_addenda.setPlainText(pr.addenda_text)
                self.set_revised_text(render_doc(self.revised), undoable=False)
            else:
                text = fileio.read_any(path)
                d = parse_text(text)
                if not d.name:
                    d.name = Path(path).stem
                d.amend_type = "제정" if self.current is None else d.amend_type
                self.project = fileio.Project()
                self.current = None
                self.ed_cur.setPlainText("")
                self.revised = d
                r = QMessageBox.question(self, "불러오기", f"「{d.name}」(조문 {len(d.articles())}개)을 불러왔습니다.\n\n"
                                         "이 문서를 '현행'으로 두고 개정안을 작성할까요?\n(아니요: 제정안·법령안으로 편집)")
                if r == QMessageBox.StandardButton.Yes:
                    self._set_current(d)
                else:
                    self.set_revised_text(render_doc(d), undoable=False)
            self.dirty = False
            self._update_title()
            self.status.showMessage(f"불러왔습니다: {path}", 5000)
        except Exception as e:      # noqa: BLE001
            QMessageBox.critical(self, "불러오기 실패", str(e))

    def _set_current(self, cur: LawDoc, amend_type: str = "일부개정"):
        self.current = cur
        self.ed_cur.setPlainText(render_doc(cur))
        rev = cur.clone()
        rev.amend_type = amend_type
        self.revised = rev
        self.ed_addenda.setPlainText(self.ed_addenda.toPlainText() or docs.default_addenda(rev))
        self.set_revised_text(render_doc(rev), undoable=False)
        self.tabs.setCurrentIndex(1)

    def load_current(self):
        path, _ = QFileDialog.getOpenFileName(self, "현행 불러오기", self._last_dir(), FILE_FILTER)
        if not path:
            return
        if path.lower().endswith(".pdf"):
            self._open_pdf(path, as_current=True)
            return
        try:
            if path.lower().endswith(".lawj"):
                pr = fileio.Project.load(path)
                d = pr.revised or pr.current
            else:
                d = parse_text(fileio.read_any(path))
                if not d.name:
                    d.name = Path(path).stem
            self._set_current(d)
            self._mark_dirty()
        except Exception as e:      # noqa: BLE001
            QMessageBox.critical(self, "현행 불러오기 실패", str(e))

    # ---- PDF: 규정집(여러 규정 묶음)이면 개정할 규정을 고르게 한다
    def _open_pdf(self, path: str, as_current: bool):
        from .regbook_window import _load_or_build
        self.status.showMessage("PDF 분석 중… (규정집이면 처음 한 번 20초 안팎)")
        self.prog.setVisible(True)
        self.prog.setRange(0, 0)

        def done(res):
            self.prog.setVisible(False)
            rb, graph, corpus = res
            entries = [e for e in rb.entries if e.doc is not None and e.doc.articles()]
            if len(entries) >= 2:
                self._pick_from_regbook(path, rb, graph, corpus, entries)
            else:
                self._open_single_pdf(path, as_current)

        def fail(e):
            self.prog.setVisible(False)
            QMessageBox.critical(self, "PDF 불러오기 실패", e.split("\n")[0])
        run_job(_load_or_build, path, on_done=done, on_fail=fail,
                on_progress=lambda i, n: (self.prog.setRange(0, n), self.prog.setValue(i)))

    def _pick_from_regbook(self, path, rb, graph, corpus, entries):
        self.set_regbook(rb, graph, corpus)
        QSettings("LawEdit", "LawEdit").setValue("regbook_pdf", path)
        if self.reg_window is not None:
            self.reg_window.rb, self.reg_window.graph, self.reg_window.corpus = rb, graph, corpus
            self.reg_window._loaded((rb, graph, corpus))
        labels = [f"{e.code}  {e.name}" + (" (폐지)" if e.repealed else "") for e in entries]
        item, ok = QInputDialog.getItem(self, "규정집 — 개정할 규정 선택",
                                        f"이 PDF는 규정 {len(entries)}개가 묶인 「{rb.title or '규정집'}」입니다.\n"
                                        "개정할 규정을 고르세요. (규정집 분석·명칭 일괄 개정·타법개정도 함께 연결됩니다)",
                                        labels, 0, False)
        if not ok:
            self.status.showMessage(f"규정집을 연결했습니다: 규정 {len(entries)}개 — [규정집 분석]에서 볼 수 있습니다.", 8000)
            return
        e = entries[labels.index(item)]
        self.load_from_regbook(e)
        self.status.showMessage(f"「{e.name}」{josa(e.name, '을/를')} 현행으로 불러왔습니다. 규정집 {len(entries)}개 규정 연결됨.", 8000)

    def _open_single_pdf(self, path, as_current):
        try:
            d = parse_text(fileio.read_any(path))
            if not d.name:
                d.name = Path(path).stem
            if as_current:
                self._set_current(d)
                self._mark_dirty()
            else:
                self.project = fileio.Project()
                self.current = None
                self.ed_cur.setPlainText("")
                self.revised = d
                self.set_revised_text(render_doc(d), undoable=False)
        except Exception as ex:      # noqa: BLE001
            QMessageBox.critical(self, "PDF 불러오기 실패", str(ex))

    def save_file(self) -> bool:
        if not self.project.path:
            return self.save_file_as()
        return self._save(self.project.path)

    def save_file_as(self) -> bool:
        name = (self.revised.name or "법령안") + (f" {self.revised.amend_type}안" if self.current else "")
        path, _ = QFileDialog.getSaveFileName(self, "저장", str(Path(self._last_dir()) / f"{name}.lawj"), "LawEdit 프로젝트 (*.lawj)")
        if not path:
            return False
        if not path.lower().endswith(".lawj"):
            path += ".lawj"
        return self._save(path)

    def _save(self, path) -> bool:
        try:
            self.on_revised_changed()
            self.project.current = self.current
            self.project.revised = self.revised
            self.project.addenda_text = self.ed_addenda.toPlainText()
            self.project.save(path)
            self._remember_dir(path)
            self.dirty = False
            self._update_title()
            self.status.showMessage(f"저장했습니다: {path}", 5000)
            return True
        except Exception as e:      # noqa: BLE001
            QMessageBox.critical(self, "저장 실패", str(e))
            return False

    def _last_dir(self):
        return QSettings("LawEdit", "LawEdit").value("last_dir", str(Path.home() / "Documents"))

    def _remember_dir(self, path):
        QSettings("LawEdit", "LawEdit").setValue("last_dir", str(Path(path).parent))

    def edit_meta(self):
        d = NewDocDialog(self, self.revised.name, self.revised.law_type, self.revised.amend_type, self.revised.org)
        if d.exec():
            self.revised.name, self.revised.law_type, self.revised.amend_type, self.revised.org = d.values()
            self._update_title()
            self._refresh_amend()

    def reformat(self):
        self.set_revised_doc(self._doc_from_editor())

    # ================================================================ 개정도구
    def _need_article(self) -> Unit | None:
        a = self._cursor_article()
        if a is None:
            QMessageBox.information(self, APP_TITLE, "커서를 조문 안에 두고 실행하세요.")
        return a

    def analyze(self):
        self.on_revised_changed()
        if self.current is None:
            QMessageBox.information(self, "개정분석", "현행이 없습니다. [현행추가]로 개정 대상 규정을 불러오세요.")
            return
        n = {}
        for c in self.changes:
            n[c.kind] = n.get(c.kind, 0) + 1
        lab = {"phrase": "자구 개정", "whole": "전체 개정", "add": "신설", "delete": "삭제", "title": "제목 개정", "renumber": "번호 변경",
               "div_title": "장ㆍ절 제목", "div_add": "장ㆍ절 신설"}
        msg = ", ".join(f"{lab.get(k, k)} {v}건" for k, v in n.items()) or "변경 사항이 없습니다."
        self.tabs.setCurrentIndex(1)
        self.status.showMessage("개정분석: " + msg, 10000)

    def insert_article(self):
        a = self._cursor_article()
        d = self.revised
        title, ok = QInputDialog.getText(self, "조문신설", "조 제목")
        if not ok:
            return
        mode = "branch" if self.current is not None else "renumber"
        if self.current is not None:
            r = QMessageBox.question(self, "조문신설", "가지조문(제N조의2)으로 신설할까요?\n아니요를 누르면 뒤 조문 번호를 하나씩 밀어냅니다.")
            mode = "branch" if r == QMessageBox.StandardButton.Yes else "renumber"
        na = numbering.insert_article(d, a, title=title, text="…", mode=mode)
        self.set_revised_doc(d)
        ln = self.ed_rev.find_unit_line(na.number_label())
        self.ed_rev.goto_line(ln, "…")

    def delete_article(self):
        a = self._need_article()
        if a is None:
            return
        mark = self.current is not None and self.settings.get("delete_mark", True)
        if QMessageBox.question(self, "삭제", f"{a.heading()}{josa(a.heading(), '을/를')} 삭제할까요?" + ("\n(번호는 남기고 '삭제'로 표시)" if mark else "")) \
                != QMessageBox.StandardButton.Yes:
            return
        numbering.delete_article(self.revised, a, "mark" if mark else "remove")
        self.set_revised_doc(self.revised)

    def move_article(self):
        a = self._need_article()
        if a is None:
            return
        dlg = ArticlePicker(self.revised, "조문이동", f"{a.heading()}{josa(a.heading(), '을/를')} 어느 조문 뒤로 옮길까요?", self, allow_top=True)
        if not dlg.exec():
            return
        uid = dlg.chosen()
        if uid == "__none__":
            return
        target = self.revised.find_uid(uid) if uid else None
        if target is a:
            return
        mp = numbering.move_article(self.revised, a, target, renumber=True, mark_moved=self.settings.get("mark_moved", False))
        self.set_revised_doc(self.revised)
        self.status.showMessage(f"조문이동: 번호 변경 {len(mp)}건, 본문 인용도 함께 고쳤습니다.", 8000)

    def swap_articles(self):
        a = self._need_article()
        if a is None:
            return
        dlg = ArticlePicker(self.revised, "맞교환", f"{a.heading()}과(와) 맞바꿀 조문", self)
        if not dlg.exec():
            return
        b = self.revised.find_uid(dlg.chosen())
        if b is None or b is a:
            return
        numbering.swap_articles(self.revised, a, b)
        self.set_revised_doc(self.revised)

    def batch_change(self):
        items = ["조문 번호를 차례로 다시 매기기(가지번호·삭제 조문 정리)", "자구 일괄 변경"]
        it, ok = QInputDialog.getItem(self, "일괄변경", "작업", items, 0, False)
        if not ok:
            return
        if it == items[0]:
            dels = [a.number_label() for a in self.revised.articles() if a.deleted]
            if dels and self.revised.amend_type == "일부개정" and QMessageBox.question(
                    self, "일괄변경",
                    f"‘{dels[0]} 삭제’ 등 삭제된 조 {len(dels)}개의 자리도 함께 없어집니다.\n"
                    "일부개정 개정문에는 삭제 자리를 없애는 문형이 없어 개정문·대비표와 본문이 어긋날 수 있습니다"
                    "(전부개정을 권합니다).\n\n그래도 번호를 다시 매길까요?") != QMessageBox.StandardButton.Yes:
                return
            mp = numbering.renumber_sequential(self.revised)
            self.set_revised_doc(self.revised)
            self.status.showMessage(f"번호 정리: {sum(1 for k, v in mp.items() if k != v)}개 조문 번호 변경", 8000)
        else:
            old, ok = QInputDialog.getText(self, "자구 일괄 변경", "바꿀 자구")
            if not ok or not old:
                return
            new, ok = QInputDialog.getText(self, "자구 일괄 변경", f"“{old}” → ")
            if not ok:
                return
            n = numbering.batch_rename_titles(self.revised, old, new)
            self.set_revised_doc(self.revised)
            self.status.showMessage(f"{n}곳 변경", 8000)

    def toggle_move_mark(self):
        self.settings["mark_moved"] = not self.settings.get("mark_moved", False)
        lawapi.save_settings(self.settings)
        self.status.showMessage("조문이동 시 이동표시: " + ("켜짐" if self.settings["mark_moved"] else "꺼짐"), 6000)

    def whole_amend(self):
        if QMessageBox.question(self, "전문개정", "전부개정으로 바꾸고 조문 번호를 1부터 다시 매길까요?") != QMessageBox.StandardButton.Yes:
            return
        self.revised.amend_type = "전부개정"
        numbering.renumber_sequential(self.revised)
        for u in [x for top in self.revised.body for x in top.iter()]:
            u.history = ""
        self.set_revised_doc(self.revised)

    def reset_phrasing(self):
        self.settings["group_same"] = not self.settings.get("group_same", True)
        lawapi.save_settings(self.settings)
        self._refresh_amend()
        self.status.showMessage("같은 자구 묶기(“각각”): " + ("사용" if self.settings["group_same"] else "사용 안 함"), 6000)

    def revert_article(self):
        a = self._need_article()
        if a is None or self.current is None:
            return
        from ..core.amend import align_units
        pair = next(((c, n) for c, n in align_units(self.current.articles(), self.revised.articles()) if n is a), None)
        if not pair or pair[0] is None:
            QMessageBox.information(self, "개정취소", "현행에 대응하는 조문이 없습니다(신설 조문은 [삭제]를 쓰세요).")
            return
        c = pair[0].clone()
        lst, idx = self.revised.parent_of(a)
        lst[idx] = c
        self.set_revised_doc(self.revised)

    def apply_amendment_text(self):
        if self.current is None:
            QMessageBox.information(self, "개정문분석", "먼저 [현행추가]로 현행을 불러오세요.")
            return
        dlg = DocPreviewDialog("개정문분석 — 개정문을 붙여 넣고 [현행에 적용]을 누르세요", "", self, apply_label="현행에 적용")
        dlg.ed.setPlaceholderText("○○규정 일부를 다음과 같이 개정한다.\n\n제3조제1항 중 “A”를 “B”로 한다.\n…")
        if not dlg.exec() or not dlg.ed.toPlainText().strip():
            return
        new, log = apply_amendment(self.current, dlg.ed.toPlainText())
        new.amend_type = "일부개정"
        self.set_revised_doc(new)
        bad = [l for l in log if not l.startswith("[적용]")]
        QMessageBox.information(self, "개정문분석", f"적용 {len(log) - len(bad)}건" + (f", 확인 필요 {len(bad)}건:\n" + "\n".join(bad[:15]) if bad else ""))

    # ================================================================ 검토
    def check_structure(self):
        d = self._doc_from_editor()
        self.issues = checks.check_structure(d) + checks.check_references(d) + checks.check_marks(d)
        self._show_issues(self.issues)

    def check_terms(self):
        if self.dictionary is None:
            self.status.showMessage("용어 사전 읽는 중… (처음 한 번)")
            self.issue_table.setRowCount(0)          # 이전 검사 결과가 새 결과처럼 보이지 않게 비운다
            self.issue_label.setText("  용어 사전 읽는 중… 끝나면 용어 검사 결과가 여기에 나옵니다.")
            self.dock_issues.raise_()
            self._with_dictionary(self.check_terms)
            return
        d = self._doc_from_editor()
        cats = set(DEFAULT_CATEGORIES)
        if self.settings.get("easy_terms"):
            cats.add("알기쉬운용어")
        self.issues = checks.check_terms(d, self.dictionary, cats)
        self._show_issues(self.issues)

    def styling(self):
        d = self._doc_from_editor()
        n = checks.apply_styling(d)
        self.set_revised_doc(d)
        self.status.showMessage(f"스타일링: {n}곳 정리", 8000)

    def _show_issues(self, issues):
        f = self.issue_filter.currentText()
        shown = [x for x in issues if f == "전체" or x.level == f]
        self.issue_table.setRowCount(len(shown))
        col = {"오류": "#b42318", "경고": "#b45309", "참고": "#2459c7"}
        for r, x in enumerate(shown):
            for c, v in enumerate([x.level, x.category, x.where, x.message, x.suggestion]):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setForeground(QBrush(QColor(col.get(x.level, "#000"))))
                    it.setText("● " + v)
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                it.setData(Qt.ItemDataRole.UserRole, x)
                self.issue_table.setItem(r, c, it)
        self.issue_table.resizeColumnsToContents()
        self.issue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        cnt = {}
        for x in issues:
            cnt[x.level] = cnt.get(x.level, 0) + 1
        self.issue_label.setText("  " + ", ".join(f"{k} {v}" for k, v in cnt.items()) if issues else "  문제가 발견되지 않았습니다.")
        self.dock_issues.raise_()

    def _issue_clicked(self, it):
        x = it.data(Qt.ItemDataRole.UserRole)
        self.tabs.setCurrentIndex(0)
        m = re.match(r"^(제\d+조(?:의\d+)?)(제\d+항)?(제\d+호(?:의\d+)?)?", x.where or "")
        if not m:
            return
        sub = ""
        if m.group(3):
            sub = re.sub(r"제(\d+)호(?:의(\d+))?", lambda mm: mm.group(1) + (("의" + mm.group(2)) if mm.group(2) else "") + ".", m.group(3))
        elif m.group(2):
            from ..core.model import circled
            sub = circled(int(re.findall(r"\d+", m.group(2))[0]))
        ln = self.ed_rev.find_unit_line(m.group(1), sub)
        self.ed_rev.goto_line(ln, x.found)

    def _issue_menu(self, pos):
        it = self.issue_table.itemAt(pos)
        if not it:
            return
        x = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        if x.found and x.suggestion:
            m.addAction(f"“{x.found}” → “{x.suggestion}” 적용", lambda: self._apply_suggestion(x))
        if x.found:
            m.addAction(f"“{x.found}” 무시 목록에 추가", lambda: (add_ignored(x.found), self._load_dictionary_async()))
            m.addAction("사용자 사전에 등록…", lambda: self._term_add(x.found, x.suggestion))
        m.exec(self.issue_table.viewport().mapToGlobal(pos))

    def _apply_suggestion(self, x) -> bool:
        d = self._doc_from_editor()
        # uid 는 다시 파싱하면 바뀌므로 위치(조문)로 찾는다
        m = re.match(r"^(제\d+조(?:의\d+)?)", x.where or "")
        targets = [a for a in d.articles() if m and a.number_label() == m.group(1)] or d.articles()
        for a in targets:
            for u in a.iter():
                if x.found in u.text:
                    u.text = u.text.replace(x.found, x.suggestion, 1)
                    self.set_revised_doc(d)
                    return True
        return False

    def _apply_selected_suggestions(self):
        rows = sorted({i.row() for i in self.issue_table.selectedItems()})
        n = 0
        for r in rows:
            x = self.issue_table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            if x.found and x.suggestion and self._apply_suggestion(x):
                n += 1
        self.status.showMessage(f"{n}건 적용", 6000)

    # ================================================================ 문서처리
    def _notice_defaults(self):
        return {"org": self.revised.org or self.settings.get("dept", ""), "contact": self.settings.get("contact", ""),
                "days": docs.kind_info(self.revised)[2], "reason": self.project.reason,
                "points": self.project.points or docs.summarize_changes(self.current, self.revised, self.changes)}

    def make_notice(self):
        self.on_revised_changed()
        dlg = NoticeOptionsDialog(self, "입법예고문", self._notice_defaults())
        if not dlg.exec():
            return
        v = dlg.values()
        self.project.reason, self.project.points = v["reason"], v["points"]
        t = docs.legislative_notice(self.current, self.revised, org=v["org"], reason=v["reason"], main_points=v["points"],
                                    notice_no=v["no"], days=v["days"], contact=v["contact"])
        DocPreviewDialog("입법예고문", t, self).exec()

    def make_gazette(self):
        self.on_revised_changed()
        dlg = NoticeOptionsDialog(self, "관보게재문", self._notice_defaults())
        if not dlg.exec():
            return
        v = dlg.values()
        t = docs.gazette_text(self.current, self.revised, number=v["no"], addenda=self.ed_addenda.toPlainText().strip())
        DocPreviewDialog("관보게재문", t, self).exec()

    def make_reason(self):
        self.on_revised_changed()
        dlg = NoticeOptionsDialog(self, "제ㆍ개정이유", self._notice_defaults())
        if not dlg.exec():
            return
        v = dlg.values()
        self.project.reason, self.project.points = v["reason"], v["points"]
        DocPreviewDialog("제ㆍ개정이유 및 주요내용", docs.reason_text(self.current, self.revised, v["reason"], v["points"]), self).exec()

    def export(self, what: str):
        self.on_revised_changed()
        name = self.revised.name or "법령안"
        if what == "법령안":
            export_text_or_html(self, name, render_doc(self.revised), kind="doc", default_name=name)
        elif what == "개정문":
            if self.current is None:
                QMessageBox.information(self, "내보내기", "현행이 없어 개정문이 없습니다.")
                return
            export_text_or_html(self, docs.amended_title(self.revised), self.view_amend_full.toPlainText(), kind="doc",
                                default_name=f"{name} 개정문")
        else:
            if self.current is None:
                QMessageBox.information(self, "내보내기", "현행이 없어 대비표가 없습니다.")
                return
            rows = build_compare_table(self.current, self.revised)
            title = f"{name} 신ㆍ구조문대비표"
            export_text_or_html(self, title, html_body=compare_table_html(self.current, self.revised, title),
                                compare_rows=rows, default_name=title)

    # ================================================================ 법령검색 / 도우미
    def law_search(self):
        a = self._cursor_article()
        q = ""
        if a:
            names = law_names_cited(a.plain())
            q = names[0] if names else ""
        dlg = LawSearchDialog(self, q)
        dlg.open_doc.connect(self._law_from_search)
        dlg.exec()

    def _law_from_search(self, d: LawDoc, mode: str):
        if mode == "current":
            if not self.maybe_save():
                return
            self.project = fileio.Project()
            self._set_current(d)
        else:
            DocPreviewDialog(d.name, render_doc(d), self).exec()

    def find_replace(self):
        if self.findrep is None:
            self.findrep = FindReplaceDialog(self.active_editor, self)
        self.findrep.show()
        self.findrep.raise_()

    def insert_text(self, text: str):
        if not text:
            return
        ed = self.ed_rev
        c = ed.textCursor()
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        c.insertText("\n" + text.strip())
        ed.setTextCursor(c)
        self.tabs.setCurrentIndex(0)

    def search_examples(self):
        q = self.ex_query.text().strip()
        if not q:
            a = self._cursor_article()
            q = a.title if a else ""
            self.ex_query.setText(q)
        if not q:
            return
        self.ex_list.clear()
        if self.ex_scope.currentIndex() == 0:
            if self.reg_corpus is None:
                QMessageBox.information(self, "조문 입법례", "[규정집 분석]에서 규정집을 먼저 불러오세요.")
                return
            for s, it in self.reg_corpus.similar(q * 2, top=40, min_score=0.12):
                li = QListWidgetItem(f"{it.reg.replace('안양도시공사 ', '')} {it.label} ({s:.2f})")
                li.setData(Qt.ItemDataRole.UserRole, it.text)
                self.ex_list.addItem(li)
        else:
            api = lawapi.LawAPI()
            if not api.ready:
                QMessageBox.information(self, "조문 입법례", "설정에서 법령 API OC 값을 입력하세요.")
                return
            self.status.showMessage("국가법령 본문 검색 중…")

            def work():
                hits = api.search(q, "law", 15, 1, True)
                out = []
                for h in hits[:8]:
                    d = api.fetch_doc(h)
                    for a in d.articles():
                        if q.replace(" ", "") in (a.title + a.plain()).replace(" ", ""):
                            out.append((f"{h.name} {a.heading()}", a.plain()))
                return out
            run_job(work, on_done=self._examples_done, on_fail=lambda e: self.status.showMessage("검색 실패: " + e.split("\n")[0], 8000))

    def _examples_done(self, out):
        for t, body in out[:60]:
            li = QListWidgetItem(t)
            li.setData(Qt.ItemDataRole.UserRole, body)
            self.ex_list.addItem(li)
        self.status.showMessage(f"입법례 {len(out)}건", 5000)

    def _show_related(self, a: Unit):
        parts = [f"<h3>{html.escape(a.heading())}</h3>"]
        # 이 조문이 인용하는 조문 / 이 조문을 인용하는 조문
        refs = extract_refs(self.revised)
        out_refs = [r for r in refs if self.revised.find_uid(r.src_uid) in list(a.iter())]
        in_refs = [r for r in refs if not r.target and r.article == a.num and r.article_branch == a.branch and
                   not any(self.revised.find_uid(r.src_uid) is x for x in a.iter())]
        if out_refs:
            parts.append("<b>이 조문이 인용</b><ul>")
            for r in out_refs:
                if r.target:
                    url = lawapi.law_url(r.target, r.label() if r.article else "")
                    parts.append(f"<li><a href='{url}'>「{html.escape(r.target)}」 {html.escape(r.text)}</a></li>")
                else:
                    parts.append(f"<li>{'같은 조 ' if r.relative else ''}{html.escape(r.text)}</li>")
            parts.append("</ul>")
        if in_refs:
            parts.append("<b>이 조문을 인용하는 조문</b><ul>" + "".join(f"<li>{html.escape(r.src_label)}: {html.escape(r.text)}</li>" for r in in_refs) + "</ul>")
        laws = law_names_cited(a.plain())
        if laws:
            parts.append("<b>관련 법령 (국가법령정보센터)</b><ul>" +
                         "".join(f"<li><a href='{lawapi.law_url(n)}'>{html.escape(n)}</a></li>" for n in laws) + "</ul>")
        guides = standards.load_guides()
        hit = [(k, u) for k, u in guides.items() if k and k in a.plain()]
        if hit:
            parts.append("<b>입안 심사기준</b><ul>" + "".join(f"<li><a href='{u}'>{html.escape(k)}</a></li>" for k, u in hit[:12]) + "</ul>")
        if self.reg_corpus is not None:
            names = {self.revised.name, self.current.name if self.current else ""} - {""}
            sims = [(sc, it) for sc, it in self.reg_corpus.similar(a.title * 3 + " " + a.plain(), top=8, min_score=0.25)
                    if not (it.reg in names and it.art.number_label() == a.number_label())][:6]    # 자기 자신은 빼고
            if sims:
                parts.append("<b>규정집의 비슷한 조문</b><ul>" + "".join(
                    f"<li>{html.escape(it.reg.replace('안양도시공사 ', ''))} {html.escape(it.label)} ({s:.2f})</li>" for s, it in sims) + "</ul>")
        self.related.setHtml("".join(parts))

    # ---- 별표/서식
    def _refresh_appendix_list(self):
        row = self.ap_list.currentRow()
        self.ap_list.blockSignals(True)
        self.ap_list.clear()
        for ap in self.revised.appendices:
            self.ap_list.addItem(f"{ap.label()} {ap.title}")
        self.ap_list.blockSignals(False)
        if 0 <= row < self.ap_list.count():
            self.ap_list.setCurrentRow(row)

    def _ap_select(self, row):
        if 0 <= row < len(self.revised.appendices):
            ap = self.revised.appendices[row]
            self.ap_title.setText(ap.title)
            self.ap_ref.setText(ap.ref)
            self.ap_text.setPlainText(ap.text)

    def _ap_add(self, kind):
        nums = [a.num for a in self.revised.appendices if a.kind == kind]
        self.revised.appendices.append(Appendix(kind=kind, num=(max(nums) + 1) if nums else 1, title="(제목)"))
        self.set_revised_doc(self.revised)
        self.ap_list.setCurrentRow(len(self.revised.appendices) - 1)

    def _ap_apply(self):
        r = self.ap_list.currentRow()
        if 0 <= r < len(self.revised.appendices):
            ap = self.revised.appendices[r]
            ap.title, ap.ref, ap.text = self.ap_title.text(), self.ap_ref.text(), self.ap_text.toPlainText()
            self.set_revised_doc(self.revised)

    def _ap_move(self, step):
        r = self.ap_list.currentRow()
        lst = self.revised.appendices
        if 0 <= r < len(lst) and 0 <= r + step < len(lst):
            lst[r], lst[r + step] = lst[r + step], lst[r]
            # 같은 종류끼리 번호 다시 매김
            for kind in ("별표", "별지", "서식"):
                k = 0
                for ap in lst:
                    if ap.kind == kind:
                        k += 1
                        ap.num, ap.branch = k, 0
            self.set_revised_doc(self.revised)
            self.ap_list.setCurrentRow(r + step)

    def _ap_delete(self):
        r = self.ap_list.currentRow()
        if 0 <= r < len(self.revised.appendices):
            del self.revised.appendices[r]
            self.set_revised_doc(self.revised)

    def _ap_clear(self):
        if self.revised.appendices and QMessageBox.question(self, "목록삭제", "별표·서식을 모두 지울까요?") == QMessageBox.StandardButton.Yes:
            self.revised.appendices = []
            self.set_revised_doc(self.revised)

    # ---- 용어관리
    def _term_load(self):
        rows = read_user_terms()
        self.term_table.setRowCount(len(rows))
        for r, (a, b, c) in enumerate(rows):
            for k, v in enumerate((a, b, c)):
                self.term_table.setItem(r, k, QTableWidgetItem(v))

    def _term_add(self, find="", repl=""):
        r = self.term_table.rowCount()
        self.term_table.insertRow(r)
        self.term_table.setItem(r, 0, QTableWidgetItem(find or ""))
        self.term_table.setItem(r, 1, QTableWidgetItem(repl or ""))
        self.term_table.setItem(r, 2, QTableWidgetItem(""))
        self.side.setCurrentIndex(4)
        self.term_table.editItem(self.term_table.item(r, 0 if not find else 1))

    def _term_del(self):
        r = self.term_table.currentRow()
        if r >= 0:
            self.term_table.removeRow(r)

    def _term_save(self):
        rows = []
        for r in range(self.term_table.rowCount()):
            g = lambda c: (self.term_table.item(r, c).text() if self.term_table.item(r, c) else "").strip()
            if g(0):
                rows.append((g(0), g(1), g(2)))
        write_user_terms(rows)
        self._load_dictionary_async()

    # ---- 타법개정
    def _others(self):
        if self.regbook is None:
            QMessageBox.information(self, "타법개정", "[규정집 분석]에서 규정집을 먼저 불러오세요.")
            return None
        return [e.doc for e in self.regbook.entries if e.doc is not None]

    def other_list(self):
        others = self._others()
        if others is None or (self.current is None and not self.revised.name):
            return
        base = self.current or self.revised
        hits = otherlaw.citing_list(base, others)
        rows = "".join(f"<tr><td>{html.escape(h.doc_name.replace('안양도시공사 ', ''))}</td><td>{html.escape(h.where)}</td>"
                       f"<td>{html.escape(h.reason)}</td></tr>" for h in hits)
        self.ol_view.setHtml(f"<b>「{html.escape(base.name)}」을(를) 인용하는 규정 {len(hits)}곳</b>"
                             f"<table border=1 cellspacing=0 cellpadding=3><tr><th>규정</th><th>조문</th><th>인용</th></tr>{rows}</table>")

    def other_amend(self):
        others = self._others()
        if others is None:
            return
        if self.current is None:
            QMessageBox.information(self, "타법개정", "현행이 있어야 합니다.")
            return
        terms = []
        for part in self.ol_terms.text().split(";"):
            if "=" in part:
                a, b = part.split("=", 1)
                if a.strip():
                    terms.append((a.strip(), b.strip()))
        ams = otherlaw.find_other_amendments(self.current, self._doc_from_editor(), others, terms)
        if not ams:
            self.ol_view.setHtml("함께 고칠 다른 규정이 없습니다.")
            self._ol_text = ""
            return
        n_add = len(re.findall(r"^제\d+조", self.ed_addenda.toPlainText(), re.M))
        self._ol_text = otherlaw.addenda_other_amend_text(ams, start_no=max(2, n_add + 1))
        hits = "".join(f"<li>{html.escape(a.doc.name)}: " + ", ".join(html.escape(h.where + ' ' + h.reason) for h in a.hits[:5]) + "</li>"
                       for a in ams)
        self.ol_view.setHtml(f"<b>함께 고칠 규정 {len(ams)}개</b><ul>{hits}</ul><hr><pre>{html.escape(self._ol_text)}</pre>")

    def _ol_to_addenda(self):
        if not self._ol_text:
            return
        cur = self.ed_addenda.toPlainText().strip()
        if cur and not re.match(r"^제1조", cur):
            cur = "제1조(시행일) " + cur
        self.set_addenda_text((cur + "\n" if cur else "") + self._ol_text)
        self.tabs.setCurrentIndex(3)

    def set_addenda_text(self, text: str):
        """부칙을 바꾸되 Ctrl+Z로 되돌릴 수 있게(한 단계)."""
        c = self.ed_addenda.textCursor()
        c.beginEditBlock()
        c.select(QTextCursor.SelectionType.Document)
        c.insertText(text)
        c.endEditBlock()

    # ================================================================ 규정집
    def open_regbook(self):
        from .regbook_window import RegBookWindow
        if self.reg_window is None:
            self.reg_window = RegBookWindow(self)
        self.reg_window.show()
        self.reg_window.raise_()
        self.reg_window.activateWindow()

    def set_regbook(self, rb, graph, corpus):
        self.regbook, self.reg_graph, self.reg_corpus = rb, graph, corpus

    def _reg_code_of(self, d: LawDoc) -> str:
        if self.regbook is None:
            return ""
        code = d.meta.get("code", "")
        if code and self.reg_graph and code in self.reg_graph.entries:
            return code
        e = self.regbook.by_name(d.name)
        return e.code if e else ""

    def impact_of_revision(self):
        if self.regbook is None:
            self.open_regbook()
            QMessageBox.information(self, "개정 영향분석", "규정집을 먼저 불러오세요.")
            return
        if self.current is None:
            QMessageBox.information(self, "개정 영향분석", "현행 규정을 불러와 개정안을 작성한 뒤 실행하세요.\n(규정집 창에서 [이 규정 개정하기]를 누르면 바로 시작됩니다.)")
            return
        code = self._reg_code_of(self.current)
        if not code:
            QMessageBox.information(self, "개정 영향분석", "현행 규정을 규정집에서 찾지 못했습니다.")
            return
        self.on_revised_changed()
        keys = set()
        olds, news = [], []
        for c in self.changes:
            u = c.old_unit if c.old_unit is not None else None
            m = re.match(r"제(\d+)조(?:의(\d+))?", c.art_path or c.path)
            if m:
                keys.add((int(m.group(1)), int(m.group(2) or 0)))
            if c.old_unit is not None:
                olds.append(c.old_unit.plain())
            if c.new_unit is not None:
                news.append(c.new_unit.plain())
        cur_keys = [k for k in keys if self.current.find_article(*k)]
        self.open_regbook()
        self.reg_window.run_impact(code, cur_keys, "\n".join(olds), "\n".join(news))

    def conflicts_of_revision(self):
        if self.regbook is None or self.current is None:
            self.impact_of_revision()
            return
        code = self._reg_code_of(self.current)
        if not code:
            return
        self.on_revised_changed()
        self.open_regbook()
        self.reg_window.run_conflicts_with_revision(code, self.revised)

    def load_from_regbook(self, entry):
        if not self.maybe_save():
            return
        self.project = fileio.Project()
        d = entry.doc.clone()
        d.meta["code"] = entry.code
        self._set_current(d)
        self.dirty = False
        self._update_title()
        self.raise_()
        self.activateWindow()

    # ================================================================ AI
    def ai_amend(self):
        from .ai_dialogs import AmendAIDialog
        AmendAIDialog(self).exec()

    def ai_new(self):
        from .ai_dialogs import NewAIDialog
        NewAIDialog(self).exec()

    def ai_settings(self):
        from .ai_dialogs import AISettingsDialog
        AISettingsDialog(self).exec()

    # ================================================================ 기타
    def open_settings(self):
        if SettingsDialog(self).exec():
            self.settings = lawapi.load_settings()
            if self.dictionary is not None:
                self._load_dictionary_async()

    def batch(self):
        BatchDialog(self, lambda: self.dictionary).exec()

    def about(self):
        QMessageBox.about(self, "정보", f"<b>{APP_TITLE}</b> (LawEdit) {__version__}<br><br>"
                          "법령안 작성·개정문·신구조문대비표·조문/용어 검사·입법예고문·관보게재문<br>"
                          "+ 규정집 상·하위 체계 / 개정 영향 분석 / 상충 검사<br><br>"
                          "법령 데이터: 국가법령정보 공동활용 Open API<br>"
                          "용어 사전: 법령안편집기가 설치돼 있으면 그 사전을 함께 사용")

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_fitted", False):
            self._fitted = True
            fit_to_screen(self, 1500)

    def closeEvent(self, e: QCloseEvent):
        if self.maybe_save():
            if self.reg_window is not None:
                self.reg_window.close()
            e.accept()
        else:
            e.ignore()
