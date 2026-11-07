"""텍스트 → LawDoc 파서.

한글 문서·법령정보센터·PDF 에서 복사한 법령 텍스트를 조·항·호·목 구조로 바꾼다.
PDF 처럼 한 문장이 여러 줄로 잘린 경우에는 번호 순서를 보고 이어 붙인다.
"""
from __future__ import annotations

import re

from .model import (LawDoc, Unit, Addendum, Appendix, CIRCLED, LABEL_DIVISION,
                    uncircle, subitem_number, HANGUL_ITEMS, LAW_TYPES)

RE_DIVISION = re.compile(r"^제\s*(\d+)\s*(편|장|절|관)(?:의\s*(\d+))?(?:\s+(.*))?$")
RE_ARTICLE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?=\s*[(（]|\s*삭제|\s*$|\s+[①-㊿])")
RE_PARA = re.compile(r"^([%s])\s*(.*)$" % CIRCLED)
RE_ITEM = re.compile(r"^(\d+)(?:의(\d+))?\.\s*(.*)$")
RE_SUBITEM = re.compile(r"^([%s거너더러머버서어저처커터퍼허])\.\s*(.*)$" % HANGUL_ITEMS)
RE_ADDENDA = re.compile(r"^부\s*칙\s*(<[^>]*>|〈[^〉]*〉|\([^)]*\))?\s*(.*)$")
RE_APPENDIX = re.compile(r"^\[\s*(별표|서식|별지)\s*(?:제\s*)?(\d+)(?:\s*의\s*(\d+))?\s*(?:호\s*서식|호)?\s*\](?=\s|<|〈|\(|$)\s*(.*)$")
RE_HISTORY_LINE = re.compile(r"^\s*(제정|일부개정|전부개정|타법개정|폐지제정|폐지|개정)\s+\d{4}\s*\.")
# 분석 결과가 바뀌는 수정을 하면 올린다 — 저장해 둔 규정집 분석(캐시)을 다시 만든다
PARSER_VERSION = 2

RE_TAIL_TAG = re.compile(r"\s*[<〈]\s*(?:개정|신설|삭제|본조신설|전문개정|제목개정|본조제목개정|종전|이동|시행일)[^>〉]*[>〉]\s*$")
RE_DELETED = re.compile(r"^삭\s*제\s*(?:[<〈][^>〉]*[>〉])?\s*\.?$")


# 원문자와 모양이 비슷해 잘못 입력되는 문자들
LOOKALIKE_CIRCLED = {"ⓛ": "①", "⓵": "①", "⓶": "②", "⓷": "③", "⓸": "④", "⓹": "⑤", "❶": "①", "❷": "②", "❸": "③"}


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    for k, v in LOOKALIKE_CIRCLED.items():
        text = text.replace(k, v)
    return text.replace("｢", "「").replace("｣", "」")


def _split_title(rest: str) -> tuple[str, str]:
    """'(목적) 이 규정은...' -> ('목적', '이 규정은...'). 중첩 괄호 처리."""
    s = rest.lstrip()
    if not s or s[0] not in "(（":
        return "", rest.strip()
    depth = 0
    for i, ch in enumerate(s):
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth -= 1
            if depth == 0:
                return s[1:i].strip(), s[i + 1:].strip()
    return "", rest.strip()


def strip_tail_tags(text: str) -> tuple[str, str]:
    """끝에 붙은 <개정 ...> 표기를 분리."""
    tags = []
    while True:
        m = RE_TAIL_TAG.search(text)
        if not m:
            break
        tags.insert(0, m.group(0).strip())
        text = text[:m.start()].rstrip()
    return text, " ".join(tags)


def join_lines(prev: str, nxt: str) -> str:
    if not prev:
        return nxt.strip()
    if prev.endswith((" ", "\t")):
        return prev.rstrip() + " " + nxt.strip()
    nxt = nxt.strip()
    if not nxt:
        return prev
    # 꺾쇠 표기, 괄호 시작은 띄움
    if nxt[0] in "<〈" or prev[-1] in ".,;:)」>":
        return prev + " " + nxt
    return prev + nxt


