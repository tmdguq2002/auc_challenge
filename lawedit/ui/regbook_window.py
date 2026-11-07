"""규정집 분석 창 — 상·하위 체계, 개정 영향 분석, 상충 검사, 상위법 대조."""
from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QTabWidget, QTextBrowser, QPushButton, QLabel, QFileDialog, QMessageBox, QListWidget,
                               QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox,
                               QLineEdit, QProgressBar, QCheckBox, QPlainTextEdit)

from ..core import lawapi
from ..core.render import render_doc, render_unit
from ..core.korean import josa
from ..regs.regbook import RegBook, build_regbook
from ..regs.analysis import (RegGraph, Corpus, analyze_impact, find_conflicts, check_external, regulation_summary,
                             compare_with_official, rank_of)
from .widgets import run_job, LawEditor, law_font, Card, fit_to_screen
from . import theme
from PySide6.QtWidgets import QFrame

SEV_COLOR = {"높음": "#b42318", "중간": "#b45309", "낮음": "#2459c7"}
DIR_COLOR = {"상위": "#9a3412", "하위": "#047857", "관련": "#2459c7", "외부법령": "#7c3aed"}


def _cache_path(pdf: str) -> Path:
    from lawedit.core.parser import PARSER_VERSION
    h = hashlib.sha1((str(Path(pdf).resolve()) + str(Path(pdf).stat().st_mtime) + f"v{PARSER_VERSION}").encode()).hexdigest()[:16]
    p = lawapi.settings_dir() / "regbooks"
    p.mkdir(exist_ok=True)
    return p / f"{h}.json"


def _load_or_build(pdf: str, progress=None):
    cp = _cache_path(pdf)
    if cp.exists():
        rb = RegBook.load(cp)
    else:
        rb = build_regbook(pdf, progress=progress)
        rb.save(cp)
    return rb, RegGraph(rb), Corpus(rb)


