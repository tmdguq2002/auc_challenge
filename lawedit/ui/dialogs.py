"""대화상자."""
from __future__ import annotations

import html
import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextDocument, QPageSize, QPageLayout, QTextCursor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
                               QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                               QSpinBox, QTextBrowser, QFileDialog, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QGroupBox, QAbstractItemView, QProgressBar, QTextEdit, QWidget)

from ..core.model import LAW_TYPES, AMEND_TYPES, LawDoc
from ..core import lawapi
from .widgets import run_job, law_font, LawEditor


class NewDocDialog(QDialog):
    def __init__(self, parent=None, name="", law_type="규정", amend_type="일부개정", org=""):
        super().__init__(parent)
        self.setWindowTitle("법령안 정보")
        f = QFormLayout(self)
        self.name = QLineEdit(name)
        self.law_type = QComboBox()
        self.law_type.addItems(LAW_TYPES)
        self.law_type.setCurrentText(law_type)
        self.amend_type = QComboBox()
        self.amend_type.addItems(AMEND_TYPES)
        self.amend_type.setCurrentText(amend_type)
        self.org = QLineEdit(org)
        f.addRow("법령(규정)명", self.name)
        f.addRow("종류", self.law_type)
        f.addRow("제ㆍ개정 구분", self.amend_type)
        f.addRow("소관 부서", self.org)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        return self.name.text().strip(), self.law_type.currentText(), self.amend_type.currentText(), self.org.text().strip()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(560, 360)
        s = lawapi.load_settings()
        f = QFormLayout(self)
        self.oc = QLineEdit(s.get("oc", ""))
        self.oc.setPlaceholderText("open.law.go.kr 에서 신청한 OC(이메일 아이디)")
        f.addRow("법령 API OC", self.oc)
        help_ = QLabel('<a href="https://open.law.go.kr/LSO/openApi/guideList.do">국가법령정보 공동활용 OPEN API 신청 안내</a>')
        help_.setOpenExternalLinks(True)
        f.addRow("", help_)
        self.conf = QLineEdit(s.get("conf_dir", ""))
        self.conf.setPlaceholderText(r"비우면 자동: C:\Program Files (x86)\LawEditor3.1\Conf")
        b = QPushButton("찾기…")
        b.clicked.connect(self._pick_conf)
        row = QHBoxLayout()
        row.addWidget(self.conf)
        row.addWidget(b)
        f.addRow("원본 사전 폴더", row)
        self.org = QLineEdit(s.get("org", "안양도시공사"))
        f.addRow("기관명", self.org)
        self.dept = QLineEdit(s.get("dept", ""))
        f.addRow("담당 부서", self.dept)
        self.contact = QLineEdit(s.get("contact", ""))
        f.addRow("연락처", self.contact)
        self.easy = QCheckBox("용어 검사에 '알기 쉬운 법령 용어'(동음이의어 오검출 많음) 포함")
        self.easy.setChecked(bool(s.get("easy_terms", False)))
        f.addRow("", self.easy)
        self.mark = QCheckBox("일부개정 시 삭제 조문은 '삭제'로 남기기(번호 유지)")
        self.mark.setChecked(bool(s.get("delete_mark", True)))
        f.addRow("", self.mark)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _pick_conf(self):
        d = QFileDialog.getExistingDirectory(self, "법령안편집기 Conf 폴더")
        if d:
            self.conf.setText(d)

    def _save(self):
        s = lawapi.load_settings()
        s.update(oc=self.oc.text().strip(), conf_dir=self.conf.text().strip(), org=self.org.text().strip(),
                 dept=self.dept.text().strip(), contact=self.contact.text().strip(), easy_terms=self.easy.isChecked(),
                 delete_mark=self.mark.isChecked())
        lawapi.save_settings(s)
        self.accept()


