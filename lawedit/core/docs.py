"""문서처리: 입법예고문, 관보게재문(공포문), 제·개정 이유, 부칙 서식."""
from __future__ import annotations

import datetime as dt
import re

from .amend import compare, build_amendment_lines, Change
from .korean import josa
from .model import LawDoc
from .render import render_doc

# 법령 종류별 표기
KIND_INFO = {
    #           공포번호표기, 개정 문서명 접미, 예고 기간(일), 시행 문구 주어
    "법률": ("법률", "법률", 40, "이 법"),
    "대통령령": ("대통령령", "령", 40, "이 영"),
    "총리령": ("총리령", "령", 40, "이 영"),
    "부령": ("부령", "령", 40, "이 규칙"),
    "조례": ("조례", "조례", 20, "이 조례"),
    "규칙": ("규칙", "규칙", 20, "이 규칙"),
    "정관": ("정관", "정관", 10, "이 정관"),
    "규정": ("규정", "규정", 10, "이 규정"),
    "시행내규": ("내규", "내규", 10, "이 내규"),
    "내규": ("내규", "내규", 10, "이 내규"),
    "지침": ("지침", "지침", 10, "이 지침"),
    "훈령": ("훈령", "훈령", 20, "이 훈령"),
    "예규": ("예규", "예규", 20, "이 예규"),
    "고시": ("고시", "고시", 20, "이 고시"),
}


def kind_info(doc: LawDoc):
    return KIND_INFO.get(doc.law_type, KIND_INFO["규정"])


def today_str(d: dt.date | None = None) -> str:
    d = d or dt.date.today()
    return f"{d.year}. {d.month}. {d.day}."


def amended_title(doc: LawDoc) -> str:
    """'안양도시공사 인사규정 일부개정규정'."""
    _, suf, _, _ = kind_info(doc)
    at = doc.amend_type
    if at == "제정":
        return doc.name
    if at == "폐지":
        return f"{doc.name} 폐지{suf}"
    return f"{doc.name} {at}{suf}"


def default_addenda(doc: LawDoc, effective: str = "") -> str:
    _, _, _, subj = kind_info(doc)
    if effective:
        return f"{subj}{josa(subj, '은/는')} {effective}부터 시행한다."
    verb = "공포한 날" if doc.law_type in ("법률", "대통령령", "총리령", "부령", "조례", "규칙") else "발령한 날"
    return f"{subj}{josa(subj, '은/는')} {verb}부터 시행한다."


def summarize_changes(cur: LawDoc | None, new: LawDoc, changes: list[Change] | None = None, limit: int = 12) -> list[str]:
    """주요내용 초안 — 조문별 한 줄."""
    if cur is None or new.amend_type in ("제정", "전부개정"):
        out = []
        for a in new.articles()[:limit]:
            if a.title:
                out.append(f"{a.title}에 관한 사항을 정함({a.number_label()}).")
        return out
    changes = changes if changes is not None else compare(cur, new)
    by_art: dict[str, list[Change]] = {}
    for c in changes:
        by_art.setdefault(c.art_path or c.path, []).append(c)
    out = []
    for art, cs in by_art.items():
        a = new.find_article(*_parse_key(art)) or (cur.find_article(*_parse_key(art)) if cur else None)
        title = a.title if a else ""
        bits = []
        for c in cs:
            if c.kind == "phrase":
                bits += [f"“{o}” → “{n}”" if n else f"“{o}” 삭제" for o, n in c.phrases[:2]]
            elif c.kind == "add":
                bits.append(f"{c.new_label} 신설")
            elif c.kind == "delete":
                bits.append(f"{c.path} 삭제")
            elif c.kind == "whole":
                bits.append(f"{c.path} 개정")
            elif c.kind == "title":
                bits.append("조 제목 변경")
            elif c.kind == "renumber":
                bits.append(f"{c.path}→{c.new_label}")
        out.append(f"{title or art} 정비({art}: {', '.join(bits[:3])})")
        if len(out) >= limit:
            break
    return out


