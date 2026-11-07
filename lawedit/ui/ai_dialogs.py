"""AI 도우미 화면 — 개정안·제정안 초안, AI 설정."""
from __future__ import annotations

import html

from ..core.korean import josa
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPlainTextEdit, QPushButton,
                               QComboBox, QLineEdit, QCheckBox, QTextBrowser, QSplitter, QMessageBox, QDialogButtonBox,
                               QDoubleSpinBox)

from ..ai.llm import LLMConfig, PRESETS
from ..ai import agent
from ..core.model import LAW_TYPES
from . import theme
from .widgets import run_job, LawEditor, law_font, Card

PRIVACY_NOTE = ("※ AI API를 쓰면 입력한 개정 의도와 규정 본문이 API 회사 서버로 전송됩니다. "
                "입법예고 전 비공개 내용은 기관 보안지침을 확인하세요.")


class AISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 모델 설정")
        self.resize(560, 380)
        c = LLMConfig.load()
        f = QFormLayout(self)
        self.preset = QComboBox()
        self.preset.addItem("(직접 설정)")
        self.preset.addItems(list(PRESETS))
        self.preset.currentTextChanged.connect(self._preset)
        self.provider = QComboBox()
        self.provider.addItem("Claude (Anthropic)", "anthropic")
        self.provider.addItem("OpenAI 호환 API (OpenAI·Gemini·공통기반·사내)", "openai")
        self.provider.setCurrentIndex(0 if c.provider == "anthropic" else 1)
        self.model = QLineEdit(c.model)
        self.base = QLineEdit(c.base_url)
        self.base.setPlaceholderText("OpenAI 호환 API 주소 (Claude 는 비움)")
        self.model.setPlaceholderText("API 회사가 안내하는 모델 이름")
        from ..ai.llm import mask
        self._saved_key = c.api_key
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(f"저장된 키: {mask(c.api_key)} (바꿀 때만 입력)" if c.api_key else "API 키 입력")
        self.key.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)     # 복사 메뉴 막기
        self.ws = QLineEdit(c.workspace_id)
        self.ws.setPlaceholderText("워크스페이스에 묶이지 않은 Claude 키일 때만: wrkspc_…")
        self.effort = QComboBox()
        self.effort.addItems(["low", "medium", "high", "xhigh"])
        self.effort.setCurrentText(c.effort)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(10, 1800)
        self.timeout.setValue(c.timeout)
        self.timeout.setSuffix(" 초")
        for lab, w in [("빠른 선택", self.preset), ("연결 방식", self.provider), ("모델", self.model), ("서버 주소", self.base),
                       ("API 키", self.key), ("워크스페이스 ID", self.ws), ("추론 수준(Claude)", self.effort), ("제한 시간", self.timeout)]:
            f.addRow(lab, w)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        test = QPushButton(theme.icon("play-circle-outline"), " 연결 시험")
        test.clicked.connect(self._test)
        f.addRow(test, self.msg)
        note = QLabel(PRIVACY_NOTE + "\n※ API 키는 Windows 보안 저장소(DPAPI)로 암호화해 이 PC·이 사용자 계정에만 저장됩니다. "
                      "설정 파일을 복사해도 다른 PC에서는 풀리지 않으며, 프로그램 폴더나 공유 파일에는 키가 들어가지 않습니다.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _preset(self, name):
        p = PRESETS.get(name)
        if not p:
            return
        self.provider.setCurrentIndex(0 if p["provider"] == "anthropic" else 1)
        self.model.setText(p["model"])
        self.base.setText(p["base_url"])

    def _cfg(self) -> LLMConfig:
        return LLMConfig(provider=self.provider.currentData(), model=self.model.text().strip(),
                         api_key=self.key.text().strip() or self._saved_key,
                         base_url=self.base.text().strip(), workspace_id=self.ws.text().strip(),
                         effort=self.effort.currentText(), timeout=self.timeout.value())

    def _test(self):
        self.msg.setText("시험 중…")
        run_job(agent.ping, self._cfg(), on_done=lambda r: self.msg.setText("✔ " + r),
                on_fail=lambda e: self.msg.setText("✖ " + e.split("\n")[0]))

    def _save(self):
        try:
            self._cfg().save()
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "AI 설정", str(e))
            return
        self.accept()


