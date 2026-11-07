"""공통 위젯: 조문 편집기(강조 표시), 백그라운드 작업, 리본."""
from __future__ import annotations

import re
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt, QTimer, QSize
from PySide6.QtGui import (QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat,
                           QPainter, QIcon, QPixmap)
from PySide6.QtWidgets import (QPlainTextEdit, QTextEdit, QWidget, QHBoxLayout, QVBoxLayout, QToolButton, QLabel,
                               QFrame, QTabWidget, QSizePolicy, QStyle, QApplication, QPlainTextDocumentLayout)

FONT_FAMILIES = ["함초롬바탕", "HCR Batang", "바탕", "Batang", "Malgun Gothic", "맑은 고딕", "Noto Serif CJK KR", "Noto Sans CJK KR"]


def law_font(size: int = 11) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSize(size)
    return f


# ------------------------------------------------------------------ 강조 표시
class LawHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)

        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            f.setFontItalic(italic)
            return f
        self.rules = [
            (re.compile(r"^\s*제\s*\d+\s*(편|장|절|관)(의\d+)?\s.*$"), fmt("#9a3412", True)),
            (re.compile(r"^\s*제\s*\d+\s*조(의\s*\d+)?(\([^)]*\))?"), fmt("#1d4ed8", True)),
            (re.compile(r"^\s*부\s*칙.*$"), fmt("#7a1f1f", True)),
            (re.compile(r"[①-㊿]"), fmt("#1f6f3a", True)),
            (re.compile(r"^\s*\d+(의\d+)?\.(?=\s)"), fmt("#1f6f3a", True)),
            (re.compile(r"^\s*[가-하]\.(?=\s)"), fmt("#1f6f3a")),
            (re.compile(r"[<〈](개정|신설|삭제|본조신설|전문개정|제목개정|종전)[^>〉]*[>〉]"), fmt("#8a8a8a", italic=True)),
            (re.compile(r"「[^」]*」"), fmt("#6b3fa0")),
            (re.compile(r"\[(별표|별지|서식)[^\]]*\]"), fmt("#a05a00", True)),
        ]

    def highlightBlock(self, text):
        for rx, f in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)


class LawEditor(QPlainTextEdit):
    """조문 편집기. 줄 강조와 위치 찾기 지원."""
    changed_debounced = Signal()

    def __init__(self, parent=None, read_only=False):
        super().__init__(parent)
        self.setFont(law_font(11))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().setDocumentMargin(14)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setReadOnly(read_only)
        self.hl = LawHighlighter(self.document())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self.changed_debounced.emit)
        self.textChanged.connect(self._timer.start)
        self._marks: list = []
        self._peers: list = []

    def share_document(self, other: "LawEditor"):
        """other 의 문서를 함께 쓴다. 문서 배치(줄바꿈 폭)는 하나뿐이라 보이는 편집기 폭으로 다시 맞춘다."""
        self.setDocument(other.document())
        self._peers.append(other)
        other._peers.append(self)

    def _relayout(self):
        # Qt는 문서를 처음 맡은 편집기(또는 더 넓은 편집기) 폭으로만 줄을 바꾼다.
        # 새 배치 객체를 달고 다시 맡으면 이 편집기 폭으로 배치된다(실행 취소 기록은 문서에 남는다).
        if not self.isVisible():
            return
        doc = self.document()
        b = doc.firstBlock()
        if not b.isValid() or abs(doc.documentLayout().blockBoundingRect(b).width() - self.viewport().width()) <= 4:
            return
        c, sb = self.textCursor(), self.verticalScrollBar().value()
        pos, anchor = c.position(), c.anchor()
        doc.setDocumentLayout(QPlainTextDocumentLayout(doc))
        self.setDocument(doc)
        c = self.textCursor()
        c.setPosition(anchor)
        c.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)
        self.verticalScrollBar().setValue(sb)

    def showEvent(self, e):
        super().showEvent(e)
        if self._peers:
            QTimer.singleShot(0, self._relayout)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._peers:
            QTimer.singleShot(0, self._relayout)
            for p in self._peers:
                QTimer.singleShot(0, p._relayout)

    def set_text_keep_scroll(self, text: str):
        if self.toPlainText() == text:
            return
        sb = self.verticalScrollBar().value()
        cur = self.textCursor().position()
        self.blockSignals(True)
        self.setPlainText(text)
        self.blockSignals(False)
        c = self.textCursor()
        c.setPosition(min(cur, len(text)))
        self.setTextCursor(c)
        self.verticalScrollBar().setValue(sb)

    def goto_line(self, line: int, select_text: str = ""):
        block = self.document().findBlockByNumber(max(0, line))
        c = QTextCursor(block)
        if select_text:
            k = block.text().find(select_text)
            if k >= 0:
                c.setPosition(block.position() + k)
                c.setPosition(block.position() + k + len(select_text), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)
        self.centerCursor()
        self.setFocus()

    def mark_lines(self, lines: set[int], color="#fff6c8"):
        sels = []
        for ln in sorted(lines):
            b = self.document().findBlockByNumber(ln)
            if not b.isValid():
                continue
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(color))
            s.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            s.cursor = QTextCursor(b)
            sels.append(s)
        self._marks = sels
        self.setExtraSelections(sels)

    def find_unit_line(self, article_label: str, sub_label: str = "") -> int:
        """'제3조' 줄을 찾고, sub_label('②', '3.', '가.')이 있으면 그 아래에서 찾는다."""
        doc = self.document()
        n = doc.blockCount()
        start = -1
        pat = re.compile(r"^\s*" + re.escape(article_label) + r"(?![의\d])")
        for i in range(n):
            if pat.match(doc.findBlockByNumber(i).text()):
                start = i
                break
        if start < 0 or not sub_label:
            return start
        first = doc.findBlockByNumber(start).text()
        if sub_label in first:
            return start
        for i in range(start + 1, min(n, start + 200)):
            t = doc.findBlockByNumber(i).text().lstrip()
            if re.match(r"^제\s*\d+\s*조", t):
                break
            if t.startswith(sub_label):
                return i
        return start