class LawSearchDialog(QDialog):
    """법령검색 — 국가법령정보 API."""
    open_doc = Signal(object, str)      # (LawDoc, mode: current/view)

    def __init__(self, parent=None, query=""):
        super().__init__(parent)
        self.setWindowTitle("법령검색 (국가법령정보센터)")
        self.resize(980, 640)
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.q = QLineEdit(query)
        self.q.setPlaceholderText("법령명 또는 본문 검색어")
        self.target = QComboBox()
        for k, n in lawapi.TARGETS.items():
            self.target.addItem(n, k)
        self.body = QCheckBox("본문 검색")
        from . import theme
        b = theme.primary(QPushButton("검색"))
        b.setDefault(True)
        b.clicked.connect(self.search)
        self.q.returnPressed.connect(self.search)
        for w in (QLabel("검색어"), self.q, self.target, self.body, b):
            row.addWidget(w)
        v.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["법령명", "종류", "소관", "공포일", "시행일", "제개정"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.preview)
        v.addWidget(self.table, 2)
        self.view = QTextBrowser()
        self.view.setFont(law_font(10))
        v.addWidget(self.view, 3)
        row2 = QHBoxLayout()
        self.status = QLabel("")
        row2.addWidget(self.status, 1)
        for text, mode in [("현행으로 불러오기(개정안 작성)", "current"), ("새 창으로 보기", "view")]:
            bb = QPushButton(text)
            bb.clicked.connect(lambda _=False, m=mode: self._emit(m))
            row2.addWidget(bb)
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        row2.addWidget(close)
        v.addLayout(row2)
        self.api = lawapi.LawAPI()
        self.hits = []
        self.docs = {}
        if query:
            self.search()

    def search(self):
        q = self.q.text().strip()
        if not q:
            return
        if not self.api.ready:
            QMessageBox.information(self, "법령검색", "설정에서 법령 API OC 값을 먼저 입력하세요.")
            return
        self.status.setText("검색 중…")
        run_job(self.api.search, q, self.target.currentData(), 50, 1, self.body.isChecked(),
                on_done=self._show, on_fail=lambda e: self.status.setText("오류: " + e.split("\n")[0]))

    def _show(self, hits):
        self.hits = hits
        self.table.setRowCount(len(hits))
        for r, h in enumerate(hits):
            for c, v in enumerate([h.name, h.kind, h.ministry, h.promulgated, h.effective, h.amend]):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.status.setText(f"{len(hits)}건")

    def _cur(self):
        r = self.table.currentRow()
        return self.hits[r] if 0 <= r < len(self.hits) else None

    def preview(self):
        h = self._cur()
        if not h:
            return
        if h.mst in self.docs:
            self._render(self.docs[h.mst])
            return
        self.status.setText("본문 가져오는 중…")
        run_job(self.api.fetch_doc, h, on_done=lambda d, k=h.mst: (self.docs.__setitem__(k, d), self._render(d)),
                on_fail=lambda e: self.status.setText("오류: " + e.split("\n")[0]))

    def _render(self, d: LawDoc):
        from ..core.render import render_doc
        self.view.setPlainText(render_doc(d))
        self.status.setText(f"{d.name} — 조문 {len(d.articles())}개")

    def _emit(self, mode):
        h = self._cur()
        if h and h.mst in self.docs:
            self.open_doc.emit(self.docs[h.mst], mode)
            if mode == "current":
                self.accept()


class FindReplaceDialog(QDialog):
    def __init__(self, editor_getter, parent=None):
        super().__init__(parent)
        self.setWindowTitle("찾기 / 바꾸기")
        self.get_editor = editor_getter
        f = QFormLayout(self)
        self.find = QLineEdit()
        self.repl = QLineEdit()
        self.regex = QCheckBox("정규식")
        f.addRow("찾을 내용", self.find)
        f.addRow("바꿀 내용", self.repl)
        f.addRow("", self.regex)
        row = QHBoxLayout()
        for t, fn in [("다음 찾기", self.find_next), ("바꾸기", self.replace_one), ("모두 바꾸기", self.replace_all)]:
            b = QPushButton(t)
            b.clicked.connect(fn)
            row.addWidget(b)
        f.addRow(row)
        self.msg = QLabel("")
        f.addRow(self.msg)

    def find_next(self):
        ed = self.get_editor()
        if ed is None:
            return False
        if self.regex.isChecked():
            from PySide6.QtCore import QRegularExpression
            ok = ed.find(QRegularExpression(self.find.text()))
        else:
            ok = ed.find(self.find.text())
        if not ok:
            c = ed.textCursor()
            c.movePosition(QTextCursor.MoveOperation.Start)
            ed.setTextCursor(c)
            ok = ed.find(self.find.text()) if not self.regex.isChecked() else False
        self.msg.setText("" if ok else "찾지 못했습니다.")
        return ok

    def replace_one(self):
        ed = self.get_editor()
        if ed is None or ed.isReadOnly():
            return
        c = ed.textCursor()
        if c.hasSelection():
            c.insertText(self.repl.text())
        self.find_next()

    def replace_all(self):
        ed = self.get_editor()
        if ed is None or ed.isReadOnly():
            return
        t = ed.toPlainText()
        if self.regex.isChecked():
            new, n = re.subn(self.find.text(), self.repl.text(), t)
        else:
            n = t.count(self.find.text())
            new = t.replace(self.find.text(), self.repl.text())
        if n:
            c = ed.textCursor()
            c.select(QTextCursor.SelectionType.Document)
            c.insertText(new)
        self.msg.setText(f"{n}곳 바꿈")


