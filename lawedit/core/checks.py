"""조문 검사·용어 검사·스타일링."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import LawDoc, Unit, CIRCLED, DIVISION_LABEL
from .refs import extract_refs, iter_text_units, find_abbreviations
from .parser import LOOKALIKE_CIRCLED


@dataclass
class Issue:
    level: str          # 오류 / 경고 / 참고
    category: str       # 번호 / 인용 / 부호 / 형식 / 용어 / 띄어쓰기 ...
    where: str          # 제3조제2항
    message: str
    uid: str = ""
    found: str = ""
    suggestion: str = ""


def _seq_issues(units: list[Unit], where: str, label: str, out: list[Issue]):
    expect = 1
    prev = None
    for u in units:
        if u.branch:
            if prev is None or u.num != prev.num:
                out.append(Issue("오류", "번호", where + u.ref_label(), f"가지번호 {u.ref_label()} 앞에 본번호가 없습니다.", u.uid))
            prev = u
            continue
        if u.num != expect:
            if u.num == expect - 1:
                out.append(Issue("오류", "번호", where + u.ref_label(), f"{label} 번호가 중복됩니다 ({u.number_label()}).", u.uid))
            else:
                out.append(Issue("오류", "번호", where + u.ref_label(),
                                 f"{label} 번호가 순서에 맞지 않습니다: {expect}번이 와야 할 자리에 {u.num}번.", u.uid))
        expect = u.num + 1
        prev = u


def check_structure(doc: LawDoc) -> list[Issue]:
    out: list[Issue] = []
    arts = doc.articles()
    _seq_issues(arts, "", "조", out)
    for kind in DIVISION_LABEL:
        divs = [d for d in doc.divisions() if d.kind == kind]
        if divs:
            _seq_issues(divs, "", DIVISION_LABEL[kind], out)
    for a in arts:
        w = a.number_label()
        if a.deleted:
            continue
        if not a.title:
            out.append(Issue("경고", "형식", w, "조 제목이 없습니다.", a.uid))
        if not a.text and not a.children:
            out.append(Issue("오류", "형식", w, "조 본문이 비어 있습니다.", a.uid))
        paras = [c for c in a.children if c.kind == "paragraph"]
        if paras:
            _seq_issues(paras, w, "항", out)
            if a.text:
                out.append(Issue("경고", "형식", w, "항(①)이 있는 조에 항 밖의 본문이 있습니다. ①이 빠졌는지 확인하세요.", a.uid))
            if len(paras) == 1:
                out.append(Issue("참고", "형식", w, "항이 하나뿐이면 ①을 붙이지 않습니다.", a.uid))
        owners = [a] + paras
        for o in owners:
            items = [c for c in o.children if c.kind == "item"]
            if items:
                ow = w + (o.ref_label() if o.kind == "paragraph" else "")
                _seq_issues(items, ow, "호", out)
                if len(items) == 1 and not items[0].branch:
                    out.append(Issue("참고", "형식", ow, "호가 하나뿐입니다. 본문으로 쓰는 것을 검토하세요.", o.uid))
                lead = o.text.rstrip()
                if lead and not re.search(r"(다음|각 호|각호|아래)", lead):
                    out.append(Issue("참고", "형식", ow, "호를 두는 본문에 '다음 각 호' 같은 연결 문구가 없습니다.", o.uid))
                for it in items:
                    subs = [c for c in it.children if c.kind == "subitem"]
                    if subs:
                        _seq_issues(subs, ow + it.ref_label(), "목", out)
        # 문장 끝
        for u in [a] + paras:
            t = u.text.strip()
            if t and u.kind in ("article", "paragraph") and not re.search(r"[.다)\]]$|다\.\s*$", t) and not t.endswith(":"):
                out.append(Issue("경고", "형식", w + (u.ref_label() if u.kind == "paragraph" else ""),
                                 "문장이 마침표로 끝나지 않습니다.", u.uid, t[-12:]))
        # 조문 머리에 다른 조 번호가 붙은 오타: '제84조제85조(위약금…)'
        if re.match(r"^제\d+조", a.title) or re.match(r"^제\d+조\s*\(", a.text or ""):
            out.append(Issue("오류", "번호", w, "조 번호 뒤에 다른 조 번호가 겹쳐 있습니다.", a.uid))
    if doc.meta.get("lookalikes"):
        out.append(Issue("경고", "부호", "", f"원문자(①)와 비슷한 다른 문자가 {doc.meta['lookalikes']}곳 쓰였습니다(예: ⓛ). 스타일링으로 바로잡습니다."))
    return out


def check_references(doc: LawDoc) -> list[Issue]:
    out: list[Issue] = []
    for r in extract_refs(doc):
        if r.target:
            continue
        a = doc.find_article(r.article, r.article_branch) if r.article else None
        if r.article and a is None:
            out.append(Issue("오류", "인용", r.src_label, f"없는 조문을 인용합니다: {r.text}", r.src_uid, r.text))
            continue
        if a is None:
            continue
        if a.deleted:
            out.append(Issue("오류", "인용", r.src_label, f"삭제된 조문을 인용합니다: {r.text}", r.src_uid, r.text))
            continue
        target: Unit = a
        if r.para:
            p = next((c for c in a.children if c.kind == "paragraph" and c.num == r.para), None)
            if p is None:
                if not any(c.kind == "paragraph" for c in a.children) and r.relative:
                    continue      # 항이 없는 조 안의 '제1호' 등
                out.append(Issue("오류", "인용", r.src_label, f"없는 항을 인용합니다: {a.number_label()}{'' if not r.relative else ''} 제{r.para}항", r.src_uid, r.text))
                continue
            target = p
        if r.item and not r.para and r.ctx_para:
            # '제1호'만 쓴 경우: 문장이 속한 항 → 조 바로 아래 순으로 찾는다
            cp = next((c for c in a.children if c.kind == "paragraph" and c.num == r.ctx_para), None)
            if cp is not None and any(c.kind == "item" for c in cp.children):
                target = cp
        if r.item:
            it = next((c for c in target.children if c.kind == "item" and c.num == r.item and c.branch == r.item_branch), None)
            if it is None and r.relative and not r.para:
                # 상대 인용 '제1호'는 같은 항/조 어디에든 있을 수 있음
                it = next((c for c in a.iter() if c.kind == "item" and c.num == r.item), None)
            if it is None:
                out.append(Issue("오류", "인용", r.src_label, f"없는 호를 인용합니다: {r.text}", r.src_uid, r.text))
    return out


def check_marks(doc: LawDoc) -> list[Issue]:
    out: list[Issue] = []
    pairs = [("「", "」"), ("“", "”"), ("(", ")"), ("‘", "’"), ("『", "』")]
    for u, art, para in iter_text_units(doc, True):
        t = u.text
        if not t:
            continue
        w = (art.number_label() if art else "") + (para.ref_label() if para and u is not art else "")
        for a, b in pairs:
            if t.count(a) != t.count(b):
                out.append(Issue("오류", "부호", w, f"여닫는 부호 {a}{b} 의 짝이 맞지 않습니다.", u.uid))
        if '"' in t:
            out.append(Issue("참고", "부호", w, '곧은 따옴표(")는 “ ”로 씁니다.', u.uid, '"'))
        if re.search(r"[․‧・]", t):
            out.append(Issue("참고", "부호", w, "가운뎃점은 'ㆍ' 또는 '·'로 통일합니다.", u.uid))
        if re.search(r" {2,}", t):
            out.append(Issue("참고", "띄어쓰기", w, "공백이 두 칸 이상 연속됩니다.", u.uid))
        if re.search(r"「\s|\s」", t):
            out.append(Issue("참고", "부호", w, "낫표 안쪽에 공백이 있습니다.", u.uid))
        m = re.search(r"\(이하\s*[“\"]([^”\"]+)[”\"]\s*이?라\s*한다\)", t)
    # 약칭 중복 정의
    full = "\n".join(u.text for u, _, _ in iter_text_units(doc))
    defs = re.findall(r"\(이하\s*[“\"]([^”\"]+)[”\"]\s*(?:이)?라\s*한다\.?\)", full)
    seen = set()
    for d in defs:
        if d in seen:
            out.append(Issue("경고", "형식", "", f"약칭 “{d}”을(를) 두 번 이상 정의했습니다."))
        seen.add(d)
    return out


def check_terms(doc: LawDoc, dictionary, categories=None) -> list[Issue]:
    out: list[Issue] = []
    for u, art, para in iter_text_units(doc, True):
        if not u.text:
            continue
        w = (art.number_label() if art else "") + (para.ref_label() if para and u is not art else "") + \
            (u.ref_label() if u.kind in ("item", "subitem") else "")
        for h in dictionary.check(u.text, categories):
            out.append(Issue("참고", h.category, w, f"“{h.found.strip()}” → {' / '.join(h.suggestions[:4])}" +
                             (f"  ({h.note})" if h.note else ""), u.uid, h.found.strip(), h.suggestions[0] if h.suggestions else ""))
    return out


def run_all(doc: LawDoc, dictionary=None, categories=None) -> list[Issue]:
    issues = check_structure(doc) + check_references(doc) + check_marks(doc)
    if dictionary is not None:
        issues += check_terms(doc, dictionary, categories)
    return issues


# ---------------------------------------------------------------- 스타일링
def style_text(t: str) -> str:
    for k, v in LOOKALIKE_CIRCLED.items():
        t = t.replace(k, v)
    t = re.sub(r"[․‧・]", "ㆍ", t)
    # 곧은 따옴표 → 둥근 따옴표 (여닫기 번갈아)
    if '"' in t:
        parts = t.split('"')
        t = parts[0] + "".join(("“" if i % 2 == 0 else "”") + p for i, p in enumerate(parts[1:]))
    t = re.sub(r"「\s+", "「", t)
    t = re.sub(r"\s+」", "」", t)
    t = re.sub(r"」(?=제\d)", "」 ", t)          # 「법」제2조 → 「법」 제2조
    t = re.sub(r"(?<=[가-힣])\(이하", " (이하", t) if False else t
    t = re.sub(r"\(이하([“\"])", r"(이하 \1", t)
    t = re.sub(r" {2,}", " ", t)
    t = re.sub(r"\s+([,.])", r"\1", t)
    t = re.sub(r"\s*:\s*", " : ", t) if False else t
    return t.strip()


def apply_styling(doc: LawDoc) -> int:
    n = 0
    for top in doc.body:
        for u in top.iter():
            for attr in ("text", "title"):
                v = getattr(u, attr)
                if v:
                    nv = style_text(v)
                    if nv != v:
                        setattr(u, attr, nv)
                        n += 1
    for ad in doc.addenda:
        nv = style_text(ad.text)
        if nv != ad.text:
            ad.text = nv
            n += 1
        for u in ad.units:
            for x in u.iter():
                nv = style_text(x.text)
                if nv != x.text:
                    x.text = nv
                    n += 1
    doc.meta.pop("lookalikes", None)
    return n


def replace_term(doc: LawDoc, uid: str, found: str, replacement: str) -> bool:
    u = doc.find_uid(uid)
    if u is None or found not in u.text:
        return False
    u.text = u.text.replace(found, replacement, 1)
    return True
