"""법령 문서 모델.

법령은 편·장·절·관(구획) 아래 조, 조 아래 항·호·목으로 구성된다.
부칙과 별표·서식은 본칙과 분리해 보관한다.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, asdict

# 구획(heading) 종류와 단계
DIVISIONS = ["part", "chapter", "section", "subsection"]          # 편 장 절 관
DIVISION_LABEL = {"part": "편", "chapter": "장", "section": "절", "subsection": "관"}
LABEL_DIVISION = {v: k for k, v in DIVISION_LABEL.items()}

# 조문 내부 단계
UNIT_KINDS = ["article", "paragraph", "item", "subitem"]           # 조 항 호 목
UNIT_LABEL = {"article": "조", "paragraph": "항", "item": "호", "subitem": "목"}

LAW_TYPES = ["법률", "대통령령", "총리령", "부령", "조례", "규칙", "정관", "규정", "시행내규", "내규", "지침", "훈령", "예규", "고시"]
AMEND_TYPES = ["제정", "일부개정", "전부개정", "폐지", "폐지제정"]

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿"
HANGUL_ITEMS = "가나다라마바사아자차카타파하"


def circled(n: int) -> str:
    return CIRCLED[n - 1] if 1 <= n <= len(CIRCLED) else f"({n})"


def uncircle(ch: str) -> int:
    i = CIRCLED.find(ch)
    return i + 1 if i >= 0 else 0


def subitem_label(n: int) -> str:
    if 1 <= n <= len(HANGUL_ITEMS):
        return HANGUL_ITEMS[n - 1]
    # 하 다음은 거, 너 ... (법제처 관행) — 충분히 드묾
    extra = "거너더러머버서어저처커터퍼허"
    k = n - len(HANGUL_ITEMS)
    return extra[k - 1] if 1 <= k <= len(extra) else f"{n}"


def subitem_number(label: str) -> int:
    i = HANGUL_ITEMS.find(label)
    if i >= 0:
        return i + 1
    i = "거너더러머버서어저처커터퍼허".find(label)
    return len(HANGUL_ITEMS) + i + 1 if i >= 0 else 0


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Unit:
    """조·항·호·목 또는 편·장·절·관."""
    kind: str                      # article / paragraph / item / subitem / part / chapter ...
    num: int = 0                   # 번호 (항은 원문자 번호)
    branch: int = 0                # 가지번호: 제3조의2 -> num=3, branch=2
    title: str = ""                # 조 제목 또는 장 제목
    text: str = ""                 # 본문
    children: list["Unit"] = field(default_factory=list)
    deleted: bool = False          # "삭제 <2020. 1. 1.>"
    history: str = ""              # 끝에 붙은 <개정 ...> 표기
    uid: str = field(default_factory=new_id)

    # ---- 표시 ----
    def number_label(self) -> str:
        if self.kind == "article":
            return f"제{self.num}조" + (f"의{self.branch}" if self.branch else "")
        if self.kind == "paragraph":
            return circled(self.num)
        if self.kind == "item":
            return f"{self.num}" + (f"의{self.branch}" if self.branch else "") + "."
        if self.kind == "subitem":
            return subitem_label(self.num) + "."
        if self.kind in DIVISION_LABEL:
            return f"제{self.num}{DIVISION_LABEL[self.kind]}" + (f"의{self.branch}" if self.branch else "")
        return ""

    def ref_label(self) -> str:
        """다른 조문에서 인용할 때 쓰는 표기 (제3조, 제2항, 제1호, 가목)."""
        if self.kind == "article":
            return self.number_label()
        if self.kind == "paragraph":
            return f"제{self.num}항"
        if self.kind == "item":
            return f"제{self.num}호" + (f"의{self.branch}" if self.branch else "")
        if self.kind == "subitem":
            return f"{subitem_label(self.num)}목"
        return self.number_label()

    def heading(self) -> str:
        lab = self.number_label()
        if self.kind == "article":
            return lab + (f"({self.title})" if self.title else "")
        if self.kind in DIVISION_LABEL:
            return f"{lab} {self.title}".strip()
        return lab

    def key(self) -> tuple:
        return (self.kind, self.num, self.branch)

    def iter(self):
        yield self
        for c in self.children:
            yield from c.iter()

    def clone(self) -> "Unit":
        return copy.deepcopy(self)

    def plain(self) -> str:
        """하위 포함 전체 텍스트(비교용)."""
        from .render import render_unit
        return "\n".join(render_unit(self))


@dataclass
class Appendix:
    """별표·서식·별지."""
    kind: str = "별표"             # 별표 / 서식 / 별지
    num: int = 1
    branch: int = 0
    title: str = ""
    text: str = ""
    ref: str = ""                  # 관련 조문 (제3조 관련)
    history: str = ""              # <개정 2021. 2. 23.> 등 연혁 표기
    uid: str = field(default_factory=new_id)

    def label(self) -> str:
        b = f"의{self.branch}" if self.branch else ""
        if self.kind == "별지":
            return f"[별지 제{self.num}{b}호서식]"
        return f"[{self.kind} {self.num}{b}]"


@dataclass
class Addendum:
    """부칙 한 덩어리 (<제N호, 2020. 1. 1.>)."""
    header: str = "부칙"
    units: list[Unit] = field(default_factory=list)   # 조 단위 부칙
    text: str = ""                                     # 조 없이 문장만 있는 부칙
    uid: str = field(default_factory=new_id)


@dataclass
class LawDoc:
    name: str = ""
    law_type: str = "규정"
    amend_type: str = "일부개정"
    org: str = ""                  # 소관부서/기관
    history: list[str] = field(default_factory=list)   # 제정·개정 연혁 줄
    body: list[Unit] = field(default_factory=list)     # 최상위: 구획 또는 조
    addenda: list[Addendum] = field(default_factory=list)
    appendices: list[Appendix] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # ---- 탐색 ----
    def articles(self) -> list[Unit]:
        out = []
        for u in self.body:
            for x in u.iter():
                if x.kind == "article":
                    out.append(x)
        return out

    def divisions(self) -> list[Unit]:
        return [x for u in self.body for x in u.iter() if x.kind in DIVISION_LABEL]

    def find_article(self, num: int, branch: int = 0) -> Unit | None:
        for a in self.articles():
            if a.num == num and a.branch == branch:
                return a
        return None

    def find_uid(self, uid: str) -> Unit | None:
        for u in self.body:
            for x in u.iter():
                if x.uid == uid:
                    return x
        for ad in self.addenda:
            for u in ad.units:
                for x in u.iter():
                    if x.uid == uid:
                        return x
        return None

    def parent_of(self, target: Unit) -> tuple[list[Unit], int] | None:
        """target 을 포함하는 리스트와 인덱스."""
        def walk(lst):
            for i, u in enumerate(lst):
                if u is target:
                    return lst, i
                r = walk(u.children)
                if r:
                    return r
            return None
        r = walk(self.body)
        if r:
            return r
        for ad in self.addenda:
            r = walk(ad.units)
            if r:
                return r
        return None

    def clone(self) -> "LawDoc":
        return copy.deepcopy(self)

    # ---- 직렬화 ----
    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "LawDoc":
        def mk_unit(x):
            return Unit(kind=x["kind"], num=x.get("num", 0), branch=x.get("branch", 0),
                        title=x.get("title", ""), text=x.get("text", ""),
                        children=[mk_unit(c) for c in x.get("children", [])],
                        deleted=x.get("deleted", False), history=x.get("history", ""),
                        uid=x.get("uid") or new_id())
        doc = LawDoc(name=d.get("name", ""), law_type=d.get("law_type", "규정"),
                     amend_type=d.get("amend_type", "일부개정"), org=d.get("org", ""),
                     history=list(d.get("history", [])), meta=dict(d.get("meta", {})))
        doc.body = [mk_unit(u) for u in d.get("body", [])]
        doc.addenda = [Addendum(header=a.get("header", "부칙"), units=[mk_unit(u) for u in a.get("units", [])],
                                text=a.get("text", ""), uid=a.get("uid") or new_id())
                       for a in d.get("addenda", [])]
        doc.appendices = [Appendix(**{k: v for k, v in a.items() if k in Appendix.__dataclass_fields__})
                          for a in d.get("appendices", [])]
        return doc
