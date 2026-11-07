"""조문 인용 분석.

'제4조제1항 단서', '「지방공기업법」 제49조', '법 제2조', '같은 조 제2항', '제1호부터 제6호까지' 같은
인용을 찾아 대상(자기 문서/다른 법령)과 조·항·호·목 번호로 정리한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import LawDoc, Unit, subitem_number

_NUM = r"\s*(\d+)\s*"
RE_CHAIN = re.compile(
    r"제" + _NUM + r"조(?:\s*의\s*(\d+))?"
    r"(?:\s*제" + _NUM + r"항)?"
    r"(?:\s*제" + _NUM + r"호(?:\s*의\s*(\d+))?)?"
    r"(?:\s*([가-하])\s*목)?"
)
RE_PARA_ONLY = re.compile(r"(?<![조\d])제" + _NUM + r"항(?:\s*제" + _NUM + r"호(?:\s*의\s*(\d+))?)?(?:\s*([가-하])\s*목)?")
RE_ITEM_ONLY = re.compile(r"(?<![항조\d])제" + _NUM + r"호(?:\s*의\s*(\d+))?(?:\s*([가-하])\s*목)?")
RE_LAWNAME = re.compile(r"「([^」]{2,80})」")
RE_ABBR = re.compile(r"(?:「([^」]+)」|([가-힣A-Za-z0-9·ㆍ\s]{2,40}?))\s*(?:제\s*\d+\s*조[^(]{0,20})?\(\s*이하\s*[“\"‘'“]\s*([^”\"’'”]{1,20}?)\s*[”\"’'”]\s*(?:이)?\s*라\s*(?:한다|함)\s*\.?\s*\)")
ABBR_HINT = ("법", "영", "시행령", "규칙", "시행규칙", "조례", "정관", "규정", "내규", "시행내규", "지침")

# 같은 문서이지만 다른 법령을 가리킬 수 있는 앞말 (규정명 일부)
RE_PREFIX_NAME = re.compile(r"([가-힣·ㆍ]{1,30}(?:법|법률|시행령|시행규칙|조례|규칙|정관|규정|내규|지침|강령))\s*$")


@dataclass
class Ref:
    text: str                # 원문 인용 표기
    start: int
    end: int
    target: str = ""         # ''=이 문서, 그 외 법령명(약칭 해석 후)
    target_raw: str = ""     # 원문의 앞말(약칭/법령명)
    article: int = 0
    article_branch: int = 0
    para: int = 0
    item: int = 0
    item_branch: int = 0
    subitem: int = 0
    relative: bool = False   # 같은 조 안의 '제2항' 처럼 조 번호 생략
    ctx_para: int = 0        # 항 번호 없이 '제1호'만 쓴 경우 그 문장이 속한 항
    src_uid: str = ""
    src_label: str = ""

    def label(self) -> str:
        s = ""
        if self.article:
            s += f"제{self.article}조" + (f"의{self.article_branch}" if self.article_branch else "")
        if self.para:
            s += f"제{self.para}항"
        if self.item:
            s += f"제{self.item}호" + (f"의{self.item_branch}" if self.item_branch else "")
        if self.subitem:
            s += "가나다라마바사아자차카타파하"[self.subitem - 1] + "목"
        return s


def find_abbreviations(text: str) -> dict[str, str]:
    """'(이하 “법”이라 한다)' 정의 → {약칭: 정식명}."""
    out: dict[str, str] = {}
    # '(이하' 가 있는 곳 주변만 정규식으로 본다 (전체 문서를 훑으면 매우 느림)
    windows = []
    for k in re.finditer(r"\(\s*이하", text):
        windows.append(text[max(0, k.start() - 90):k.start() + 40])
    for m in (mm for w in windows for mm in RE_ABBR.finditer(w)):
        full = (m.group(1) or m.group(2) or "").strip()
        short = m.group(3).strip()
        if full and short and short != full:
            out.setdefault(short, full)
    return out


_NAME_STOP = re.compile(r"(?:은|는|이|가|을|를|에서|에게|하여|하고|하며|한|후|때|경우|및|또는|로|으로|라|다)$")


def _law_name_from_words(words: list[str]) -> str:
    """낫표 없이 쓴 법령명 고르기: '… 결재를 득한 후 형사소송법' → '형사소송법',
    '기간제 및 단시간근로자 보호 등에 관한 법률' → 그대로."""
    if not words:
        return ""
    last = words[-1]
    if last != "법률":
        return last if len(last) >= 3 else ""
    # '…에 관한 법률': '관한' 앞의 명사구를 거꾸로 모은다
    out = [last]
    i = len(words) - 2
    while i >= 0:
        w = words[i]
        if w in ("관한", "대한", "위한", "따른") or w.endswith(("에", "의", "등")) or w in ("및", "등"):
            out.insert(0, w)
            i -= 1
            continue
        if _NAME_STOP.search(w) and w not in ("및",):
            break
        out.insert(0, w)
        i -= 1
    return " ".join(out)


def _prefix_target(text: str, pos: int, abbrs: dict[str, str]) -> tuple[str, str]:
    """인용 바로 앞의 법령명/약칭."""
    before = text[max(0, pos - 90):pos]
    b = before.rstrip()
    if re.search(r"(?:^|[\s(])이\s*(?:법|영|규칙|조례|규정|내규|정관|강령)\s*$", b):
        return "", ""
    if re.search(r"(?:^|[\s(])(?:같은|동)\s*(?:법|영|규칙|조례|규정|내규)\s*$", b):
        return "(같은 법)", "같은 법"
    m = re.search(r"「([^」]{2,80})」\s*(?:\([^)]{0,40}\))?\s*$", b)
    if m:
        return m.group(1).strip(), m.group(0)
    # 약칭: '법 제2조', '영 제5조'
    m = re.search(r"(?:^|[\s(,“”\"·ㆍ])([가-힣]{1,10})\s*$", b)
    if m:
        w = m.group(1)
        if w in abbrs:
            return abbrs[w], w
        if w in ABBR_HINT and w not in ("규정", "내규") or w in ("법", "영"):
            return w, w
        if w in ("규정", "내규", "정관", "조례") and len(before) - len(b) <= 1:
            return w, w
        if w in ("같은", "이", "동"):
            return "", ""
    m = re.search(r"[“\"]([^”\"]{2,60}(?:법|법률|령|규칙|조례|규정|내규|정관))[”\"]\s*$", b)
    if m:
        return m.group(1).strip(), m.group(0)
    m = re.search(r"((?:[가-힣·ㆍ]+\s+){0,7}[가-힣·ㆍ]*(?:법률|법))\s*$", b)
    if m and (m.group(1).endswith("법률") or len(m.group(1).split()[-1]) >= 2) and not re.search(r"(?:^|\s)(?:이|같은|동)\s*법$", m.group(1)):
        name = _law_name_from_words(m.group(1).split())
        if name:
            return name, name
    m = RE_PREFIX_NAME.search(b)
    if m:
        name = m.group(1)
        pre = b[:m.start()].rstrip()
        if pre.endswith(("이", "같은", "동")) and len(name) <= 3:
            return "", ""
        if name in ("법률", "법"):
            # '…에 관한 법률 제2조' — 앞쪽 몇 낱말까지 법령명으로
            mm = re.search(r"([가-힣·ㆍ\s]{2,40}법률)\s*$", b)
            return (mm.group(1).strip() if mm else name), name
        if len(name) >= 2:
            return name, name
    return "", ""


def extract_refs_text(text: str, abbrs: dict[str, str] | None = None,
                      ctx_article: int = 0, ctx_branch: int = 0, ctx_para: int = 0) -> list[Ref]:
    abbrs = abbrs or {}
    refs: list[Ref] = []
    taken: list[tuple[int, int]] = []

    def overlaps(a, b):
        return any(not (b <= s or a >= e) for s, e in taken)

    for m in RE_CHAIN.finditer(text):
        tgt, raw = _prefix_target(text, m.start(), abbrs)
        tgt = re.sub(r"\s+", " ", tgt).strip()
        r = Ref(text=m.group(0), start=m.start(), end=m.end(), target=tgt, target_raw=raw,
                article=int(m.group(1)), article_branch=int(m.group(2) or 0),
                para=int(m.group(3) or 0), item=int(m.group(4) or 0), item_branch=int(m.group(5) or 0),
                subitem=subitem_number(m.group(6)) if m.group(6) else 0)
        # '같은 조' 앞말
        refs.append(r)
        taken.append((m.start(), m.end()))
    for m in RE_PARA_ONLY.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        before = text[max(0, m.start() - 8):m.start()]
        same = re.search(r"(?:같은\s*조|동\s*조)\s*$", before)
        tgt, raw = ("", "") if same or not before.strip() else _prefix_target(text, m.start(), abbrs)
        if raw and raw not in ("법", "영") and not tgt:
            tgt = ""
        r = Ref(text=m.group(0), start=m.start(), end=m.end(), target=tgt if raw else "",
                article=ctx_article, article_branch=ctx_branch,
                para=int(m.group(1)), item=int(m.group(2) or 0), item_branch=int(m.group(3) or 0),
                subitem=subitem_number(m.group(4)) if m.group(4) else 0, relative=True)
        refs.append(r)
        taken.append((m.start(), m.end()))
    for m in RE_ITEM_ONLY.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        same_para = re.search(r"같은\s*항\s*$", text[max(0, m.start() - 6):m.start()])
        r = Ref(text=m.group(0), start=m.start(), end=m.end(), article=ctx_article, article_branch=ctx_branch,
                para=ctx_para if same_para else 0, item=int(m.group(1)), item_branch=int(m.group(2) or 0),
                subitem=subitem_number(m.group(3)) if m.group(3) else 0, relative=True, ctx_para=ctx_para)
        refs.append(r)
        taken.append((m.start(), m.end()))
    refs.sort(key=lambda r: r.start)
    # 서식·별표 번호는 인용이 아니다: '별지 제2호 서식', '[별지 제19호의 서식]'
    allrefs = list(refs)
    refs = [r for r in refs if not (re.search(r"(별지|별표|서식|별표\s*\d+\s*\])\s*[\[〔(]?\s*$", text[max(0, r.start - 10):r.start])
                                    or re.match(r"^\s*(?:의\s*)?서식", text[r.end:r.end + 5]))]
    # 서식·별표 번호 뒤에 나열된 번호도 제외: '[별표 1] 제3호 및 제4호'
    kept = set(id(r) for r in refs)
    for prev, r in zip(allrefs, allrefs[1:]):
        if id(prev) not in kept and id(r) in kept and \
                re.fullmatch(r"\s*(?:,|및|또는|과|와|ㆍ|·|부터|내지)?\s*", text[prev.end:r.start]):
            kept.discard(id(r))
    refs = [r for r in allrefs if id(r) in kept]
    # '같은 법 제3조' — 바로 앞에 인용한 법령
    last_t = ""
    for r in refs:
        if r.target == "(같은 법)":
            r.target = last_t
        elif r.target:
            last_t = r.target
    # '같은 조 제5호' — 바로 앞에 인용한 조(다른 법령일 수 있음)
    last_chain = None
    for r in refs:
        if not r.relative:
            last_chain = r
        elif last_chain is not None and re.search(r"(?:같은|동)\s*조\s*$", text[max(0, r.start - 6):r.start]):
            r.target, r.target_raw = last_chain.target, last_chain.target_raw
            r.article, r.article_branch = last_chain.article, last_chain.article_branch
            if r.item and not r.para:
                r.para = last_chain.para
    # 나열된 인용은 앞 인용의 대상·상위 번호를 이어받는다: '「법」 제19조의2, 제19조의3', '제47조제1항제1호, 제2호'
    for prev, r in zip(refs, refs[1:]):
        gap = text[prev.end:r.start]
        if not re.fullmatch(r"\s*(?:\([^)]{0,30}\))?\s*(?:단서|본문|전단|후단|각\s*호\s*외의\s*부분)?\s*(?:,|및|또는|과|와|ㆍ|·|부터|내지|이나|나)?\s*", gap):
            continue
        if prev.target and not r.target and r.relative and re.search(r"(?:같은|동)\s*조\s*$", text[max(0, r.start - 6):r.start]):
            r.target, r.target_raw = prev.target, prev.target_raw
        if prev.target and not r.target:
            r.target, r.target_raw = prev.target, prev.target_raw
        if r.relative and not prev.relative or (r.relative and prev.relative):
            if r.item and not r.para and prev.para:
                r.article, r.article_branch, r.para = prev.article, prev.article_branch, prev.para
            elif r.item and prev.article and not r.para:
                r.article, r.article_branch = prev.article, prev.article_branch
            elif r.para and prev.article:
                r.article, r.article_branch = prev.article, prev.article_branch
    return refs


def iter_text_units(doc: LawDoc, include_addenda: bool = False):
    """(unit, article, para) 를 순회 — 텍스트가 있는 모든 단위."""
    def walk(u: Unit, art: Unit | None, para: Unit | None):
        if u.kind == "article":
            art = u
        if u.kind == "paragraph":
            para = u
        yield u, art, para
        for c in u.children:
            yield from walk(c, art, para)
    for u in doc.body:
        yield from walk(u, None, None)
    if include_addenda:
        for ad in doc.addenda:
            for u in ad.units:
                yield from walk(u, None, None)


def unit_path_label(art: Unit | None, para: Unit | None, u: Unit) -> str:
    s = art.number_label() if art else ""
    if para is not None and u.kind != "article":
        s += para.ref_label()
    if u.kind in ("item", "subitem"):
        if u.kind == "subitem":
            # 부모 호 찾기 어려움 → 호 번호는 생략하고 목만
            s += u.ref_label()
        else:
            s += u.ref_label()
    return s


def extract_refs(doc: LawDoc, include_addenda: bool = False) -> list[Ref]:
    full = "\n".join(u.text + " " + u.title for u, _, _ in iter_text_units(doc, include_addenda))
    abbrs = find_abbreviations(full)
    out: list[Ref] = []
    for u, art, para in iter_text_units(doc, include_addenda):
        for field_text in (u.text,):
            if not field_text:
                continue
            for r in extract_refs_text(field_text, abbrs,
                                       ctx_article=art.num if art else 0,
                                       ctx_branch=art.branch if art else 0,
                                       ctx_para=para.num if para else 0):
                r.src_uid = u.uid
                r.src_label = unit_path_label(art, para, u)
                out.append(r)
    return out


def law_names_cited(text: str) -> list[str]:
    seen = []
    for m in RE_LAWNAME.finditer(text):
        n = m.group(1).strip()
        if n not in seen:
            seen.append(n)
    return seen