class ArticlePicker(QDialog):
    """조문 선택 (조문이동·맞교환 대상)."""

    def __init__(self, doc: LawDoc, title: str, label: str, parent=None, allow_top=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 500)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(label))
        self.list = QListWidget()
        if allow_top:
            it = QListWidgetItem("(맨 앞)")
            it.setData(Qt.ItemDataRole.UserRole, None)
            self.list.addItem(it)
        for a in doc.articles():
            it = QListWidgetItem(a.heading() + (" 삭제" if a.deleted else ""))
            it.setData(Qt.ItemDataRole.UserRole, a.uid)
            self.list.addItem(it)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        v.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def chosen(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else "__none__"


def export_text_or_html(parent, title: str, text: str = "", html_body: str = "", kind: str = "text",
                        compare_rows=None, default_name: str = ""):
    """TXT/HTML/HWPX/HWP/PDF 로 내보내기."""
    from ..core import fileio
    filters = "한글 문서 (*.hwpx);;한글 97-2024 (*.hwp);;PDF (*.pdf);;웹 문서 (*.html);;텍스트 (*.txt)"
    path, flt = QFileDialog.getSaveFileName(parent, f"{title} 내보내기", default_name or title, filters)
    if not path:
        return
    ext = Path(path).suffix.lower()
    if not ext:
        ext = {"한글 문서": ".hwpx", "한글 97": ".hwp", "PDF": ".pdf", "웹 문서": ".html", "텍스트": ".txt"}[
            next(k for k in ["한글 문서", "한글 97", "PDF", "웹 문서", "텍스트"] if flt.startswith(k))]
        path += ext
    try:
        if ext == ".txt":
            Path(path).write_text(text or re.sub(r"<[^>]+>", "", html_body), encoding="utf-8")
        elif ext in (".html", ".htm"):
            Path(path).write_text(fileio.wrap_html(html_body, title) if html_body else fileio.text_to_html(text, title),
                                  encoding="utf-8")
        elif ext in (".hwpx", ".hwp"):
            target = path if ext == ".hwpx" else str(Path(path).with_suffix(".tmp.hwpx"))
            if compare_rows is not None:
                fileio.compare_table_to_hwpx(compare_rows, target, title)
            else:
                fileio.text_to_hwpx(text, target, title=title, title_lines=1 if kind == "doc" else 0)
            if ext == ".hwp":
                if not fileio.hancom_convert(target, path, "HWP"):
                    QMessageBox.warning(parent, "내보내기", "한글(HWP) 변환에는 한컴오피스 한글이 필요합니다. HWPX로 저장했습니다.")
                    os.replace(target, str(Path(path).with_suffix(".hwpx")))
                    return
                os.remove(target)
        elif ext == ".pdf":
            from PySide6.QtGui import QPdfWriter
            doc = QTextDocument()
            doc.setDefaultFont(law_font(10))
            if html_body:
                doc.setHtml(fileio.wrap_html(html_body, title))
            else:
                doc.setHtml(fileio.text_to_html(text, title))
            w = QPdfWriter(path)
            w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            w.setPageMargins(__import__("PySide6.QtCore", fromlist=["QMarginsF"]).QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter)
            doc.print_(w)
        QMessageBox.information(parent, "내보내기", f"저장했습니다.\n{path}")
    except Exception as e:      # noqa: BLE001
        QMessageBox.critical(parent, "내보내기 실패", str(e))


class DocPreviewDialog(QDialog):
    """생성 문서(입법예고문·관보게재문 등) 미리보기·편집·내보내기."""

    def __init__(self, title: str, text: str, parent=None, apply_label: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 760)
        v = QVBoxLayout(self)
        self.ed = LawEditor()
        self.ed.setPlainText(text)
        v.addWidget(self.ed)
        row = QHBoxLayout()
        row.addStretch(1)
        from . import theme
        if apply_label:              # 입력용: [적용] [취소]
            self.ed.setReadOnly(False)
            b = theme.primary(QPushButton(theme.icon("check-circle-outline", "white"), " " + apply_label))
            b.clicked.connect(self.accept)
            row.addWidget(b)
            x = QPushButton("취소")
            x.clicked.connect(self.reject)
            row.addWidget(x)
            v.addLayout(row)
            return
        b = theme.primary(QPushButton(theme.icon("file-export-outline", "white"), " 내보내기"))
        b.clicked.connect(lambda: export_text_or_html(self, title, self.ed.toPlainText(), kind="doc"))
        row.addWidget(b)
        c = QPushButton("복사")
        c.clicked.connect(lambda: (self.ed.selectAll(), self.ed.copy()))
        row.addWidget(c)
        x = QPushButton("닫기")
        x.clicked.connect(self.accept)
        row.addWidget(x)
        v.addLayout(row)


class NoticeOptionsDialog(QDialog):
    def __init__(self, parent=None, kind="입법예고문", defaults: dict | None = None):
        super().__init__(parent)
        d = defaults or {}
        self.setWindowTitle(f"{kind} 작성")
        f = QFormLayout(self)
        self.no = QLineEdit(d.get("no", ""))
        self.org = QLineEdit(d.get("org", ""))
        self.contact = QLineEdit(d.get("contact", ""))
        self.days = QSpinBox()
        self.days.setRange(1, 90)
        self.days.setValue(d.get("days", 10))
        self.reason = QPlainTextEdit(d.get("reason", ""))
        self.reason.setFixedHeight(80)
        self.points = QPlainTextEdit("\n".join(d.get("points", [])))
        self.points.setFixedHeight(140)
        f.addRow("공고(공포)번호", self.no)
        if kind == "입법예고문":
            f.addRow("의견 제출처(부서)", self.org)
            f.addRow("연락처", self.contact)
            f.addRow("예고 기간(일)", self.days)
        f.addRow("제ㆍ개정 이유", self.reason)
        f.addRow("주요내용(줄마다 한 항목)", self.points)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self) -> dict:
        return {"no": self.no.text().strip(), "org": self.org.text().strip(), "contact": self.contact.text().strip(),
                "days": self.days.value(), "reason": self.reason.toPlainText().strip(),
                "points": [l.strip() for l in self.points.toPlainText().split("\n") if l.strip()]}