class AmendAIDialog(QDialog):
    """개정 의도 → AI 초안 → 미리보기 → 적용."""

    def __init__(self, main, scope_hint: str = ""):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("AI 개정안 작성")
        self.resize(1100, 760)
        self.draft = None
        self.preview_doc = None
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.intent = QPlainTextEdit()
        self.intent.setPlaceholderText("개정 의도를 적어 주세요.\n예) 인사위원회 위원 수를 7명 이상 9명 이내로 늘리고, 외부위원 비율을 과반으로 정한다.\n"
                                       "예) 조직개편으로 '경영기획본부'를 '경영전략본부'로 바꾼다.")
        self.intent.setFixedHeight(110)
        if scope_hint:
            self.intent.setPlainText(scope_hint)
        top.addWidget(Card(self.intent, "개정 의도", "", theme.C["primary"]), 1)
        side = QVBoxLayout()
        self.use_related = QCheckBox("상·하위 규정 조문을 참고로 함께 보냄(규정집)")
        self.use_related.setChecked(main.reg_corpus is not None)
        self.use_related.setEnabled(main.reg_corpus is not None)
        self.model_lab = QLabel(LLMConfig.load().label())
        self.model_lab.setObjectName("Pill")
        run = theme.primary(QPushButton(theme.icon("play-circle-outline", "white"), " AI 초안 만들기"))
        run.clicked.connect(self.run)
        side.addWidget(self.model_lab)
        side.addWidget(self.use_related)
        side.addStretch(1)
        side.addWidget(run)
        top.addLayout(side)
        v.addLayout(top)
        sp = QSplitter(Qt.Orientation.Horizontal)
        self.log = QTextBrowser()
        self.log.document().setDefaultStyleSheet(theme.HTML_CSS)
        self.table = QTextBrowser()
        self.table.document().setDefaultStyleSheet(theme.HTML_CSS)
        sp.addWidget(Card(self.log, "AI 초안 · 엔진 검증", "", "#c2410c"))
        sp.addWidget(Card(self.table, "신ㆍ구조문대비표 (미리보기)", "", "#0f766e"))
        sp.setSizes([420, 680])
        v.addWidget(sp, 1)
        note = QLabel(PRIVACY_NOTE)
        note.setObjectName("Hint")
        note.setWordWrap(True)
        v.addWidget(note)
        row = QHBoxLayout()
        self.status = QLabel("")
        row.addWidget(self.status, 1)
        self.apply_btn = theme.primary(QPushButton(theme.icon("check-decagram-outline", "white"), " 개정안에 적용"))
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        row.addWidget(self.apply_btn)
        row.addWidget(close)
        v.addLayout(row)

    def _related_context(self, intent: str) -> str:
        m = self.main
        if not (self.use_related.isChecked() and m.reg_corpus is not None and m.current is not None):
            return ""
        code = m._reg_code_of(m.current)
        rel = set()
        if code and m.reg_graph:
            rel = set(m.reg_graph.ancestors(code)) | set(m.reg_graph.descendants(code))
        hits = m.reg_corpus.similar(intent * 2, codes=rel or None, top=6, min_score=0.1)
        return "\n\n".join(f"「{it.reg}」 {it.text[:700]}" for s, it in hits)

    def run(self):
        intent = self.intent.toPlainText().strip()
        m = self.main
        if not intent:
            return
        if m.current is None:
            QMessageBox.information(self, "AI 개정안", "먼저 [현행추가]나 규정집에서 개정할 규정을 불러오세요.")
            return
        # 명칭 변경 의도인데 현행 규정에 그 명칭이 없으면 먼저 알려 준다
        self.pairs = agent.rename_pairs(intent)
        cur_text = m.current.plain() if hasattr(m.current, "plain") else ""
        from ..core.render import render_doc
        cur_text = render_doc(m.current)
        for old, new in self.pairs:
            if old in cur_text:
                continue
            if self._offer_bulk_rename(old, new):
                return
        cfg = LLMConfig.load()
        if not cfg.ready:
            AISettingsDialog(self).exec()
            cfg = LLMConfig.load()
            if not cfg.ready:
                return
        self.status.setText(f"AI가 초안을 쓰는 중… ({cfg.label()})")
        self.apply_btn.setEnabled(False)
        ctx = self._related_context(intent)
        run_job(agent.draft_amendment, cfg, m.current, intent, ctx, on_done=self._done,
                on_fail=lambda e: (self.status.setText("실패"), QMessageBox.warning(self, "AI 개정안", e.split("\n")[0])))

    def _offer_bulk_rename(self, old: str, new: str) -> bool:
        """현행에 없는 명칭 → 규정집에서 찾아 일괄 개정 제안. True 면 AI 호출을 건너뛴다."""
        m = self.main
        name = m.current.name
        if m.regbook is None:
            r = QMessageBox.question(self, "AI 개정안",
                                     f"현행 「{name}」에는 ‘{old}’{josa(old, '이/가')} 없습니다.\n"
                                     "다른 규정에 있는 명칭이라면 [규정집 분석]에서 규정집을 열면 쓰이는 곳을 모두 찾아 일괄 개정할 수 있습니다.\n\n"
                                     "그래도 AI 초안을 만들까요?")
            return r != QMessageBox.StandardButton.Yes
        locs = agent.term_locations(old, [e.doc for e in m.regbook.entries if e.doc is not None])
        if not locs:
            r = QMessageBox.question(self, "AI 개정안", f"‘{old}’{josa(old, '은/는')} 현행 규정과 규정집 어디에도 없습니다(표기를 확인하세요).\n\n그래도 AI 초안을 만들까요?")
            return r != QMessageBox.StandardButton.Yes
        total = sum(n for _, n, _ in locs)
        lines = "\n".join(f"  · {d.name.replace('안양도시공사 ', '')} {', '.join(arts[:4])} ({n}곳)" for d, n, arts in locs[:12])
        box = QMessageBox(self)
        box.setWindowTitle("명칭 변경 — 쓰이는 규정 찾음")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"현행 「{name}」에는 ‘{old}’{josa(old, '이/가')} 없습니다.\n이 명칭은 규정집의 {len(locs)}개 규정, {total}곳에서 쓰입니다.\n\n{lines}")
        base = locs[0][0]
        b_bulk = box.addButton(f"「{base.name.replace('안양도시공사 ', '')}」을 개정하고 나머지는 부칙으로 일괄 개정", QMessageBox.ButtonRole.AcceptRole)
        b_ai = box.addButton("그래도 현행에 AI 초안", QMessageBox.ButtonRole.ActionRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is b_bulk:
            self._bulk_rename(base, old, new, locs)
            return True
        return box.clickedButton() is not b_ai

    def _bulk_rename(self, base_doc, old: str, new: str, locs):
        """기준 규정을 현행으로 열고 명칭을 바꾼 뒤, 나머지 규정은 부칙 「다른 규정의 개정」으로."""
        from ..core import numbering, otherlaw, docs
        m = self.main
        entry = next((e for e in m.regbook.entries if e.doc is base_doc), None)
        if entry is None or not m.maybe_save():
            return
        m.load_from_regbook(entry)
        rev = m._doc_from_editor()
        n = numbering.batch_rename_titles(rev, old, new)
        m.set_revised_doc(rev)
        others = [e.doc for e in m.regbook.entries if e.doc is not None]
        ams = otherlaw.find_other_amendments(m.current, m._doc_from_editor(), others, [(old, new)])
        add = "제1조(시행일) " + docs.default_addenda(m.revised)
        if ams:
            add += "\n" + otherlaw.addenda_other_amend_text(ams, start_no=2)
        m.set_addenda_text(add)
        m.project.reason = f"조직 명칭 변경에 따라 ‘{old}’{josa(old, '을/를')} ‘{new}’{josa(new, '으로/로')} 바꾸고, 이 명칭을 쓰는 다른 규정을 함께 정비하려는 것임."
        m.project.points = [f"‘{old}’ → ‘{new}’ 명칭 변경({entry.name.replace('안양도시공사 ', '')} {n}곳)",
                            f"다른 규정 {len(ams)}개 정비(부칙 「다른 규정의 개정」)"]
        m.tabs.setCurrentIndex(3)
        QMessageBox.information(self, "명칭 일괄 개정",
                                f"「{entry.name}」의 ‘{old}’ {n}곳을 바꾸고, 다른 규정 {len(ams)}개는 부칙 「다른 규정의 개정」으로 만들었습니다.\n"
                                "[개정문(본문)] 탭에서 개정문과 부칙을 확인하세요.")
        self.accept()

    def _done(self, draft):
        from ..core.amend import compare_table_html, build_amendment_lines
        m = self.main
        self.draft = draft
        mark = m.settings.get("delete_mark", True)
        new, log = agent.apply_draft(m.current, m._doc_from_editor(), draft, "mark" if mark else "remove")
        self.preview_doc = new
        issues = [x for x in agent.verify_doc(new) if x.level == "오류"]
        base_errors = {(x.where, x.message) for x in agent.verify_doc(m.current) if x.level == "오류"}
        new_errors = [x for x in issues if (x.where, x.message) not in base_errors]
        parts = [f"<h3>AI 초안 ({html.escape(draft.model)})</h3><p class='muted'>{html.escape(draft.usage)}</p><ul>"]
        parts += [f"<li>{html.escape(l)}</li>" for l in log] + ["</ul>"]
        if draft.reason:
            parts.append(f"<b>개정이유</b><p>{html.escape(draft.reason)}</p>")
        if draft.points:
            parts.append("<b>주요내용</b><ul>" + "".join(f"<li>{html.escape(p)}</li>" for p in draft.points) + "</ul>")
        parts.append("<b>엔진 검증</b>")
        if new_errors:
            parts.append("<ul>" + "".join(f"<li style='color:#b42318'>{html.escape(x.where)} {html.escape(x.message)}</li>"
                                          for x in new_errors) + "</ul>")
        else:
            parts.append("<p style='color:#047857'>번호·인용·부호 오류 없음 (현행에 있던 오류 제외)</p>")
        allt = "\n".join(e.text for e in draft.edits)
        if draft.edits:
            draft.warnings += agent.spelling_warnings(getattr(self, "pairs", []), allt)
        for w in draft.warnings:
            parts.append(f"<p style='color:#b45309'>{html.escape(w)}</p>")
        changed = [c for c in __import__("lawedit.core.amend", fromlist=["compare"]).compare(m.current, new)]
        if not changed:
            parts.insert(1, "<p style='color:#b45309;font-weight:bold'>AI가 이 규정에서 고칠 조문이 없다고 판단했습니다. "
                            "아래 개정이유를 확인하고, 다른 규정을 고쳐야 하면 그 규정을 현행으로 열어 다시 시도하세요.</p>")
            self.log.setHtml("".join(parts))
            self.table.setHtml("")
            self.status.setText("개정할 조문 없음")
            self.apply_btn.setEnabled(False)
            return
        amend = build_amendment_lines(m.current, new)
        parts.append("<b>개정문</b><pre style='white-space:pre-wrap'>" + html.escape("\n".join(amend)) + "</pre>")
        self.log.setHtml("".join(parts))
        self.table.setHtml(compare_table_html(m.current, new))
        self.status.setText(f"초안 완료 — 조문 변경 {len(log)}건, 새로 생긴 오류 {len(new_errors)}건")
        self.apply_btn.setEnabled(True)

    def apply(self):
        m = self.main
        if self.preview_doc is None:
            return
        m.set_revised_doc(self.preview_doc)
        if self.draft:
            m.project.reason = self.draft.reason or m.project.reason
            m.project.points = self.draft.points or m.project.points
        m.tabs.setCurrentIndex(1)
        self.accept()


class NewAIDialog(QDialog):
    """제정 목적·위임 조항 → AI 제정안."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("AI 제정안 작성")
        self.resize(1000, 760)
        self.doc = None
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("예) 안양도시공사 생성형 AI 활용 지침")
        self.kind = QComboBox()
        self.kind.addItems(LAW_TYPES)
        self.kind.setCurrentText("지침")
        self.purpose = QPlainTextEdit()
        self.purpose.setPlaceholderText("제정 목적과 담을 내용 (예: 직원의 생성형 AI 업무 활용 기준, 보안·개인정보 보호, 승인 절차 …)")
        self.purpose.setFixedHeight(90)
        self.deleg = QPlainTextEdit()
        self.deleg.setPlaceholderText("상위 규정의 위임 조항 (예: 사무관리규정 제○조 '… 세부 사항은 사장이 따로 정한다.')")
        self.deleg.setFixedHeight(60)
        self.use_similar = QCheckBox("규정집에서 비슷한 조문을 찾아 참고로 보냄")
        self.use_similar.setChecked(main.reg_corpus is not None)
        self.use_similar.setEnabled(main.reg_corpus is not None)
        for lab, w in [("규정명", self.name), ("종류", self.kind), ("제정 목적", self.purpose), ("위임 조항", self.deleg), ("", self.use_similar)]:
            f.addRow(lab, w)
        v.addLayout(f)
        self.view = LawEditor(read_only=True)
        v.addWidget(Card(self.view, "AI 제정안 초안", "", theme.C["primary"]), 1)
        self.check = QLabel("")
        v.addWidget(self.check)
        row = QHBoxLayout()
        self.status = QLabel(LLMConfig.load().label())
        self.status.setObjectName("Pill")
        row.addWidget(self.status)
        row.addStretch(1)
        run = theme.primary(QPushButton(theme.icon("play-circle-outline", "white"), " AI 초안 만들기"))
        run.clicked.connect(self.run)
        self.apply_btn = QPushButton(theme.icon("file-document-edit-outline"), " 편집기로 보내기")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        for b in (run, self.apply_btn, close):
            row.addWidget(b)
        v.addLayout(row)

    def run(self):
        if not self.name.text().strip() or not self.purpose.toPlainText().strip():
            QMessageBox.information(self, "AI 제정안", "규정명과 제정 목적을 입력하세요.")
            return
        cfg = LLMConfig.load()
        if not cfg.ready:
            AISettingsDialog(self).exec()
            cfg = LLMConfig.load()
            if not cfg.ready:
                return
        similar = ""
        c = self.main.reg_corpus
        if self.use_similar.isChecked() and c is not None:
            hits = c.similar(self.purpose.toPlainText() * 2, top=6, min_score=0.1)
            similar = "\n\n".join(f"「{it.reg}」 {it.text[:600]}" for s, it in hits)
        self.status.setText("AI가 초안을 쓰는 중…")
        run_job(agent.draft_new, cfg, self.name.text().strip(), self.kind.currentText(), self.purpose.toPlainText().strip(),
                self.deleg.toPlainText().strip(), similar, on_done=self._done,
                on_fail=lambda e: (self.status.setText("실패"), QMessageBox.warning(self, "AI 제정안", e.split("\n")[0])))

    def _done(self, res):
        from ..core.render import render_doc
        doc, usage = res
        self.doc = doc
        self.view.setPlainText(render_doc(doc))
        errs = [x for x in agent.verify_doc(doc) if x.level == "오류"]
        self.check.setText(f"엔진 검증: 조문 {len(doc.articles())}개, 오류 {len(errs)}건" +
                           (" — " + "; ".join(f"{x.where} {x.message}" for x in errs[:3]) if errs else " (번호·인용·부호 정상)"))
        self.status.setText(usage)
        self.apply_btn.setEnabled(True)

    def apply(self):
        m = self.main
        if self.doc is None or not m.maybe_save():
            return
        from ..core import fileio
        from ..core.render import render_doc
        m.project = fileio.Project()
        m.current = None
        m.ed_cur.setPlainText("")
        m.revised = self.doc
        m.set_revised_text(render_doc(self.doc), undoable=False)
        m.tabs.setCurrentIndex(0)
        self.accept()