class _State:
    def __init__(self, doc: LawDoc):
        self.doc = doc
        self.div_stack: list[Unit] = []
        self.article: Unit | None = None
        self.para: Unit | None = None
        self.item: Unit | None = None
        self.sub: Unit | None = None
        self.last: Unit | None = None          # 마지막으로 텍스트를 받은 단위
        self.addendum: Addendum | None = None
        self.appendix: Appendix | None = None
        self.last_article_num = 0

    # 현재 단위 리스트(본칙/부칙)
    def container(self) -> list[Unit]:
        if self.addendum is not None:
            return self.addendum.units
        if self.div_stack:
            return self.div_stack[-1].children
        return self.doc.body


def _expected_article(st: _State, num: int, branch: int) -> bool:
    last = st.last_article_num
    if st.article is None and last == 0:
        return True
    if branch and num == last:
        return True
    if branch and st.article and num == st.article.num:
        return True
    return last < num <= last + 15 or (branch and num <= last)


def _expected_para(st: _State, num: int) -> bool:
    if st.article is None:
        return False
    paras = [c for c in st.article.children if c.kind == "paragraph"]
    if not paras:
        return num in (1, 2) and not any(c.kind == "item" for c in st.article.children) or num == 1
    return num == paras[-1].num + 1


def _expected_item(st: _State, num: int, branch: int) -> bool:
    owner = st.para or st.article
    if owner is None:
        return False
    items = [c for c in owner.children if c.kind == "item"]
    if not items:
        return num == 1
    last = items[-1]
    if branch:
        return num == last.num and branch == last.branch + 1 or (num == last.num and branch >= 2 and last.branch == 0) or (num == last.num and branch == 2)
    return num == last.num + 1


def _expected_sub(st: _State, num: int) -> bool:
    if st.item is None:
        return False
    subs = [c for c in st.item.children if c.kind == "subitem"]
    return num == (subs[-1].num + 1 if subs else 1)