class BatchDialog(QDialog):
    """일괄처리 — 여러 파일을 한꺼번에 검사·변환."""

    def __init__(self, parent=None, dictionary_getter=None):
        super().__init__(parent)
        self.setWindowTitle("일괄처리")
        self.resize(760, 560)
        self.get_dict = dictionary_getter
        v = QVBoxLayout(self)
        self.files = QListWidget()
        row = QHBoxLayout()
        for t, fn in [("파일 추가…", self.add_files), ("폴더 추가…", self.add_folder), ("목록 비우기", self.files.clear)]:
            b = QPushButton(t)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(self.files, 1)
        g = QGroupBox("작업")
        gl = QVBoxLayout(g)
        self.chk_check = QCheckBox("조문 검사 + 용어 검사 보고서(HTML)")
        self.chk_check.setChecked(True)
        self.chk_style = QCheckBox("스타일링 적용본 저장(TXT)")
        self.chk_hwpx = QCheckBox("HWPX로 변환")
        for w in (self.chk_check, self.chk_style, self.chk_hwpx):
            gl.addWidget(w)
        v.addWidget(g)
        row2 = QHBoxLayout()
        self.out = QLineEdit(str(Path.home() / "Documents" / "LawEdit_일괄처리"))
        b = QPushButton("출력 폴더…")
        b.clicked.connect(lambda: self.out.setText(QFileDialog.getExistingDirectory(self, "출력 폴더") or self.out.text()))
        row2.addWidget(QLabel("출력"))
        row2.addWidget(self.out, 1)
        row2.addWidget(b)
        v.addLayout(row2)
        self.bar = QProgressBar()
        v.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        v.addWidget(self.log)
        bb = QHBoxLayout()
        bb.addStretch(1)
        from . import theme
        run = theme.primary(QPushButton("실행"))
        run.clicked.connect(self.run)
        bb.addWidget(run)
        x = QPushButton("닫기")
        x.clicked.connect(self.accept)
        bb.addWidget(x)
        v.addLayout(bb)

    def add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "파일", "", "법령 문서 (*.txt *.hwp *.hwpx *.pdf *.lawj *.html)")
        for f in fs:
            self.files.addItem(f)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "폴더")
        if d:
            for p in sorted(Path(d).rglob("*")):
                if p.suffix.lower() in (".txt", ".hwp", ".hwpx", ".pdf", ".lawj"):
                    self.files.addItem(str(p))

    def run(self):
        files = [self.files.item(i).text() for i in range(self.files.count())]
        if not files:
            return
        out = Path(self.out.text())
        out.mkdir(parents=True, exist_ok=True)
        opts = (self.chk_check.isChecked(), self.chk_style.isChecked(), self.chk_hwpx.isChecked())
        dic = self.get_dict() if self.get_dict and opts[0] else None
        if opts[0] and dic is None:
            from ..core.dictionary import load_default
            dic = load_default(lawapi.load_settings().get("conf_dir") or None)
        self.bar.setRange(0, len(files))
        run_job(_batch, files, out, opts, dic, on_progress=lambda i, n: self.bar.setValue(i),
                on_done=lambda log: (self.bar.setValue(len(files)), self.log.setPlainText(log)),
                on_fail=lambda e: self.log.setPlainText(e))