def _parse_key(label: str) -> tuple[int, int]:
    m = re.match(r"제(\d+)조(?:의(\d+))?", label or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def legislative_notice(cur: LawDoc | None, new: LawDoc, org: str = "", reason: str = "", main_points: list[str] | None = None,
                       notice_no: str = "", start: dt.date | None = None, days: int | None = None,
                       contact: str = "", announcer: str = "") -> str:
    """입법예고문."""
    _, suf, default_days, _ = kind_info(new)
    days = days or default_days
    start = start or dt.date.today()
    end = start + dt.timedelta(days=days)
    name = new.name or (cur.name if cur else "")
    kind = {"제정": "제정", "일부개정": "일부개정", "전부개정": "전부개정", "폐지": "폐지"}.get(new.amend_type, new.amend_type)
    org = org or new.org or "소관부서"
    announcer = announcer or (f"{name.split()[0]} 사장" if name.startswith("안양도시공사") else "기관장")
    pts = main_points if main_points is not None else summarize_changes(cur, new)
    reason = reason or f"「{name}」의 운영상 나타난 일부 미비점을 개선ㆍ보완하려는 것임."
    lines = [
        f"{(name.split()[0] + ' ') if name.startswith('안양도시공사') else ''}공고 제{notice_no or '     '}호", "",
        f"「{name}」 {kind}(안) 입법예고", "",
        f"「{name}」{josa('」', '을/를') if False else '을'} {kind}하고자 그 취지와 주요내용을 미리 알려 의견을 듣고자 다음과 같이 공고합니다.".replace("」을", "」" + josa(name, "을/를")),
        "", f"{start.year}년 {start.month}월 {start.day}일", "", announcer, "",
        f"1. {kind}이유", f"   {reason}", "",
        "2. 주요내용",
    ]
    hangul = "가나다라마바사아자차카타파하"
    for i, p in enumerate(pts or ["(주요내용을 입력하십시오)"]):
        lines.append(f"   {hangul[i % 14]}. {p}")
    lines += [
        "", "3. 의견제출",
        f"   이 {kind}안에 대하여 의견이 있는 기관ㆍ단체 또는 개인은 {end.year}년 {end.month}월 {end.day}일까지 "
        f"다음 사항을 적은 의견서를 {org}에 제출해 주시기 바랍니다.",
        "   가. 예고 사항에 대한 의견(찬성 또는 반대 의견과 그 이유)",
        "   나. 성명(단체의 경우 단체명과 대표자 성명), 주소 및 전화번호",
        "   다. 그 밖의 참고 사항",
        "", "4. 그 밖의 사항",
        f"   {kind}안에 대한 자세한 사항은 {org}" + (f"(☎ {contact})" if contact else "") + "로 문의해 주시기 바랍니다.",
    ]
    return "\n".join(lines)


def gazette_text(cur: LawDoc | None, new: LawDoc, number: str = "", date: dt.date | None = None,
                 promulgator: str = "", addenda: str = "") -> str:
    """관보(공포·발령) 게재문."""
    numlabel, suf, _, _ = kind_info(new)
    date = date or dt.date.today()
    name = new.name or (cur.name if cur else "")
    title = amended_title(new)
    verb = "공포한다" if new.law_type in ("법률", "대통령령", "총리령", "부령", "조례", "규칙") else "발령한다"
    lines = [f"{title}{josa(title, '을/를')} 이에 {verb}.", "",
             f"{date.year}년 {date.month}월 {date.day}일", "",
             promulgator or ("안양도시공사 사장" if name.startswith("안양도시공사") else "(공포권자)"), "",
             f"⊙{numlabel} 제{number or '    '}호", "", title, ""]
    if new.amend_type in ("제정", "전부개정"):
        if new.amend_type == "전부개정" and cur is not None:
            lines.append(f"{name} 전부를 다음과 같이 개정한다.")
            lines.append("")
        body = render_doc(new, with_history=False, with_header=False).split("\n")
        # 본문에 이미 부칙이 있으면 그대로
        lines += body
        if not new.addenda:
            lines += ["", "부칙", addenda or default_addenda(new)]
    elif new.amend_type == "폐지":
        lines += [f"{name}{josa(name, '을/를')} 폐지한다.", "", "부칙", addenda or default_addenda(new)]
    else:
        lines += build_amendment_lines(cur or new, new)
        lines += ["", "부칙", addenda or default_addenda(new)]
    return "\n".join(lines)


def reason_text(cur: LawDoc | None, new: LawDoc, reason: str = "", points: list[str] | None = None) -> str:
    """제정ㆍ개정이유 및 주요내용 (법제처 서식)."""
    kind = new.amend_type
    pts = points if points is not None else summarize_changes(cur, new)
    lines = [f"◆{kind}이유 및 주요내용", "",
             reason or f"「{new.name}」의 운영상 나타난 일부 미비점을 개선ㆍ보완하려는 것임.", ""]
    hangul = "가나다라마바사아자차카타파하"
    for i, p in enumerate(pts):
        lines.append(f"{hangul[i % 14]}. {p}")
    return "\n".join(lines)
