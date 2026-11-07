"""규정집 체계 분석 — 상·하위 관계, 개정 영향 분석, 상충 검사.

체계(위가 상위):
  국가 법령(지방공기업법 등) > 조례 > 정관 > 규정 > 시행내규·내규 > 지침
  같은 분류코드 앞자리: 0202 인사규정 → 020201 인사규정 시행내규
연결 근거:
  1) 분류코드 상·하위  2) 명시적 인용(「…」, '규정 제17조', '정관 제6조')
  3) 내용 유사도(같은 주제의 조문)  4) 같은 문구·용어 사용
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..core.model import LawDoc, Unit
from ..core.refs import extract_refs, find_abbreviations, iter_text_units, RE_LAWNAME
from ..core.render import render_unit
from .regbook import RegBook, RegEntry, _norm

RANK = {"법률": 0, "대통령령": 0, "총리령": 0, "부령": 0, "조례": 1, "규칙": 1, "정관": 2,
        "규정": 3, "강령": 3, "시행내규": 4, "내규": 4, "지침": 5, "세칙": 5, "요령": 5, "기준": 5}


def rank_of(e: RegEntry) -> int:
    n = _norm(e.name)
    for k in ("시행내규", "내규", "조례", "정관", "강령", "지침", "세칙", "요령", "기준", "규칙", "규정"):
        if n.endswith(k):
            return RANK[k]
    return 3


# ---------------------------------------------------------------- 텍스트 유사도
def _grams(text: str) -> Counter:
    t = re.sub(r"[^가-힣A-Za-z0-9]", "", text)
    return Counter(t[i:i + 2] for i in range(len(t) - 1))


STOP_GRAMS = {"한다", "하여", "에는", "있다", "에서", "하는", "으로", "이다", "사항", "경우", "따라", "다음", "각호", "규정",
              "공사", "에게", "한경", "을받", "하고", "이나", "또는", "하며", "제1", "제2", "제3", "는다", "니한", "아니"}


@dataclass
class ArticleRef:
    code: str
    reg: str
    art: Unit
    label: str
    text: str
    vec: dict = field(default_factory=dict)
    norm: float = 0.0


class Corpus:
    """규정집 전체 조문 색인."""

    def __init__(self, book: RegBook):
        self.book = book
        self.items: list[ArticleRef] = []
        self.by_code: dict[str, list[ArticleRef]] = defaultdict(list)
        df: Counter = Counter()
        raw = []
        for e in book.entries:
            if e.doc is None:
                continue
            for a in e.doc.articles():
                if a.deleted:
                    continue
                txt = "\n".join(render_unit(a, False))
                g = _grams(a.title * 3 + " " + txt)
                for k in list(g):
                    if k in STOP_GRAMS:
                        del g[k]
                raw.append((e, a, txt, g))
                df.update(g.keys())
        N = max(1, len(raw))
        self.idf = {k: math.log(N / (1 + v)) + 1 for k, v in df.items()}
        for e, a, txt, g in raw:
            vec = {k: (1 + math.log(c)) * self.idf[k] for k, c in g.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            ar = ArticleRef(e.code, e.name, a, a.heading(), txt, vec, norm)
            self.items.append(ar)
            self.by_code[e.code].append(ar)

    def vec_of(self, text: str) -> tuple[dict, float]:
        g = _grams(text)
        vec = {k: (1 + math.log(c)) * self.idf.get(k, 1.0) for k, c in g.items() if k not in STOP_GRAMS}
        return vec, math.sqrt(sum(v * v for v in vec.values())) or 1.0

    @staticmethod
    def cos(v1, n1, v2, n2) -> float:
        if len(v1) > len(v2):
            v1, v2 = v2, v1
        return sum(w * v2.get(k, 0.0) for k, w in v1.items()) / (n1 * n2)

    def similar(self, text: str, codes: set[str] | None = None, top: int = 10, min_score: float = 0.25,
                exclude: Unit | None = None) -> list[tuple[float, ArticleRef]]:
        v, n = self.vec_of(text)
        out = []
        pool = self.items if codes is None else [x for c in codes for x in self.by_code.get(c, [])]
        for it in pool:
            if exclude is not None and it.art is exclude:
                continue
            s = self.cos(v, n, it.vec, it.norm)
            if s >= min_score:
                out.append((s, it))
        out.sort(key=lambda x: -x[0])
        return out[:top]


# ---------------------------------------------------------------- 인용 그래프
@dataclass
class Link:
    src_code: str
    src_label: str          # 제3조제1항
    src_uid: str
    dst_code: str           # '' 이면 외부 법령
    dst_name: str
    article: int = 0
    branch: int = 0
    para: int = 0
    item: int = 0
    text: str = ""
    external: bool = False


class RegGraph:
    def __init__(self, book: RegBook):
        self.book = book
        self.entries = {e.code: e for e in book.entries if e.code}
        self.links: list[Link] = []
        self.external_laws: Counter = Counter()
        self._name_index = self._build_name_index()
        self._build()

    # 규정 이름 → 코드 (짧은 이름 포함)
    def _build_name_index(self) -> list[tuple[str, str]]:
        idx = []
        for e in self.book.entries:
            if not e.code:
                continue
            n = _norm(e.name)
            idx.append((n, e.code))
        idx.sort(key=lambda x: -len(x[0]))
        return idx

    def resolve_name(self, name: str, src: RegEntry | None = None) -> str:
        n = _norm(name)
        if not n:
            return ""
        if src is not None:
            # 종류 이름만 쓴 경우: 자기 자신('시행내규 제57조'), 상위 규정('규정 제17조')
            if n in ("시행내규", "내규", "이내규", "이시행내규") and rank_of(src) >= 4:
                return src.code
            if n in ("규칙", "지침", "강령", "행동강령") and _norm(src.name).endswith(n):
                return src.code
            # 시행내규의 '규정' = 같은 분류의 상위 규정, '정관', '조례'
            if n in ("규정", "본규정") and rank_of(src) >= 4 and src.parent_code in self.entries:
                return src.parent_code
            if n in ("규정", "이규정"):
                return ""
        if n in ("정관",):
            return next((c for c, e in self.entries.items() if _norm(e.name).endswith("정관")), "")
        if n in ("조례", "설립조례", "설립및운영조례"):
            return next((c for c, e in self.entries.items() if _norm(e.name).endswith("조례")), "")
        for full, code in self._name_index:
            if n == full:
                return code
        for full, code in self._name_index:
            if len(n) >= 3 and (full.endswith(n) or n.endswith(full)):
                return code
        return ""

    def _build(self):
        for e in self.book.entries:
            if e.doc is None or not e.code:
                continue
            full = "\n".join(u.text for u, _, _ in iter_text_units(e.doc))
            abbrs = find_abbreviations(full)
            last_law = ""
            for r in extract_refs(e.doc):
                if not r.target:
                    continue
                name = r.target
                # '같은 법 시행령', '법 시행령' 처럼 '시행령'만 남은 경우 → 바로 앞에 인용한 법률의 시행령
                mm = re.fullmatch(r"(?:동법|같은법|동\s*법|같은\s*법)\s*(시행령|시행규칙)", name)
                if mm:
                    name = mm.group(1)
                if name in ("시행령", "시행규칙", "영", "규칙") and last_law:
                    name = re.sub(r"\s*(시행령|시행규칙)$", "", last_law) + (" 시행규칙" if name in ("시행규칙", "규칙") else " 시행령")
                elif re.search(r"(법|법률)$", name) and "도시공사" not in name:
                    last_law = name
                if name.startswith("이 ") or len(name) > 60:
                    continue
                code = self.resolve_name(name, e)
                ext = not code
                if ext:
                    # 같은 공사 규정인데 못 찾은 경우와 국가 법령 구분
                    if re.search(r"(법|법률|령|규칙)$", name) and "도시공사" not in name and name not in ("시행령", "시행규칙", "법", "영"):
                        self.external_laws[name] += 1
                self.links.append(Link(e.code, r.src_label, r.src_uid, code, name, r.article, r.article_branch,
                                       r.para, r.item, r.text, ext))
            # 조문 번호 없이 이름만 인용: 「안양도시공사 기간제 … 인사규정」을 적용한다
            for u, art, para in iter_text_units(e.doc):
                for m in RE_LAWNAME.finditer(u.text):
                    nm = m.group(1)
                    if nm.startswith("이 ") or len(nm.split()) > 10:
                        continue
                    code = self.resolve_name(nm, e)
                    after = u.text[m.end():m.end() + 6]
                    if re.match(r"\s*(?:\([^)]*\))?\s*제\s*\d+\s*조", after):
                        continue    # 조문 인용은 위에서 처리
                    if code and code != e.code:
                        self.links.append(Link(e.code, art.number_label() if art else "", u.uid, code, nm, text=m.group(0)))
                    elif not code and not ("도시공사" in nm):
                        self.external_laws[nm] += 1

    # ---- 체계 ----
    def parent(self, code: str) -> str:
        e = self.entries.get(code)
        if not e:
            return ""
        if e.parent_code in self.entries:
            return e.parent_code
        r = rank_of(e)
        if r >= 3:      # 규정 → 정관
            return next((c for c, x in self.entries.items() if rank_of(x) == 2), "")
        if r == 2:      # 정관 → 조례
            return next((c for c, x in self.entries.items() if rank_of(x) == 1), "")
        return ""

    def ancestors(self, code: str) -> list[str]:
        out = []
        p = self.parent(code)
        while p and p not in out:
            out.append(p)
            p = self.parent(p)
        return out

    def children(self, code: str) -> list[str]:
        return [c for c in self.entries if self.parent(c) == code]

    def descendants(self, code: str) -> list[str]:
        out = []
        stack = self.children(code)
        while stack:
            c = stack.pop(0)
            if c not in out:
                out.append(c)
                stack.extend(self.children(c))
        return out

    def tree(self) -> list[tuple[int, str]]:
        """(깊이, 코드) — 화면 표시용."""
        roots = [c for c in self.entries if not self.parent(c)]
        out = []

        def walk(c, d):
            out.append((d, c))
            for ch in sorted(self.children(c)):
                walk(ch, d + 1)
        for r in sorted(roots):
            walk(r, 0)
        return out

    def links_into(self, code: str, article: int = 0, branch: int = 0) -> list[Link]:
        return [l for l in self.links if l.dst_code == code and (not article or (l.article, l.branch) == (article, branch))]

    def links_from(self, code: str, src_article_label: str = "") -> list[Link]:
        return [l for l in self.links if l.src_code == code and (not src_article_label or l.src_label.startswith(src_article_label))]


RE_BODY_NAME = re.compile(r"([가-힣]{2,12}(?:위원회|심의회|협의회|평의회|심사회|위원단))")


def _bodies(text: str) -> set[str]:
    return {m.group(1) for m in RE_BODY_NAME.finditer(text) if m.group(1) not in ("위원회",)}



# ---------------------------------------------------------------- 영향 분석
@dataclass
class Impact:
    direction: str      # 상위 / 하위 / 관련 / 외부법령
    code: str
    reg: str
    label: str          # 조문
    reason: str
    score: float
    snippet: str = ""
    uid: str = ""


def _art_label_of(label: str) -> str:
    m = re.match(r"^(제\d+조(?:의\d+)?)", label)
    return m.group(1) if m else label


def _direction(graph: RegGraph, base: str, other: str) -> str:
    if other in graph.ancestors(base):
        return "상위"
    if other in graph.descendants(base):
        return "하위"
    eb, eo = graph.entries.get(base), graph.entries.get(other)
    if eb and eo:
        rb, ro = rank_of(eb), rank_of(eo)
        if ro < rb:
            return "상위"
        if ro > rb:
            return "하위"
    return "관련"


def changed_phrases(old_text: str, new_text: str) -> list[str]:
    """바뀌는 현행 문구 중 다른 규정에서 찾아볼 만한 것(명칭·용어). 숫자만 다른 경우는 제외."""
    from ..core.amend import phrase_changes
    out = []
    for o, n in phrase_changes(old_text, new_text):
        cands = [o.strip()] + re.findall(r"[가-힣A-Za-z·ㆍ]{3,}", o)
        for w in cands:
            core = re.sub(r"\d+|[^가-힣A-Za-z]|명|인|년|개월|월|일|원|이상|이하|이내|초과|미만|부터|까지", "", w)
            if len(core) < 3:
                continue
            if w in n:            # 그대로 남는 낱말은 제외
                continue
            if w not in out:
                out.append(w)
    return out


def analyze_impact(book: RegBook, graph: RegGraph, corpus: Corpus, code: str, article_keys: list[tuple[int, int]] | None = None,
                   old_text: str = "", new_text: str = "", sim_threshold: float = 0.22) -> list[Impact]:
    """code 규정(특정 조문들)을 바꿀 때 함께 봐야 할 조문."""
    e = graph.entries.get(code)
    if e is None or e.doc is None:
        return []
    arts = [a for a in e.doc.articles() if not a.deleted]
    if article_keys:
        arts = [a for a in arts if (a.num, a.branch) in set(article_keys)]
    out: dict[tuple[str, str, str], Impact] = {}

    def add(imp: Impact):
        k = (imp.code, imp.label, imp.reason.split(":")[0])
        if k not in out or out[k].score < imp.score:
            out[k] = imp

    related = set(graph.ancestors(code)) | set(graph.descendants(code)) | set(graph.children(graph.parent(code)))
    related.discard(code)
    entry_name = {c: x.name for c, x in graph.entries.items()}
    for a in arts:
        alabel = a.number_label()
        # 1) 이 조문을 인용하는 다른 규정 조문
        for l in graph.links_into(code, a.num, a.branch):
            if l.src_code == code:
                continue
            src = graph.entries[l.src_code]
            u = src.doc.find_uid(l.src_uid)
            add(Impact(_direction(graph, code, l.src_code), l.src_code, entry_name[l.src_code], l.src_label,
                       f"명시적 인용: {l.text}가 {alabel}을(를) 가리킴", 1.0, (u.text if u else "")[:160], l.src_uid))
        # 2) 이 조문이 인용하는 상위·다른 규정 / 외부 법령
        for l in graph.links_from(code, alabel):
            if l.dst_code and l.dst_code != code:
                tgt = graph.entries[l.dst_code]
                ta = tgt.doc.find_article(l.article, l.branch) if l.article else None
                add(Impact(_direction(graph, code, l.dst_code), l.dst_code, entry_name[l.dst_code],
                           ta.number_label() if ta else "(규정 전체)", f"근거·인용: {l.src_label}이(가) {l.text} 인용",
                           0.95, ("\n".join(render_unit(ta, False)) if ta else "")[:160], ta.uid if ta else ""))
            elif l.external:
                add(Impact("외부법령", "", l.dst_name, f"제{l.article}조" if l.article else "", f"상위 법령 인용: {l.src_label}",
                           0.9, l.text))
        # 3) 같은 주제의 조문(상·하위 규정 우선)
        txt = "\n".join(render_unit(a, False))
        my_bodies = _bodies(a.title + " " + txt)
        for s, it in corpus.similar(a.title * 3 + " " + txt, codes=related, top=6, min_score=sim_threshold, exclude=a):
            ob = _bodies(it.art.title + " " + it.text)
            if my_bodies and ob and not (my_bodies & ob):
                continue
            add(Impact(_direction(graph, code, it.code), it.code, it.reg, it.art.number_label(),
                       f"내용 유사({s:.2f}): {alabel}({a.title})와 같은 주제", round(s, 3), it.text[:160], it.art.uid))
        for s, it in corpus.similar(a.title * 3 + " " + txt, codes=None, top=4, min_score=max(sim_threshold + 0.16, 0.38), exclude=a):
            if it.code in related or it.code == code:
                continue
            ob = _bodies(it.art.title + " " + it.text)
            if my_bodies and ob and not (my_bodies & ob):
                continue
            add(Impact(_direction(graph, code, it.code), it.code, it.reg, it.art.number_label(),
                       f"내용 유사({s:.2f}): {alabel}({a.title})와 같은 주제", round(s * 0.9, 3), it.text[:160], it.art.uid))
        # 3-2) 이 조문이 설치·규정하는 기구(인사위원회 등)를 언급하는 다른 규정 조문
        defined = {b for b in my_bodies if b in a.title or re.search(re.escape(b) + r"[^가-힣]{0,3}(?:를|을)\s*(?:둔다|설치)", txt)}
        for b in defined:
            hits = [it for it in corpus.items if it.code != code and b in it.text]
            hits.sort(key=lambda it: (it.code not in related, it.code))
            for it in hits[:15]:
                k = it.text.find(b)
                add(Impact(_direction(graph, code, it.code), it.code, it.reg, it.art.number_label(),
                           f"같은 기구 언급: “{b}”", 0.8 if it.code in related else 0.6, it.text[max(0, k - 40):k + 80], it.art.uid))
    # 4) 바뀌는 문구가 다른 규정에도 쓰인 곳 (명칭 변경 전파)
    if old_text and new_text:
        for w in changed_phrases(old_text, new_text)[:12]:
            for it in corpus.items:
                if it.code == code:
                    continue
                if w in it.text:
                    k = it.text.find(w)
                    add(Impact(_direction(graph, code, it.code), it.code, it.reg, it.art.number_label(),
                               f"같은 문구 사용: “{w}”", 0.85, it.text[max(0, k - 40):k + 80], it.art.uid))
    res = sorted(out.values(), key=lambda x: ({"상위": 0, "하위": 1, "관련": 2, "외부법령": 3}[x.direction], -x.score))
    return res


# ---------------------------------------------------------------- 상충 검사
UNIT_NORM = {"인": "명", "명": "명", "년": "년", "개월": "개월", "월": "개월", "일": "일", "시간": "시간", "원": "원",
             "만원": "만원", "억원": "억원", "%": "%", "퍼센트": "%", "배": "배", "회": "회", "급": "급", "세": "세", "호봉": "호봉",
             "주": "주", "분": "분", "개": "개"}
RE_FACT = re.compile(
    r"(?P<num>\d[\d,]*(?:\.\d+)?|100분의\s*\d+|[일이삼사오육칠팔구십]+)\s*"
    r"(?P<unit>개월|시간|만원|억원|퍼센트|호봉|명|인|년|월|일|원|%|배|회|급|세|주|분|개)"
    r"(?P<qual>\s*(?:이상|이하|이내|초과|미만|전|후|까지|부터|마다))?")
KOR_NUM = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9, "십": 10}


@dataclass
class Fact:
    obj: str            # 숫자 뒤에서 세는 대상: '10명 이내의 이사' → 이사
    subject: str
    value: float
    unit: str
    qual: str
    text: str
    pos: int


def _num(s: str) -> float | None:
    s = s.replace(",", "").replace(" ", "")
    if s.startswith("100분의"):
        return float(s[4:])
    try:
        return float(s)
    except ValueError:
        if all(c in KOR_NUM for c in s):
            if s == "십":
                return 10
            return float(KOR_NUM.get(s, 0)) if len(s) == 1 else None
        return None


def _subject(text: str, pos: int) -> str:
    before = text[max(0, pos - 30):pos]
    before = re.split(r"[.,;:)\]」]|다만|및|또는", before)[-1]
    words = re.findall(r"[가-힣]{2,}", before)
    stop = {"이상", "이하", "이내", "이를", "그", "다음", "각", "해당", "경우", "때에는", "때", "이", "포함하여", "포함한", "범위에서",
            "동안", "기간", "까지", "부터"}
    words = [w for w in words if w not in stop]
    return " ".join(words[-3:])


def extract_facts(text: str) -> list[Fact]:
    out = []
    for m in RE_FACT.finditer(text):
        # 조·항·호 번호, 날짜, 금액 단위 앞 숫자는 제외
        pre = text[max(0, m.start() - 1):m.start()]
        if pre == "제" or re.match(r"\d{4}\.", text[m.start():m.start() + 5]):
            continue
        unit = m.group("unit")
        nxt = text[m.end():m.end() + 1]
        if unit in ("일", "월") and nxt in ("부", "자") or unit == "일" and re.match(r"\s*\d", text[m.end():m.end() + 2]):
            pass
        if unit == "급" and not re.search(r"(직원|직급|급\s*이상|급\s*이하|급\s*직원)", text[m.start():m.end() + 6]):
            pass
        v = _num(m.group("num"))
        if v is None:
            continue
        num = m.group("num")
        u = UNIT_NORM.get(unit, unit)
        if num.startswith("100분의"):
            u = "%"
        after = text[m.end():m.end() + 14]
        mo = re.match(r"\s*(?:의|인|씩)?\s*([가-힣]{2,8}?)(?:와|과|을|를|이|가|은|는|으로|로|에|및|,|\s|$)", after)
        obj = mo.group(1) if mo else ""
        if obj in ("범위", "기간", "경우", "때", "이내", "이상", "이하", "동안", "전까지", "전", "후", "까지", "부터", "이후"):
            obj = ""
        out.append(Fact(obj, _subject(text, m.start()), v, u, (m.group("qual") or "").strip(), m.group(0), m.start()))
    return out


def _subj_sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ga, gb = set(_grams(a)), set(_grams(b))
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


@dataclass
class Conflict:
    kind: str           # 수치 불일치 / 인용 오류 / 폐지 규정 인용 / 상위 개정 미반영 / 명칭 불일치 / 상위법 확인
    severity: str       # 높음 / 중간 / 낮음
    a_code: str
    a_reg: str
    a_label: str
    a_text: str
    b_code: str
    b_reg: str
    b_label: str
    b_text: str
    detail: str
    a_uid: str = ""
    b_uid: str = ""


def _fact_conflicts(x: ArticleRef, y: ArticleRef, direction: str) -> list[str]:
    bx, by = _bodies(x.art.title + " " + x.text), _bodies(y.art.title + " " + y.text)
    if bx and by and not (bx & by):
        return []           # 서로 다른 위원회 이야기
    fx, fy = extract_facts(x.text), extract_facts(y.text)
    msgs = []
    for a in fx:
        for b in fy:
            if a.unit != b.unit:
                continue
            if a.obj and b.obj:
                if a.obj != b.obj:
                    continue
                if _subj_sim(a.subject, b.subject) < 0.2 and not (set(a.subject.split()) & set(b.subject.split())):
                    continue
            elif _subj_sim(a.subject, b.subject) < 0.5:
                continue
            if a.value == b.value and a.qual == b.qual:
                continue
            # 이상/이내 범위가 포함 관계면 하위가 상위 범위 안인지
            if a.value == b.value and {a.qual, b.qual} <= {"이내", "이하", ""}:
                continue
            what = a.obj or a.subject
            msgs.append(f"‘{what}’: {a.text.strip()} ↔ {b.text.strip()}")
    return list(dict.fromkeys(msgs))


def _latest_date(hist: list[str] | str) -> str:
    text = " ".join(hist) if isinstance(hist, list) else hist
    ds = re.findall(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})", text)
    return max((f"{y}{int(m):02d}{int(d):02d}" for y, m, d in ds), default="")


def _unit_latest(u: Unit) -> str:
    return max((_latest_date(x.history) for x in u.iter()), default="")


def find_conflicts(book: RegBook, graph: RegGraph, corpus: Corpus, codes: list[str] | None = None,
                   sim_threshold: float = 0.3, progress=None) -> list[Conflict]:
    out: list[Conflict] = []
    target_codes = codes or [c for c in graph.entries]
    names = {c: e.name for c, e in graph.entries.items()}
    # 1) 인용 오류 / 폐지 규정 인용 / 상위 개정 미반영
    for l in graph.links:
        if l.src_code not in target_codes:
            continue
        src = graph.entries[l.src_code]
        u = src.doc.find_uid(l.src_uid)
        stext = u.text if u else ""
        if l.dst_code:
            dst = graph.entries[l.dst_code]
            if dst.repealed:
                out.append(Conflict("폐지 규정 인용", "높음", l.src_code, names[l.src_code], l.src_label, stext,
                                    l.dst_code, names[l.dst_code], "", "", f"폐지된 규정을 인용합니다: {l.text}", l.src_uid))
                continue
            if l.article:
                ta = dst.doc.find_article(l.article, l.branch)
                if ta is None:
                    out.append(Conflict("인용 오류", "높음", l.src_code, names[l.src_code], l.src_label, stext,
                                        l.dst_code, names[l.dst_code], f"제{l.article}조", "",
                                        f"{names[l.dst_code]}에 없는 조문을 인용합니다: {l.text}", l.src_uid))
                    continue
                if ta.deleted:
                    out.append(Conflict("인용 오류", "높음", l.src_code, names[l.src_code], l.src_label, stext,
                                        l.dst_code, names[l.dst_code], ta.number_label(), "",
                                        f"삭제된 조문을 인용합니다: {names[l.dst_code]} {l.text}", l.src_uid, ta.uid))
                    continue
                if l.para and not any(c.kind == "paragraph" and c.num == l.para for c in ta.children):
                    out.append(Conflict("인용 오류", "중간", l.src_code, names[l.src_code], l.src_label, stext,
                                        l.dst_code, names[l.dst_code], ta.number_label(), "\n".join(render_unit(ta, False))[:300],
                                        f"{names[l.dst_code]} {ta.number_label()}에 제{l.para}항이 없습니다: {l.text}", l.src_uid, ta.uid))
                # 상위 조문이 하위 규정의 최종 개정 이후 바뀜
                up_date = _unit_latest(ta)
                low_date = _latest_date(src.doc.history)
                if up_date and low_date and up_date > low_date and rank_of(dst) < rank_of(src):
                    out.append(Conflict("상위 개정 미반영", "낮음", l.src_code, names[l.src_code], l.src_label, stext,
                                        l.dst_code, names[l.dst_code], ta.number_label(), "\n".join(render_unit(ta, False))[:300],
                                        f"인용한 상위 조문이 {up_date[:4]}.{up_date[4:6]}.{up_date[6:]}에 개정됐지만 "
                                        f"이 규정의 최종 개정은 {low_date[:4]}.{low_date[4:6]}.{low_date[6:]}입니다. 반영 여부를 확인하세요.",
                                        l.src_uid, ta.uid))
        elif l.external and re.search(r"도시공사", l.dst_name):
            out.append(Conflict("인용 오류", "중간", l.src_code, names[l.src_code], l.src_label, stext, "", l.dst_name, "", "",
                                f"규정집에 없는 공사 규정을 인용합니다(명칭 변경·폐지 확인): 「{l.dst_name}」", l.src_uid))
    # 2) 수치 불일치 — 상·하위/인용 관계 규정의 같은 주제 조문
    pairs_done = set()
    tc = [c for c in target_codes if c in graph.entries]
    for i, code in enumerate(tc):
        if progress:
            progress(i, len(tc))
        rel = set(graph.ancestors(code)) | set(graph.descendants(code)) | {l.dst_code for l in graph.links_from(code) if l.dst_code}
        rel |= {code}
        for x in corpus.by_code.get(code, []):
            if not extract_facts(x.text):
                continue
            for s, y in corpus.similar(x.art.title * 3 + " " + x.text, codes=rel, top=8, min_score=sim_threshold, exclude=x.art):
                key = tuple(sorted([id(x.art), id(y.art)]))
                if key in pairs_done:
                    continue
                pairs_done.add(key)
                msgs = _fact_conflicts(x, y, "")
                if msgs:
                    same = y.code == code
                    out.append(Conflict("수치 불일치", "중간" if not same else "낮음", x.code, x.reg, x.art.number_label(), x.text[:400],
                                        y.code, y.reg, y.art.number_label(), y.text[:400],
                                        f"같은 주제(유사도 {s:.2f})의 조문에서 수치가 다릅니다 — " + "; ".join(msgs[:3]),
                                        x.art.uid, y.art.uid))
    # 3) 조직 명칭: 직제규정에 없는 부서·직위 명칭
    out.extend(_org_name_conflicts(book, graph, target_codes))
    sev = {"높음": 0, "중간": 1, "낮음": 2}
    out.sort(key=lambda c: (sev[c.severity], c.kind, c.a_code))
    return out


RE_ORG = re.compile(r"(?<![가-힣])([가-힣]{2,10}(?:본부|팀|센터|사업단|사업소))(?:장)?(?![가-힣])")


def _org_name_conflicts(book: RegBook, graph: RegGraph, target_codes) -> list[Conflict]:
    jik = next((e for e in book.entries if _norm(e.name).endswith("직제규정")), None)
    if jik is None or jik.doc is None:
        return []
    jtext = "\n".join(u.text + " " + u.title for u, _, _ in iter_text_units(jik.doc)) + "\n" + \
            "\n".join(a.title + " " + a.text for a in jik.doc.appendices)
    known = set(m.group(1) for m in RE_ORG.finditer(jtext))
    generic = {"사업단", "각 본부", "해당팀", "담당팀", "소관팀", "관련팀", "주관팀", "전담팀", "해당본부", "관련본부", "각본부", "각팀",
               "고객센터", "콜센터", "지원센터", "상담센터", "본부", "센터"}
    out = []
    seen = set()
    for e in book.entries:
        if e.code not in target_codes or e.doc is None or e is jik:
            continue
        for u, art, para in iter_text_units(e.doc):
            for m in RE_ORG.finditer(u.text):
                nm = m.group(1)
                if nm in known or nm in generic or any(nm.endswith(g) and len(nm) <= len(g) + 1 for g in generic):
                    continue
                if (e.code, nm) in seen:
                    continue
                seen.add((e.code, nm))
                out.append(Conflict("명칭 불일치", "낮음", e.code, e.name, art.number_label() if art else "", u.text[:300],
                                    jik.code, jik.name, "", "", f"직제규정에 없는 조직 명칭 “{nm}” — 조직 개편 반영 여부 확인", u.uid))
    return out


def regulation_summary(graph: RegGraph, code: str) -> dict:
    e = graph.entries[code]
    return {
        "code": code, "name": e.name, "rank": rank_of(e), "dept": e.dept,
        "upper": [(c, graph.entries[c].name) for c in graph.ancestors(code)],
        "lower": [(c, graph.entries[c].name) for c in graph.descendants(code)],
        "cites": sorted({(l.dst_code, graph.entries[l.dst_code].name) for l in graph.links_from(code) if l.dst_code and l.dst_code != code}),
        "cited_by": sorted({(l.src_code, graph.entries[l.src_code].name) for l in graph.links_into(code) if l.src_code != code}),
        "laws": sorted({l.dst_name for l in graph.links_from(code) if l.external}),
        "history": e.doc.history if e.doc else [],
    }


# ---------------------------------------------------------------- 상위법(국가법령·자치법규) 대조
def check_external(book: RegBook, graph: RegGraph, api, codes: list[str] | None = None, progress=None,
                   max_laws: int = 60) -> list[Conflict]:
    """규정이 인용한 국가 법령 조문을 법령 API 로 가져와 대조한다."""
    from ..core.render import render_unit as _ru
    out: list[Conflict] = []
    target_codes = set(codes or graph.entries)
    names = {c: e.name for c, e in graph.entries.items()}
    ext_links = [l for l in graph.links if l.external and l.src_code in target_codes and l.dst_name
                 and not re.search(r"도시공사", l.dst_name) and l.dst_name not in ("시행령", "시행규칙", "법", "영", "규칙")]
    law_names = list(dict.fromkeys(l.dst_name for l in ext_links))[:max_laws]
    docs: dict[str, LawDoc | None] = {}
    for i, nm in enumerate(law_names):
        if progress:
            progress(i, len(law_names))
        try:
            hit = api.find_law(nm)
            docs[nm] = api.fetch_doc(hit) if hit else None
        except Exception as ex:      # 네트워크 오류 등은 건너뛰고 기록
            docs[nm] = None
            out.append(Conflict("상위법 확인", "낮음", "", "", "", "", "", nm, "", "", f"법령 조회 실패: {ex}"))
            continue
        if docs[nm] is None:
            first = next(l for l in ext_links if l.dst_name == nm)
            is_law = bool(re.search(r"(법|법률|시행령|시행규칙)$", nm))
            sug = api.suggest_name(nm) if is_law else ""
            msg = (f"「{nm}」은(는) 현행 법령에 없습니다. 법령명이 「{sug}」(으)로 바뀐 것으로 보입니다." if sug else
                   f"「{nm}」을(를) 국가법령정보에서 찾지 못했습니다(법령명 변경·폐지 여부 확인).")
            out.append(Conflict("상위법 확인", "중간" if is_law else "낮음", first.src_code, names.get(first.src_code, ""),
                                first.src_label, "", "", nm, "", "", msg, first.src_uid))
    seen = set()
    for l in ext_links:
        doc = docs.get(l.dst_name)
        if doc is None or not l.article:
            continue
        key = (l.src_code, l.src_label, l.dst_name, l.article, l.branch, l.para)
        if key in seen:
            continue
        seen.add(key)
        src = graph.entries[l.src_code]
        u = src.doc.find_uid(l.src_uid)
        stext = u.text if u else ""
        ta = doc.find_article(l.article, l.branch)
        lab = f"제{l.article}조" + (f"의{l.branch}" if l.branch else "")
        if ta is None:
            out.append(Conflict("상위법 인용 오류", "높음", l.src_code, names[l.src_code], l.src_label, stext, "", doc.name, lab, "",
                                f"「{doc.name}」에 {lab}이(가) 없습니다(조문 이동·삭제 확인).", l.src_uid))
            continue
        ttext = "\n".join(_ru(ta, False))
        if ta.deleted:
            out.append(Conflict("상위법 인용 오류", "높음", l.src_code, names[l.src_code], l.src_label, stext, "", doc.name, lab,
                                ttext, f"「{doc.name}」 {lab}은(는) 삭제된 조문입니다.", l.src_uid))
            continue
        if l.para and not any(c.kind == "paragraph" and c.num == l.para for c in ta.children):
            out.append(Conflict("상위법 인용 오류", "중간", l.src_code, names[l.src_code], l.src_label, stext, "", doc.name, lab,
                                ttext[:400], f"「{doc.name}」 {lab}에 제{l.para}항이 없습니다.", l.src_uid))
        # 수치 대조 (우리 조문 전체 ↔ 상위법 조문)
        art = src.doc.find_article(*_key(l.src_label))
        if art is not None:
            x = ArticleRef(l.src_code, names[l.src_code], art, art.heading(), "\n".join(_ru(art, False)))
            y = ArticleRef("", doc.name, ta, ta.heading(), ttext)
            msgs = _fact_conflicts(x, y, "")
            if msgs:
                out.append(Conflict("상위법 수치 확인", "중간", l.src_code, names[l.src_code], art.number_label(), x.text[:400],
                                    "", doc.name, lab, ttext[:400], "인용한 상위법 조문과 수치가 다릅니다 — " + "; ".join(msgs[:3]),
                                    art.uid))
    return out


def _key(label: str) -> tuple[int, int]:
    m = re.match(r"제(\d+)조(?:의(\d+))?", label or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def compare_with_official(entry: RegEntry, api) -> tuple[LawDoc | None, list]:
    """규정집에 실린 조례 등을 법령정보 현행본과 비교 → (현행본, 변경목록)."""
    from ..core.amend import compare
    hit = api.find_law(entry.name)
    if hit is None:
        return None, []
    off = api.fetch_doc(hit)
    sq = lambda t: re.sub(r"[\s‘’“”\"']", "", t or "")
    out = []
    for c in compare(entry.doc, off):
        if c.kind == "phrase":
            c.phrases = [(o, n) for o, n in c.phrases if sq(o) != sq(n)]
            if not c.phrases:
                continue
        if c.kind == "whole" and c.old_unit is not None and c.new_unit is not None and sq(c.old_unit.plain()) == sq(c.new_unit.plain()):
            continue
        out.append(c)
    return off, out