# ------------------------------------------------------------------ 백그라운드 작업
class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)


class Job(QRunnable):
    def __init__(self, fn, *args, **kw):
        super().__init__()
        self.fn, self.args, self.kw = fn, args, kw
        self.signals = _Signals()

    def run(self):
        try:
            if "progress" in self.fn.__code__.co_varnames:
                self.kw.setdefault("progress", lambda i, n: self.signals.progress.emit(i, n))
            r = self.fn(*self.args, **self.kw)
            self.signals.done.emit(r)
        except Exception as e:      # noqa: BLE001 — 화면에 오류를 보여준다
            self.signals.failed.emit(f"{e}\n\n{traceback.format_exc()}")


def run_job(fn, *args, on_done=None, on_fail=None, on_progress=None, **kw) -> Job:
    j = Job(fn, *args, **kw)
    if on_done:
        j.signals.done.connect(on_done)
    if on_fail:
        j.signals.failed.connect(on_fail)
    if on_progress:
        j.signals.progress.connect(on_progress)
    QThreadPool.globalInstance().start(j)
    return j


# ------------------------------------------------------------------ 리본
def text_icon(ch: str, color: str = "#2f5597") -> QIcon:
    """글자 아이콘 (외부 이미지 없이)."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(1, 1, 30, 30, 6, 6)
    p.setPen(QColor("white"))
    f = QFont()
    f.setFamilies(["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR"])
    f.setPixelSize(15 if len(ch) == 1 else 11)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, ch)
    p.end()
    return QIcon(pm)


class RibbonGroup(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("RibbonGroup")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 2)
        v.setSpacing(0)
        self.row = QHBoxLayout()
        self.row.setSpacing(1)
        v.addLayout(self.row, 1)
        lab = QLabel(title)
        lab.setObjectName("RibbonGroupTitle")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(lab)

    def add(self, action) -> QToolButton:
        b = QToolButton()
        b.setObjectName("RibbonButton")
        b.setDefaultAction(action)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(24, 24))
        b.setAutoRaise(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumWidth(max(58, b.fontMetrics().horizontalAdvance(action.text()) + 18))
        b.setMinimumHeight(58)
        self.row.addWidget(b)
        return b


class Ribbon(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Ribbon")
        self.setDocumentMode(False)
        self.setFixedHeight(122)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)

    def page(self, title: str) -> QHBoxLayout:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 2, 8, 2)
        h.setSpacing(2)
        h.addStretch(1)
        self.addTab(w, title)
        return h

    @staticmethod
    def group(layout: QHBoxLayout, title: str) -> RibbonGroup:
        g = RibbonGroup(title)
        layout.insertWidget(layout.count() - 1, g)
        sep = QFrame()
        sep.setObjectName("RibbonSep")
        layout.insertWidget(layout.count() - 1, sep)
        return g


class Card(QFrame):
    """제목 머리가 달린 둥근 패널."""

    def __init__(self, widget: QWidget, title: str, sub: str = "", dot: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        v = QVBoxLayout(self)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(0)
        head = QFrame()
        head.setObjectName("CardHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(8)
        if dot:
            d = QFrame()
            d.setObjectName("CardDot")
            d.setStyleSheet(f"background:{dot}; border-radius:4px;")
            hl.addWidget(d)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        hl.addWidget(t)
        self.sub = QLabel(sub)
        self.sub.setObjectName("CardSub")
        hl.addWidget(self.sub)
        hl.addStretch(1)
        self.tools = hl
        v.addWidget(head)
        v.addWidget(widget, 1)

    def set_sub(self, text: str):
        self.sub.setText(text)


def fit_to_screen(win, width: int = 1500):
    """창 높이를 모니터 작업 영역(작업 표시줄 제외)에 맞추고 가로는 가운데로."""
    from PySide6.QtGui import QGuiApplication
    scr = win.screen() or QGuiApplication.primaryScreen()
    if scr is None:
        return
    a = scr.availableGeometry()
    # 창 테두리·제목 표시줄 두께만큼 빼야 화면 밖으로 넘치지 않는다
    fw = win.frameGeometry().height() - win.geometry().height()
    frame = fw if fw > 0 else 32
    w = min(width, a.width())
    h = a.height() - frame
    win.resize(w, h)
    win.move(a.x() + (a.width() - w) // 2, a.y())