class RegBookWindow(QMainWindow):
    def __init__(self, main=None):
        # 부모 없는 독립 창 — 부모(소유) 창으로 두면 늘 메인 창 위에 떠서 메인 창을 앞으로 가져올 수 없다
        super().__init__(None)
        self.main = main
        if main is not None:
            self.setWindowIcon(main.windowIcon())
        self.setWindowTitle("규정집 분석")
        self.resize(1400, 860)
        self.rb: RegBook | None = None
        self.graph: RegGraph | None = None
        self.corpus: Corpus | None = None
        self.conflicts = []
        self.impacts = []
        self._build()
        last = QSettings("LawEdit", "LawEdit").value("regbook_pdf", "")
        if last and Path(last).exists():
            self.load_pdf(last)

    # ------------------------------------------------------------ UI
    def _build(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QFrame()
        head.setObjectName("AppHeader")
        head.setFixedHeight(52)
        top = QHBoxLayout(head)
        top.setContentsMargins(16, 0, 16, 0)
        logo = QLabel()
        logo.setPixmap(theme.icon("book-open-page-variant-outline", "white").pixmap(22, 22))
        ttl = QLabel("규정집 분석")
        ttl.setObjectName("AppTitle")
        top.addWidget(logo)
        top.addWidget(ttl)
        b_open = theme.primary(QPushButton(theme.icon("folder-open-outline", "white"), " 규정집 PDF 열기"))
        b_open.setStyleSheet("QPushButton{background:white;color:%s;border:0;font-weight:700}QPushButton:hover{background:#e8effc}" % theme.C["primary"])
        b_open.clicked.connect(self.pick_pdf)
        b_rebuild = QPushButton(theme.icon("refresh", "white"), " 다시 분석")
        b_rebuild.setStyleSheet("QPushButton{background:transparent;color:white;border:1px solid rgba(255,255,255,0.5)}"
                                "QPushButton:hover{background:rgba(255,255,255,0.15)}")
        b_rebuild.clicked.connect(self.rebuild)
        self.search = QLineEdit()
        self.search.setPlaceholderText("규정 찾기 (이름)")
        self.search.textChanged.connect(self._filter_tree)
        self.info = QLabel("규정집을 불러오세요.")
        self.info.setObjectName("AppDoc")
        self.search.setMinimumWidth(220)
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(220)
        self.bar.setVisible(False)
        for x in (b_open, b_rebuild, self.search):
            top.addWidget(x)
        top.addWidget(self.info, 1)
        top.addWidget(self.bar)
        v.addWidget(head)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(10, 10, 10, 10)
        v.addWidget(body, 1)
        sp = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["규정 체계", "코드"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._select)
        # 키보드·접근성 도구로 고른 경우에도 반응
        self.tree.itemSelectionChanged.connect(
            lambda: self.tree.selectedItems() and self.tree.selectedItems()[0] is not self.tree.currentItem()
            and self.tree.setCurrentItem(self.tree.selectedItems()[0]))
        self.tree.setIndentation(16)
        self.tree.setHeaderHidden(True)
        self.tree.setColumnWidth(1, 70)
        sp.addWidget(Card(self.tree, "규정 체계", "조례 › 정관 › 규정 › 내규", theme.C["primary"]))
        self.tabs = QTabWidget()
        self.tabs.setObjectName("DocTabs")
        self.tabs.addTab(self._build_view(), theme.icon("file-document-edit-outline"), "규정 보기")
        self.tabs.addTab(self._build_impact(), theme.icon("sitemap-outline"), "영향 분석")
        self.tabs.addTab(self._build_conflict(), theme.icon("alert-octagon-outline"), "상충 검사")
        self.tabs.addTab(self._build_external(), theme.icon("scale-balance"), "상위법 대조")
        sp.addWidget(self.tabs)
        sp.setSizes([380, 1020])
        bv.addWidget(sp, 1)
        self.setCentralWidget(w)

    def _build_view(self):
        w = QWidget()
        v = QVBoxLayout(w)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.summary = QTextBrowser()
        self.summary.setOpenLinks(False)
        self.summary.anchorClicked.connect(self._summary_link)
        self.text = LawEditor(read_only=True)
        self.summary.document().setDefaultStyleSheet(theme.HTML_CSS)
        sp.addWidget(Card(self.summary, "규정 개요", "", "#0f766e"))
        sp.addWidget(Card(self.text, "본문", "", theme.C["primary"]))
        sp.setSizes([260, 560])
        v.addWidget(sp, 1)
        row = QHBoxLayout()
        b = theme.primary(QPushButton(theme.icon("file-document-edit-outline", "white"), " 이 규정 개정하기"))
        b.clicked.connect(self.edit_current)
        b2 = QPushButton(theme.icon("web"), " 법령정보 현행본과 비교")
        b2.clicked.connect(self.compare_official)
        row.addWidget(b)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _build_impact(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("바꾸려는 조문을 고르고 [분석]을 누르면 함께 봐야 할 상위·하위·관련 규정 조문을 찾습니다.")
        hint.setObjectName("Hint")
        v.addWidget(hint)
        sp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.art_list = QListWidget()
        lv.addWidget(Card(self.art_list, "조문 선택", "", theme.C["primary"]), 1)
        self.change_text = QLineEdit()
        self.change_text.setPlaceholderText("바꿀 명칭·문구 (선택): 옛말=새말")
        lv.addWidget(self.change_text)
        row = QHBoxLayout()
        for t, fn in [("모두 선택", lambda: self._check_all(True)), ("선택 해제", lambda: self._check_all(False))]:
            b = QPushButton(t)
            b.clicked.connect(fn)
            row.addWidget(b)
        run = theme.primary(QPushButton(theme.icon("play-circle-outline", "white"), " 분석"))
        run.clicked.connect(self.impact_selected)
        row.addWidget(run)
        lv.addLayout(row)
        sp.addWidget(left)
        right = QSplitter(Qt.Orientation.Vertical)
        self.imp_table = QTableWidget(0, 5)
        self.imp_table.setHorizontalHeaderLabels(["구분", "규정", "조문", "사유", "점수"])
        self.imp_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.imp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.imp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.imp_table.currentCellChanged.connect(lambda r, *_: self._imp_detail(r))
        self.imp_table.cellDoubleClicked.connect(lambda r, c: self._goto(self.impacts[r].code, self.impacts[r].label))
        self.imp_detail = LawEditor(read_only=True)
        for t in (self.imp_table,):
            t.verticalHeader().setVisible(False)
            t.setAlternatingRowColors(True)
            t.setShowGrid(False)
        right.addWidget(Card(self.imp_table, "함께 검토할 조문", "", "#c2410c"))
        right.addWidget(Card(self.imp_detail, "조문 내용", "", "#64748b"))
        right.setSizes([480, 260])
        sp.addWidget(right)
        sp.setSizes([300, 900])
        v.addWidget(sp, 1)
        row2 = QHBoxLayout()
        self.imp_label = QLabel("")
        exp = QPushButton("보고서 저장(HTML)")
        exp.clicked.connect(self.export_impact)
        row2.addWidget(self.imp_label, 1)
        row2.addWidget(exp)
        v.addLayout(row2)
        return w

    def _build_conflict(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        b_all = theme.primary(QPushButton(theme.icon("alert-octagon-outline", "white"), " 전체 규정 상충 검사"))
        b_all.clicked.connect(lambda: self.run_conflicts(None))
        b_sel = QPushButton("선택 규정과 상·하위만")
        b_sel.clicked.connect(self.conflicts_selected)
        self.sev = QComboBox()
        self.sev.addItems(["모든 수준", "높음", "중간", "낮음"])
        self.kind = QComboBox()
        self.kind.addItem("모든 종류")
        for c in (self.sev, self.kind):
            c.currentTextChanged.connect(lambda *_: self._show_conflicts())
        for x in (b_all, b_sel, QLabel("수준"), self.sev, QLabel("종류"), self.kind):
            row.addWidget(x)
        row.addStretch(1)
        ai = QPushButton(theme.icon("robot-outline"), " 선택 건 AI 검토")
        ai.setToolTip("선택한 상충 의심 건을 AI가 읽고 실제 상충인지 판단합니다.")
        ai.clicked.connect(self.ai_review)
        row.addWidget(ai)
        exp = QPushButton("보고서 저장(HTML)")
        exp.clicked.connect(self.export_conflicts)
        row.addWidget(exp)
        v.addLayout(row)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.cf_table = QTableWidget(0, 6)
        self.cf_table.setHorizontalHeaderLabels(["수준", "종류", "규정(가)", "조문", "규정(나)", "내용"])
        self.cf_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.cf_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cf_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cf_table.currentCellChanged.connect(lambda r, *_: self._cf_detail(r))
        self.cf_table.verticalHeader().setVisible(False)
        self.cf_table.setAlternatingRowColors(True)
        self.cf_table.setShowGrid(False)
        sp.addWidget(Card(self.cf_table, "검사 결과", "", "#b42318"))
        det = QSplitter(Qt.Orientation.Horizontal)
        self.cf_a = LawEditor(read_only=True)
        self.cf_b = LawEditor(read_only=True)
        det.addWidget(Card(self.cf_a, "규정 (가)", "", theme.C["primary"]))
        det.addWidget(Card(self.cf_b, "규정 (나)", "", "#0f766e"))
        sp.addWidget(det)
        sp.setSizes([460, 300])
        v.addWidget(sp, 1)
        self.cf_label = QLabel("")
        v.addWidget(self.cf_label)
        return w

    def _build_external(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("규정이 인용한 국가 법령 조문을 국가법령정보 Open API로 가져와 조문 존재 여부·삭제 여부·수치를 대조합니다.\n"
                           "(설정에서 OC 값 필요, 인터넷 연결 필요)"))
        row = QHBoxLayout()
        b1 = theme.primary(QPushButton(theme.icon("scale-balance", "white"), " 선택 규정 상위법 대조"))
        b1.clicked.connect(lambda: self.run_external(True))
        b2 = QPushButton("전체 규정 상위법 대조 (오래 걸림)")
        b2.clicked.connect(lambda: self.run_external(False))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)
        self.laws_view = QTextBrowser()
        self.laws_view.setOpenExternalLinks(True)
        self.laws_view.document().setDefaultStyleSheet(theme.HTML_CSS)
        v.addWidget(Card(self.laws_view, "인용 법령", "", "#7c3aed"), 1)
        return w

    # ------------------------------------------------------------ 불러오기
    def pick_pdf(self):
        p, _ = QFileDialog.getOpenFileName(self, "규정집 PDF", str(Path.home() / "Documents"), "PDF (*.pdf);;분석 파일 (*.json)")
        if p:
            self.load_pdf(p)

    def rebuild(self):
        last = QSettings("LawEdit", "LawEdit").value("regbook_pdf", "")
        if last and Path(last).exists():
            try:
                _cache_path(last).unlink(missing_ok=True)
            except OSError:
                pass
            self.load_pdf(last)

    def load_pdf(self, path: str):
        self.info.setText(f"분석 중… {Path(path).name}")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        QSettings("LawEdit", "LawEdit").setValue("regbook_pdf", path)

        def work(progress=None):
            if path.lower().endswith(".json"):
                rb = RegBook.load(path)
                return rb, RegGraph(rb), Corpus(rb)
            return _load_or_build(path, progress)
        run_job(work, on_done=self._loaded, on_fail=self._fail,
                on_progress=lambda i, n: (self.bar.setRange(0, n), self.bar.setValue(i)))

    def _fail(self, e):
        self.bar.setVisible(False)
        self.info.setText("실패")
        QMessageBox.critical(self, "규정집 분석", e[:2000])

    def _loaded(self, res):
        self.rb, self.graph, self.corpus = res
        self.bar.setVisible(False)
        n_art = len(self.corpus.items)
        self.info.setText(f"{self.rb.title or '규정집'} — 규정 {len(self.rb.entries)}개, 조문 {n_art:,}개, 인용 {len(self.graph.links):,}건")
        if self.main is not None:
            self.main.set_regbook(self.rb, self.graph, self.corpus)
        self._fill_tree()
        kinds = sorted({"인용 오류", "폐지 규정 인용", "상위 개정 미반영", "수치 불일치", "명칭 불일치", "상위법 인용 오류",
                        "상위법 수치 확인", "상위법 확인"})
        self.kind.clear()
        self.kind.addItem("모든 종류")
        self.kind.addItems(kinds)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_fitted", False):
            self._fitted = True
            fit_to_screen(self, 1400)

    def _fill_tree(self):
        self.tree.clear()
        stack: list[QTreeWidgetItem] = []
        for depth, code in self.graph.tree():
            e = self.graph.entries[code]
            it = QTreeWidgetItem([e.name.replace("안양도시공사 ", ""), code])
            it.setData(0, Qt.ItemDataRole.UserRole, code)
            if e.repealed:
                it.setForeground(0, QBrush(QColor("#999")))
                it.setText(0, it.text(0) + " (폐지)")
            stack = stack[:depth]
            (stack[-1].addChild(it) if stack else self.tree.addTopLevelItem(it))
            stack.append(it)
        self.tree.expandAll()

    def _filter_tree(self, q):
        q = q.strip()

        def walk(it):
            vis = not q or q in it.text(0)
            for i in range(it.childCount()):
                vis = walk(it.child(i)) or vis
            it.setHidden(not vis)
            return vis
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    # ------------------------------------------------------------ 규정 보기
    def current_code(self) -> str:
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else ""

    def _select(self, it, _=None):
        if not it or self.graph is None:
            return
        code = it.data(0, Qt.ItemDataRole.UserRole)
        e = self.graph.entries[code]
        s = regulation_summary(self.graph, code)
        lk = lambda c, n: f"<a href='reg:{c}'>{html.escape(n.replace('안양도시공사 ', ''))}</a>"
        parts = [f"<h3>{html.escape(e.name)} <small>({code}, {e.dept}, 규정집 {e.page}쪽)</small></h3>"]
        if s["history"]:
            parts.append(f"<div style='color:#555'>{html.escape(s['history'][0])} … {html.escape(s['history'][-1])} (연혁 {len(s['history'])}건)</div>")
        parts.append("<table cellpadding=3>")
        for title, items in [("상위", s["upper"]), ("하위", s["lower"]), ("인용하는 규정", s["cites"]), ("인용받는 규정", s["cited_by"])]:
            parts.append(f"<tr><td valign=top><b>{title}</b></td><td>{', '.join(lk(c, n) for c, n in items) or '-'}</td></tr>")
        laws = ", ".join(f"<a href='{lawapi.law_url(n)}'>{html.escape(n)}</a>" for n in s["laws"])
        parts.append(f"<tr><td valign=top><b>상위 법령</b></td><td>{laws or '-'}</td></tr></table>")
        self.summary.setHtml("".join(parts))
        self.text.setPlainText(render_doc(e.doc))
        self.art_list.clear()
        for a in e.doc.articles():
            li = QListWidgetItem(a.heading() + (" 삭제" if a.deleted else ""))
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(Qt.CheckState.Unchecked)
            li.setData(Qt.ItemDataRole.UserRole, (a.num, a.branch))
            self.art_list.addItem(li)

    def _summary_link(self, url):
        s = url.toString()
        if s.startswith("reg:"):
            self.select_code(s[4:])
        else:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)

    def select_code(self, code: str):
        def walk(it):
            if it.data(0, Qt.ItemDataRole.UserRole) == code:
                return it
            for i in range(it.childCount()):
                r = walk(it.child(i))
                if r:
                    return r
            return None
        for i in range(self.tree.topLevelItemCount()):
            r = walk(self.tree.topLevelItem(i))
            if r:
                self.tree.setCurrentItem(r)
                return True
        return False

    def _goto(self, code: str, label: str):
        if not code:
            return
        self.select_code(code)
        self.tabs.setCurrentIndex(0)
        import re
        m = re.match(r"^(제\d+조(?:의\d+)?)", label or "")
        if m:
            ln = self.text.find_unit_line(m.group(1))
            if ln >= 0:
                self.text.goto_line(ln)

    def edit_current(self):
        code = self.current_code()
        if code and self.main is not None:
            self.main.load_from_regbook(self.graph.entries[code])

    def compare_official(self):
        code = self.current_code()
        if not code:
            return
        api = lawapi.LawAPI()
        if not api.ready:
            QMessageBox.information(self, "비교", "설정에서 법령 API OC 값을 입력하세요.")
            return
        e = self.graph.entries[code]
        self.info.setText("법령정보 현행본 가져오는 중…")

        def done(res):
            off, ch = res
            if off is None:
                QMessageBox.information(self, "비교", f"「{e.name}」{josa(e.name, '을/를')} 국가법령정보에서 찾지 못했습니다(공사 내부 규정은 공개 대상이 아닐 수 있습니다).")
                return
            lines = [f"「{e.name}」 규정집 수록본 ↔ 국가법령정보 현행본({off.meta.get('effective', '')} 시행)", ""]
            lines += [c.describe() for c in ch] or ["차이가 없습니다."]
            from .dialogs import DocPreviewDialog
            DocPreviewDialog("현행본 비교", "\n".join(lines), self).exec()
            self.info.setText(f"현행본 비교: 차이 {len(ch)}건")
        run_job(compare_with_official, e, api, on_done=done, on_fail=self._fail)

    # ------------------------------------------------------------ 영향 분석
    def _check_all(self, on: bool):
        for i in range(self.art_list.count()):
            self.art_list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def impact_selected(self):
        code = self.current_code()
        if not code:
            return
        keys = [self.art_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.art_list.count())
                if self.art_list.item(i).checkState() == Qt.CheckState.Checked]
        if not keys:
            QMessageBox.information(self, "영향 분석", "바꾸려는 조문을 하나 이상 체크하세요.")
            return
        old = new = ""
        t = self.change_text.text()
        if "=" in t:
            old, new = [x.strip() for x in t.split("=", 1)]
        self.run_impact(code, keys, old, new)

    def run_impact(self, code: str, keys, old_text: str = "", new_text: str = ""):
        if self.graph is None:
            return
        self.select_code(code)
        for i in range(self.art_list.count()):
            it = self.art_list.item(i)
            it.setCheckState(Qt.CheckState.Checked if tuple(it.data(Qt.ItemDataRole.UserRole)) in {tuple(k) for k in keys}
                             else Qt.CheckState.Unchecked)
        self.tabs.setCurrentIndex(1)
        self.imp_label.setText("분석 중…")
        run_job(analyze_impact, self.rb, self.graph, self.corpus, code, [tuple(k) for k in keys], old_text, new_text,
                on_done=self._show_impact, on_fail=self._fail)

    def _show_impact(self, res):
        self.impacts = res
        self.imp_table.setRowCount(len(res))
        for r, x in enumerate(res):
            vals = [x.direction, x.reg.replace("안양도시공사 ", ""), x.label, x.reason, f"{x.score:.2f}"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setForeground(QBrush(QColor(DIR_COLOR.get(x.direction, "#000"))))
                    it.setText("● " + v)
                self.imp_table.setItem(r, c, it)
        self.imp_table.resizeColumnsToContents()
        self.imp_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        cnt = {}
        for x in res:
            cnt[x.direction] = cnt.get(x.direction, 0) + 1
        self.imp_label.setText(f"함께 검토할 조문 {len(res)}건 — " + ", ".join(f"{k} {v}" for k, v in cnt.items()))

    def _imp_detail(self, r):
        if not (0 <= r < len(self.impacts)):
            return
        x = self.impacts[r]
        text = x.snippet
        if x.code:
            e = self.graph.entries.get(x.code)
            import re
            m = re.match(r"^제(\d+)조(?:의(\d+))?", x.label or "")
            if e and m:
                a = e.doc.find_article(int(m.group(1)), int(m.group(2) or 0))
                if a:
                    text = "\n".join(render_unit(a))
        self.imp_detail.setPlainText(f"[{x.direction}] {x.reg} {x.label}\n사유: {x.reason}\n\n{text}")

    def export_impact(self):
        if not self.impacts:
            return
        rows = "".join(f"<tr><td>{x.direction}</td><td>{html.escape(x.reg)}</td><td>{html.escape(x.label)}</td>"
                       f"<td>{html.escape(x.reason)}</td><td>{html.escape(x.snippet)}</td></tr>" for x in self.impacts)
        self._save_html("영향분석", f"<h2>개정 영향 분석</h2><p>{html.escape(self.imp_label.text())}</p>"
                                    f"<table><tr><th>구분</th><th>규정</th><th>조문</th><th>사유</th><th>내용</th></tr>{rows}</table>")

    # ------------------------------------------------------------ 상충 검사
    def conflicts_selected(self):
        code = self.current_code()
        if code:
            codes = [code] + self.graph.ancestors(code) + self.graph.descendants(code)
            self.run_conflicts(codes)

    def run_conflicts(self, codes):
        if self.graph is None:
            return
        self.tabs.setCurrentIndex(2)
        self.cf_label.setText("검사 중…")
        self.bar.setVisible(True)
        run_job(find_conflicts, self.rb, self.graph, self.corpus, codes, on_done=self._conf_done, on_fail=self._fail,
                on_progress=lambda i, n: (self.bar.setRange(0, n), self.bar.setValue(i)))

    def run_conflicts_with_revision(self, code: str, revised):
        """편집 중인 개정안을 규정집에 넣었다고 보고 상충 검사."""
        if self.rb is None:
            return
        rb2 = RegBook.from_json(self.rb.to_json())
        e = rb2.by_code(code)
        d = revised.clone()
        d.meta["code"] = code
        e.doc = d
        self.tabs.setCurrentIndex(2)
        self.cf_label.setText("개정안 기준으로 검사 중…")

        def work(progress=None):
            g, c = RegGraph(rb2), Corpus(rb2)
            codes = [code] + g.ancestors(code) + g.descendants(code)
            res = find_conflicts(rb2, g, c, codes, progress=progress)
            return [x for x in res if code in (x.a_code, x.b_code)]
        run_job(work, on_done=self._conf_done, on_fail=self._fail)

    def _conf_done(self, res):
        self.bar.setVisible(False)
        self.conflicts = res
        self._show_conflicts()

    def _show_conflicts(self):
        sev, kind = self.sev.currentText(), self.kind.currentText()
        shown = [x for x in self.conflicts if (sev == "모든 수준" or x.severity == sev) and (kind == "모든 종류" or x.kind == kind)]
        self._shown_cf = shown
        self.cf_table.setRowCount(len(shown))
        for r, x in enumerate(shown):
            vals = [x.severity, x.kind, x.a_reg.replace("안양도시공사 ", ""), x.a_label,
                    (x.b_reg.replace("안양도시공사 ", "") + " " + x.b_label).strip(), x.detail]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setForeground(QBrush(QColor(SEV_COLOR.get(x.severity, "#000"))))
                    it.setText("● " + v)
                self.cf_table.setItem(r, c, it)
        self.cf_table.resizeColumnsToContents()
        self.cf_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        cnt = {}
        for x in self.conflicts:
            cnt[x.severity] = cnt.get(x.severity, 0) + 1
        self.cf_label.setText(f"전체 {len(self.conflicts)}건 (" + ", ".join(f"{k} {v}" for k, v in cnt.items()) + f") / 표시 {len(shown)}건")

    def _cf_detail(self, r):
        shown = getattr(self, "_shown_cf", [])
        if not (0 <= r < len(shown)):
            return
        x = shown[r]
        a_text = x.a_text
        if x.a_code and self.graph and x.a_code in self.graph.entries:
            import re
            m = re.match(r"^제(\d+)조(?:의(\d+))?", x.a_label or "")
            a = self.graph.entries[x.a_code].doc.find_article(int(m.group(1)), int(m.group(2) or 0)) if m else None
            if a:
                a_text = "\n".join(render_unit(a))
        self.cf_a.setPlainText(f"{x.a_reg} {x.a_label}\n\n{a_text}")
        self.cf_b.setPlainText(f"{x.b_reg} {x.b_label}\n\n{x.b_text}\n\n▶ {x.detail}")

    def ai_review(self):
        from ..ai.llm import LLMConfig
        from ..ai import agent
        shown = getattr(self, "_shown_cf", [])
        r = self.cf_table.currentRow()
        if not (0 <= r < len(shown)):
            QMessageBox.information(self, "AI 검토", "검토할 행을 선택하세요.")
            return
        cfg = LLMConfig.load()
        if not cfg.ready:
            from .ai_dialogs import AISettingsDialog
            AISettingsDialog(self).exec()
            cfg = LLMConfig.load()
            if not cfg.ready:
                return
        x = shown[r]
        a_text = self.cf_a.toPlainText()
        b_text = x.b_text or self.cf_b.toPlainText()
        self.cf_label.setText("AI 검토 중…")

        def done(d):
            verdict = d.get("verdict", "?")
            self.cf_b.setPlainText(self.cf_b.toPlainText() + f"\n\n🤖 AI 검토({d.get('model', '')}): {verdict}\n"
                                   f"근거: {d.get('reason', '')}\n" + (f"고칠 방향: {d.get('fix', '')}" if d.get("fix") else ""))
            it = self.cf_table.item(r, 5)
            if it:
                it.setText(f"[AI: {verdict}] " + x.detail)
            self.cf_label.setText(f"AI 검토 결과: {verdict}")
        run_job(agent.review_conflict, cfg, f"{x.a_reg} {x.a_label}", a_text, f"{x.b_reg} {x.b_label}", b_text, x.detail,
                on_done=done, on_fail=lambda e: (self.cf_label.setText("AI 검토 실패"), QMessageBox.warning(self, "AI 검토", e.split("\n")[0])))

    def export_conflicts(self):
        if not self.conflicts:
            return
        rows = "".join(f"<tr><td>{x.severity}</td><td>{x.kind}</td><td>{html.escape(x.a_reg)} {html.escape(x.a_label)}</td>"
                       f"<td>{html.escape(x.b_reg)} {html.escape(x.b_label)}</td><td>{html.escape(x.detail)}</td></tr>"
                       for x in self.conflicts)
        self._save_html("상충검사", f"<h2>규정 상충 검사</h2><p>{html.escape(self.cf_label.text())}</p>"
                                    f"<table><tr><th>수준</th><th>종류</th><th>규정(가)</th><th>규정(나)</th><th>내용</th></tr>{rows}</table>")

    # ------------------------------------------------------------ 상위법
    def run_external(self, selected_only: bool):
        if self.graph is None:
            return
        api = lawapi.LawAPI()
        if not api.ready:
            QMessageBox.information(self, "상위법 대조", "설정에서 법령 API OC 값을 입력하세요.")
            return
        codes = None
        if selected_only:
            code = self.current_code()
            if not code:
                return
            codes = [code]
        self.laws_view.setHtml("법령을 가져와 대조하는 중… (처음에는 시간이 걸립니다)")
        self.bar.setVisible(True)

        def done(res):
            self.bar.setVisible(False)
            self.conflicts = res + [x for x in self.conflicts if not x.kind.startswith("상위법")]
            self._show_conflicts()
            laws = {}
            for l in self.graph.links:
                if l.external and (codes is None or l.src_code in codes):
                    laws[l.dst_name] = laws.get(l.dst_name, 0) + 1
            items = "".join(f"<li><a href='{lawapi.law_url(n)}'>{html.escape(n)}</a> — 인용 {c}회</li>"
                            for n, c in sorted(laws.items(), key=lambda x: -x[1]))
            self.laws_view.setHtml(f"<b>상위법 대조 결과 {len(res)}건</b> → [상충 검사] 탭에서 '상위법' 종류로 확인하세요.<br>"
                                   f"<b>인용된 법령</b><ul>{items}</ul>")
        run_job(check_external, self.rb, self.graph, api, codes, on_done=done, on_fail=self._fail,
                on_progress=lambda i, n: (self.bar.setRange(0, n), self.bar.setValue(i)))

    def _save_html(self, name, body):
        from ..core.fileio import wrap_html
        p, _ = QFileDialog.getSaveFileName(self, "보고서 저장", str(Path.home() / "Documents" / f"{name}.html"), "HTML (*.html)")
        if p:
            Path(p).write_text(wrap_html(body, name), encoding="utf-8")
            QMessageBox.information(self, "저장", p)
