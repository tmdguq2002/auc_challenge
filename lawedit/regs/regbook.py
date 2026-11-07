"""규정집 PDF → 규정별 LawDoc.

안양도시공사 규정집 형식:
  쪽 머리: '안양도시공사 규정집' / 규정명 / '안양도시공사' / '- n / 전체 -' / 담당부서
  목차(앞쪽): 분류코드(0202, 020201 …) / 규정명 / 쪽번호
분류코드의 앞자리가 같으면 상·하위 관계다 (0202 인사규정 → 020201 인사규정 시행내규).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core.model import LawDoc
from ..core.parser import parse_text, guess_law_type

RE_PAGE_LABEL = re.compile(r"^-\s*(\d+)\s*/\s*(\d+)\s*-$")
RE_PAGE_LABEL_IN = re.compile(r"-\s*(\d+)\s*/\s*(\d+)\s*-")
RE_CODE = re.compile(r"^(\d{2}(?:\d{2}){0,3})$")


@dataclass
class RegEntry:
    code: str = ""
    name: str = ""
    page: int = 0                  # 규정집 쪽번호(인쇄 번호)
    dept: str = ""
    repealed: bool = False
    text: str = ""
    pdf_pages: list[int] = field(default_factory=list)
    doc: LawDoc | None = None

    @property
    def level(self) -> int:
        return len(self.code) // 2 if self.code else 0

    @property
    def parent_code(self) -> str:
        return self.code[:-2] if len(self.code) > 2 else ""


@dataclass
class RegBook:
    title: str = ""
    source: str = ""
    entries: list[RegEntry] = field(default_factory=list)

    def by_code(self, code: str) -> RegEntry | None:
        return next((e for e in self.entries if e.code == code), None)

    def by_name(self, name: str) -> RegEntry | None:
        n = _norm(name)
        for e in self.entries:
            if _norm(e.name) == n:
                return e
        for e in self.entries:
            if _norm(e.name).endswith(n) or n.endswith(_norm(e.name)):
                return e
        return None

    def to_json(self) -> dict:
        from dataclasses import asdict
        return {"title": self.title, "source": self.source,
                "entries": [{**{k: v for k, v in asdict(e).items() if k not in ("doc",)},
                             "doc": e.doc.to_dict() if e.doc else None} for e in self.entries]}

    @staticmethod
    def from_json(d: dict) -> "RegBook":
        rb = RegBook(title=d.get("title", ""), source=d.get("source", ""))
        for x in d.get("entries", []):
            doc = LawDoc.from_dict(x["doc"]) if x.get("doc") else None
            rb.entries.append(RegEntry(code=x.get("code", ""), name=x.get("name", ""), page=x.get("page", 0),
                                       dept=x.get("dept", ""), repealed=x.get("repealed", False), text=x.get("text", ""),
                                       pdf_pages=x.get("pdf_pages", []), doc=doc))
        return rb

    def save(self, path: str | Path):
        Path(path).write_text(json.dumps(self.to_json(), ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "RegBook":
        return RegBook.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def _norm(s: str) -> str:
    s = re.sub(r"[\s·ㆍ・‧․,]+", "", s or "")
    return s.removeprefix("안양도시공사")


REG_SUFFIX = re.compile(r"(규정|내규|조례|정관|강령|규칙|지침|세칙|요령|기준)$")


def _parse_toc(lines: list[str]) -> list[tuple[str, str, int, bool]]:
    """목차 쪽의 줄들 → (코드, 이름, 쪽, 폐지여부).
    한 줄 형식('0202 인사규정 29')과 여러 줄 형식(코드 / 이름 / 쪽) 모두 읽는다."""
    out = []
    one = re.compile(r"^(0\d(?:\d\d){0,3})\s+(.+?)\s+(\d{1,4})$")
    # 이름이 가운뎃점에서 줄바꿈된 경우('040207 상품권 구매' / '사용 및 … 425') 이어 붙인다
    joined = []
    for l in (x.strip() for x in lines):
        if joined and re.match(r"^0\d(?:\d\d){0,3}\s+\S", joined[-1]) and not re.search(r"\s\d{1,4}$", joined[-1]) \
                and not re.match(r"^0\d(?:\d\d){0,3}\s", l):
            joined[-1] = joined[-1] + "·" + l
        else:
            joined.append(l)
    for l in joined:
        m = one.match(l.strip())
        if m:
            name = m.group(2)
            rep = "폐지" in name
            name = re.sub(r"\s*폐지\s*[<〈]?\s*[>〉]?\s*$", "", name).strip()
            out.append((m.group(1), name, int(m.group(3)), rep))
    if out:
        return out
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if RE_CODE.match(s) and len(s) in (2, 4, 6, 8) and (len(s) > 2 or (i + 2 < n)):
            code = s
            name_parts = []
            j = i + 1
            page = 0
            while j < n and j < i + 8:
                t = lines[j].strip()
                # 이름 다음의 숫자는 쪽번호 (1015 처럼 4자리여도). 분류코드는 0으로 시작
                if re.fullmatch(r"\d{1,4}", t) and (name_parts or not t.startswith("0")):
                    page = int(t)
                    break
                m = re.match(r"^(.*?)\s+(\d{1,4})$", t)
                if m and m.group(1) and not RE_CODE.match(t):
                    name_parts.append(m.group(1))
                    page = int(m.group(2))
                    break
                if RE_CODE.match(t) and len(t) in (4, 6, 8) and t.startswith("0"):
                    break
                if t and t not in ("<", ">", ".", "・", "․", "·"):
                    name_parts.append(t)
                j += 1
            name = " ".join(name_parts).strip()
            repealed = "폐지" in name
            name = re.sub(r"\s*폐지\s*$", "", name).strip()
            if page and name:
                # '성희롱 성폭력' 처럼 가운뎃점이 줄바꿈으로 빠진 경우
                out.append((code, name, page, repealed))
                i = j + 1
                continue
        i += 1
    return out


def _extract_range(args):
    path, start, end = args
    from pypdf import PdfReader
    r = PdfReader(path)
    return [r.pages[i].extract_text() or "" for i in range(start, end)]


def _parse_header(lines: list[str], rb: "RegBook"):
    """쪽 머리글 → (인쇄 쪽번호, 규정명, 부서, 본문 시작 줄).
    두 형식 모두 처리:
      한 줄씩: 규정집 / 규정명 / 안양도시공사 / - n / N - / 부서
      합쳐짐: '규정집제목 규정명' / '기관명 - n / N - 부서'"""
    for k in range(min(8, len(lines))):
        s = lines[k].strip()
        m = RE_PAGE_LABEL.match(s)
        if m:
            head = [l.strip() for l in lines[:k]]
            if not rb.title and head:
                rb.title = head[0]
            regname = head[1] if len(head) > 1 else ""
            dept = lines[k + 1].strip() if k + 1 < len(lines) else ""
            return int(m.group(1)), regname, dept, k + 2
        m = RE_PAGE_LABEL_IN.search(s)
        if m and k >= 1:
            first = lines[k - 1].strip()
            title = rb.title or "안양도시공사 규정집"
            if not rb.title:
                # '안양도시공사 규정집 안양도시공사 인사규정' → 앞의 '…규정집'
                mt = re.match(r"^(\S+\s*규정집)\s+", first)
                if mt:
                    rb.title = title = mt.group(1)
            regname = first[len(title):].strip() if first.startswith(title) else first
            dept = s[m.end():].strip()
            return int(m.group(1)), regname, dept, k + 1
    return None


def load_pdf_text(pdf_path: str | Path, progress=None) -> list[str]:
    """PDF 쪽별 텍스트 (pypdf, BSD 라이선스). 쪽이 많으면 여러 프로세스로 나눠 읽는다."""
    from pypdf import PdfReader
    path = str(pdf_path)
    n = len(PdfReader(path).pages)
    if n < 60:
        return _extract_range((path, 0, n))
    import os
    from concurrent.futures import ProcessPoolExecutor
    workers = max(1, min(4, (os.cpu_count() or 2)))
    step = 40
    chunks = [(path, i, min(n, i + step)) for i in range(0, n, step)]
    pages: list[str] = []
    try:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for k, part in enumerate(ex.map(_extract_range, chunks)):
                pages.extend(part)
                if progress:
                    progress(min(n, (k + 1) * step), n)
    except Exception:
        pages = _extract_range((path, 0, n))
    return pages


def build_regbook(pdf_path: str | Path, progress=None, org_prefix: str = "") -> RegBook:
    pages = load_pdf_text(pdf_path, progress)
    return build_regbook_from_pages(pages, source=str(pdf_path), progress=progress)


def build_regbook_from_pages(pages: list[str], source: str = "", progress=None) -> RegBook:
    rb = RegBook(source=source)
    toc: list[tuple[str, str, int, bool]] = []
    body_pages: list[tuple[int, str, str, str, int]] = []   # (pdf idx, regname, dept, text, printed page)

    for idx, txt in enumerate(pages):
        txt = re.sub(r"[\ue000-\uf8ff]", "", txt.replace("\r\n", "\n").replace("\r", "\n"))
        lines = txt.split("\n")
        head = _parse_header(lines, rb)
        if head:
            printed, regname, dept, body_start = head
            body_pages.append((idx, regname, dept, "\n".join(lines[body_start:]), printed))
        else:
            if not body_pages:
                toc.extend(_parse_toc(lines))

    # 규정명 단위로 쪽을 묶는다 (같은 이름이 연속되는 구간)
    groups: list[RegEntry] = []
    for idx, regname, dept, body, printed in body_pages:
        if groups and _norm(groups[-1].name) == _norm(regname):
            g = groups[-1]
            g.text += body if g.text.endswith("\n") else "\n" + body
            g.pdf_pages.append(idx)
        else:
            groups.append(RegEntry(name=regname, dept=dept, page=printed, text=body, pdf_pages=[idx]))

    # 서식 쪽처럼 머리글 둘째 줄이 규정명이 아닌 묶음은 앞 규정에 합친다
    merged: list[RegEntry] = []
    for g in groups:
        known = any(_norm(name) == _norm(g.name) or _norm(g.name).endswith(_norm(name)) for _, name, _, _ in toc)
        if merged and not known and not REG_SUFFIX.search(_norm(g.name)):
            merged[-1].text += "\n" + g.text
            merged[-1].pdf_pages += g.pdf_pages
        elif merged and _norm(merged[-1].name) == _norm(g.name):
            merged[-1].text += "\n" + g.text
            merged[-1].pdf_pages += g.pdf_pages
        else:
            merged.append(g)
    groups = merged

    # 목차 코드 매칭 (쪽 번호 우선, 이름 보조)
    for g in groups:
        best = None
        for code, name, page, rep in toc:
            if page == g.page and (_norm(name) in _norm(g.name) or _norm(g.name).endswith(_norm(name)) or _norm(name)[:4] == _norm(g.name)[:4]):
                best = (code, name, rep)
                break
        if best is None:
            for code, name, page, rep in toc:
                if _norm(name) == _norm(g.name) or _norm(g.name).endswith(_norm(name)):
                    best = (code, name, rep)
                    break
        if best:
            g.code, _, g.repealed = best
        if "폐지" in g.name:
            g.repealed = True

    for i, g in enumerate(groups):
        if progress:
            progress(i, len(groups))
        doc = parse_text(g.text, name=g.name)
        if not doc.name or _norm(doc.name) != _norm(g.name):
            # 첫 줄이 규정명이 아닐 수 있음
            doc.name = g.name
        doc.law_type = guess_law_type(g.name)
        doc.org = g.dept
        doc.meta["code"] = g.code
        doc.meta["page"] = g.page
        g.doc = doc
    rb.entries = groups
    return rb