def parse_text(text: str, name: str = "", law_type: str = "") -> LawDoc:
    doc = LawDoc(name=name)
    st = _State(doc)
    looks = sum(text.count(k) for k in LOOKALIKE_CIRCLED)
    lines = normalize_text(text).split("\n")
    seen_body = False

    def append_text(u, line):
        if u is None:
            return
        u.text = join_lines(u.text, line)

    for raw in lines:
        line = raw.replace("　", " ").rstrip("\n")
        s = line.strip()
        if not s:
            # 빈 줄은 이어 붙이기 판단에 쓰지 않음(PDF 공백 줄 다수)
            if st.last is not None and st.last.text and not st.last.text.endswith(" "):
                pass
            continue
        keep_space = line.endswith(" ")

        # 1) 제목/연혁 (본문 시작 전)
        if not seen_body:
            if RE_HISTORY_LINE.match(s) or (s.startswith("(") and doc.history and not RE_ARTICLE.match(s)):
                doc.history.append(s)
                continue
            if not doc.name and not RE_ARTICLE.match(s) and not RE_DIVISION.match(s) and not RE_ADDENDA.match(s):
                doc.name = s
                continue

        # 2) 별표/서식
        m = RE_APPENDIX.match(s)
        if m and (st.addendum is not None or seen_body):
            kind = "별지" if m.group(1) in ("별지", "서식") and "서식" in s else m.group(1)
            ap = Appendix(kind=kind, num=int(m.group(2)), branch=int(m.group(3) or 0))
            rest = m.group(4).strip()
            mref = re.match(r"^[<(（〈]\s*(제\s*\d+\s*조[^>)）〉]*관련)\s*[>)）〉]\s*(.*)$", rest)
            if mref:
                ap.ref, rest = mref.group(1), mref.group(2)
            # 제목 앞의 <개정 …> 표기(여러 줄일 수 있음)는 연혁으로
            mtag = re.match(r"^([<〈]\s*(?:개정|신설|삭제|전문개정|본표신설|제목개정)[^>〉]*)([>〉])?\s*(.*)$", rest)
            if mtag:
                ap.history = mtag.group(1) + (mtag.group(2) or "")
                ap._tag_open = mtag.group(2) is None
                rest = mtag.group(3) if mtag.group(2) else ""
            rest, tail = strip_tail_tags(rest)
            ap.history = (ap.history + " " + tail).strip()
            ap.title = rest
            doc.appendices.append(ap)
            st.appendix = ap
            st.last = None
            continue
        if st.appendix is not None and getattr(st.appendix, "_tag_open", False):
            k = max(s.find(">"), s.find("〉"))
            if k < 0:
                st.appendix.history += " " + s
            else:
                st.appendix.history += " " + s[:k + 1]
                st.appendix._tag_open = False
                if s[k + 1:].strip() and not st.appendix.title:
                    st.appendix.title = s[k + 1:].strip()
            continue
        if st.appendix is not None:
            if not st.appendix.title:
                st.appendix.title = s
            else:
                st.appendix.text += (("\n" if st.appendix.text else "") + s)
            continue

        # 3) 부칙
        m = RE_ADDENDA.match(s)
        if m and seen_body and (len(s) < 60) and not s.startswith("부칙에"):
            ad = Addendum(header=("부칙 " + (m.group(1) or "")).strip())
            doc.addenda.append(ad)
            st.addendum = ad
            st.div_stack = []
            st.article = st.para = st.item = st.sub = None
            st.last_article_num = 0
            rest = (m.group(2) or "").strip()
            if rest:
                ad.text = rest
                st.last = None
            else:
                st.last = None
            continue

        # 4) 편장절관
        m = RE_DIVISION.match(s)
        if m and st.addendum is None and (m.group(4) is None or (len(m.group(4)) <= 40 and not m.group(4).rstrip().endswith(("다.", "다", ","))
                                                                 and not re.match(r"^(에|의|을|를|부터|까지|및|또는|중)", m.group(4)))):
            kind = LABEL_DIVISION[m.group(2)]
            div = Unit(kind=kind, num=int(m.group(1)), branch=int(m.group(3) or 0), title=(m.group(4) or "").strip())
            order = ["part", "chapter", "section", "subsection"]
            while st.div_stack and order.index(st.div_stack[-1].kind) >= order.index(kind):
                st.div_stack.pop()
            (st.div_stack[-1].children if st.div_stack else doc.body).append(div)
            st.div_stack.append(div)
            st.article = st.para = st.item = st.sub = None
            st.last = None
            seen_body = True
            continue

        # 5) 조
        m = RE_ARTICLE.match(s)
        if m:
            num, branch = int(m.group(1)), int(m.group(2) or 0)
            if _expected_article(st, num, branch):
                title, rest = _split_title(s[m.end():])
                art = Unit(kind="article", num=num, branch=branch, title=title)
                st.container().append(art)
                st.article, st.para, st.item, st.sub = art, None, None, None
                st.last_article_num = num
                seen_body = True
                rest, tag = strip_tail_tags(rest)
                if RE_DELETED.match(rest) or rest.startswith("삭제") or (not rest and "삭제" in tag):
                    art.deleted = True
                    art.history = (rest[2:].strip() + " " + tag).strip()
                    st.last = None
                    continue
                art.history = tag
                pm = RE_PARA.match(rest)
                if pm:
                    p = Unit(kind="paragraph", num=uncircle(pm.group(1)))
                    prest, ptag = strip_tail_tags(pm.group(2))
                    if RE_DELETED.match(prest) or (not prest and "삭제" in ptag):     # '제3조(제목) ① 삭제'
                        p.deleted, p.history = True, (prest[2:].strip() + " " + ptag).strip()
                    else:
                        p.text, p.history = prest, ptag
                    art.children.append(p)
                    st.para = p
                    st.last = p if not p.deleted else None
                else:
                    art.text = rest
                    st.last = art
                if keep_space and st.last is not None:
                    st.last.text += " "
                continue

        # 6) 항
        m = RE_PARA.match(s)
        if m and _expected_para(st, uncircle(m.group(1))):
            p = Unit(kind="paragraph", num=uncircle(m.group(1)))
            rest, tag = strip_tail_tags(m.group(2))
            if RE_DELETED.match(rest) or (not rest and "삭제" in tag):
                p.deleted, p.history = True, (rest[2:].strip() + " " + tag).strip()
                rest = ""
            else:
                p.text, p.history = rest, tag
            st.article.children.append(p)
            st.para, st.item, st.sub = p, None, None
            st.last = p if not p.deleted else None
            if keep_space and st.last is not None:
                st.last.text += " "
            continue

        # 7) 호
        m = RE_ITEM.match(s)
        if m and _expected_item(st, int(m.group(1)), int(m.group(2) or 0)):
            it = Unit(kind="item", num=int(m.group(1)), branch=int(m.group(2) or 0))
            rest, tag = strip_tail_tags(m.group(3))
            if RE_DELETED.match(rest) or (not rest and "삭제" in tag):
                it.deleted, it.history = True, (rest[2:].strip() + " " + tag).strip()
            else:
                it.text, it.history = rest, tag
            (st.para or st.article).children.append(it)
            st.item, st.sub = it, None
            st.last = it if not it.deleted else None
            if keep_space and st.last is not None:
                st.last.text += " "
            continue

        # 8) 목
        m = RE_SUBITEM.match(s)
        if m and _expected_sub(st, subitem_number(m.group(1))):
            sb = Unit(kind="subitem", num=subitem_number(m.group(1)))
            rest, tag = strip_tail_tags(m.group(2))
            if RE_DELETED.match(rest) or (not rest and "삭제" in tag):
                sb.deleted, sb.history = True, (rest[2:].strip() + " " + tag).strip()
            else:
                sb.text, sb.history = rest, tag
            st.item.children.append(sb)
            st.sub = sb
            st.last = sb if not sb.deleted else None
            if keep_space and st.last is not None:
                st.last.text += " "
            continue

        # 9) 이어지는 줄
        if st.addendum is not None and st.article is None:
            st.addendum.text = join_lines(st.addendum.text, line)
            continue
        if st.last is not None:
            # 꺾쇠 연혁 표기만 있는 줄
            only_tag, tag = strip_tail_tags(s)
            if not only_tag and tag:
                st.last.history = (st.last.history + " " + tag).strip()
                continue
            st.last.text = join_lines(st.last.text, line)
            if keep_space:
                st.last.text += " "
            continue
        if st.article is None and not seen_body:
            continue
        if st.div_stack and st.article is None:
            # 장 제목이 두 줄로 나뉜 경우
            st.div_stack[-1].title = join_lines(st.div_stack[-1].title, s)

    _finalize(doc)
    if looks:
        doc.meta["lookalikes"] = looks
    if law_type:
        doc.law_type = law_type
    else:
        doc.law_type = guess_law_type(doc.name)
    return doc


def _finalize(doc: LawDoc):
    def clean(u: Unit):
        txt, tag = strip_tail_tags(u.text.strip())
        u.text = txt
        if tag:
            u.history = (u.history + " " + tag).strip()
        for c in u.children:
            clean(c)
    for u in doc.body:
        clean(u)
    for ad in doc.addenda:
        ad.text = ad.text.strip()
        for u in ad.units:
            clean(u)
    for ap in doc.appendices:
        ap.text = ap.text.strip()


def guess_law_type(name: str) -> str:
    n = name.replace(" ", "")
    for t in ["시행규칙", "시행령", "시행내규", "조례", "정관", "내규", "지침", "규칙", "규정", "훈령", "예규", "고시"]:
        if n.endswith(t):
            return {"시행령": "대통령령", "시행규칙": "부령"}.get(t, t)
    if n.endswith("법") or n.endswith("법률"):
        return "법률"
    return "규정"


__all__ = ["parse_text", "strip_tail_tags", "join_lines", "guess_law_type", "LAW_TYPES"]