def _batch(files, out: Path, opts, dic, progress=None) -> str:
    from ..core import fileio, checks
    from ..core.parser import parse_text
    from ..core.render import render_doc
    log = []
    rows = []
    for i, f in enumerate(files):
        if progress:
            progress(i, len(files))
        try:
            if f.lower().endswith(".lawj"):
                pr = fileio.Project.load(f)
                doc = pr.revised or pr.current
            else:
                doc = parse_text(fileio.read_any(f), name="")
                if not doc.name:
                    doc.name = Path(f).stem
            stem = Path(f).stem
            if opts[0]:
                iss = checks.run_all(doc, dic, {"용어", "띄어쓰기", "맞춤법", "사용자"} if dic else None)
                rows.append((doc.name, iss))
            if opts[1]:
                d2 = doc.clone()
                n = checks.apply_styling(d2)
                (out / f"{stem}_스타일링.txt").write_text(render_doc(d2), encoding="utf-8")
                log.append(f"{stem}: 스타일링 {n}곳")
            if opts[2]:
                fileio.text_to_hwpx(render_doc(doc), out / f"{stem}.hwpx", title=doc.name, title_lines=1)
            log.append(f"{stem}: 완료 (조문 {len(doc.articles())}개)")
        except Exception as e:      # noqa: BLE001
            log.append(f"{f}: 실패 — {e}")
    if rows:
        body = ["<h2>일괄 검사 보고서</h2>"]
        for name, iss in rows:
            body.append(f"<h3>{html.escape(name)} — {len(iss)}건</h3><table><tr><th>수준</th><th>분류</th><th>위치</th><th>내용</th></tr>")
            for x in iss:
                body.append(f"<tr><td>{x.level}</td><td>{x.category}</td><td>{html.escape(x.where)}</td><td>{html.escape(x.message)}</td></tr>")
            body.append("</table>")
        p = out / "일괄검사보고서.html"
        p.write_text(fileio.wrap_html("".join(body), "일괄 검사 보고서"), encoding="utf-8")
        log.append(f"보고서: {p}")
    return "\n".join(log)
