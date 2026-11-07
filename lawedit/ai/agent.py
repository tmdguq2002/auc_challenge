"""규정 제·개정 에이전트 작업.

원칙: AI 는 '초안'만 쓴다. 조 번호·인용 정정·개정문·대비표·검사는 규칙 엔진이 다시 만들고 검증한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.model import LawDoc, Unit
from ..core.parser import parse_text
from ..core.render import render_unit, render_doc
from ..core import numbering, checks
from .llm import LLMConfig, complete, extract_json, LLMError

STYLE_RULES = """[입안 기준]
- 법제처 「법령 입안·심사 기준」과 알기 쉬운 법령 원칙을 따른다.
- 조문 형식: 제N조(제목) 본문 / 항은 ①②③, 호는 1. 2., 목은 가. 나.
- '~에 의하여'→'~에 따라', '당해'→'해당', '기타'→'그 밖의'로 쓴다. 문장 끝맺음('~하여야 한다' 등)은 기관 규정의 기존 문체를 따른다.
- 다른 조문 인용은 '제3조제1항제2호' 형식, 다른 규정은 「규정명」 제N조.
- 기존 규정의 용어·호칭·기구 명칭을 그대로 쓴다. 근거 없는 수치·기구를 지어내지 않는다.
"""


# ------------------------------------------------------------------ 관련 조문 고르기 (작은 모델용 문맥 절약)
def _score(text: str, query: str) -> float:
    def grams(t):
        t = re.sub(r"[^가-힣A-Za-z0-9]", "", t)
        return {t[i:i + 2] for i in range(len(t) - 1)}
    a, b = grams(text), grams(query)
    return len(a & b) / (len(b) or 1)


def relevant_articles(doc: LawDoc, query: str, limit: int = 12) -> list[Unit]:
    arts = [a for a in doc.articles() if not a.deleted]
    scored = sorted(arts, key=lambda a: -_score(a.title * 2 + a.plain(), query))
    keep = set(id(a) for a in scored[:limit])
    return [a for a in arts if id(a) in keep]


def doc_context(doc: LawDoc, query: str, full: bool) -> str:
    if full:
        return render_doc(doc, with_history=False)
    arts = relevant_articles(doc, query)
    heads = ", ".join(a.heading() for a in doc.articles()[:200])
    return (f"{doc.name}\n[전체 조문 목록] {heads}\n\n[관련 조문]\n" +
            "\n".join("\n".join(render_unit(a, False)) for a in arts))


# ------------------------------------------------------------------ 개정안 초안
@dataclass
class ArticleEdit:
    action: str            # replace / insert_after / delete
    target: str            # 제8조 (insert_after 면 그 뒤에)
    text: str = ""         # 새 조문 전체
    why: str = ""


@dataclass
class AmendDraft:
    edits: list[ArticleEdit] = field(default_factory=list)
    reason: str = ""
    points: list[str] = field(default_factory=list)
    model: str = ""
    usage: str = ""
    warnings: list[str] = field(default_factory=list)


AMEND_SYSTEM = """당신은 공공기관 규정(사규) 개정안을 입안하는 법제 담당자를 돕는 전문가입니다.
사용자가 준 현행 규정과 '개정 의도'를 바탕으로, 바꿔야 할 조문만 골라 개정 후 조문 전체를 작성합니다.
""" + STYLE_RULES + """
[출력] 아래 JSON 하나만 출력합니다. 설명 문장은 쓰지 않습니다.
{
 "edits": [
   {"action": "replace", "target": "제8조", "text": "제8조(인사위원회 설치) ① …\\n② …", "why": "변경 이유 한 줄"},
   {"action": "insert_after", "target": "제8조", "text": "제8조의2(…) …", "why": "…"},
   {"action": "delete", "target": "제9조", "why": "…"}
 ],
 "reason": "개정이유 (…하려는 것임. 형식, 2~4문장)",
 "points": ["주요내용 1 (…함)", "주요내용 2"]
}
- replace 의 text 는 조 제목과 모든 항·호를 포함한 개정 후 조문 전체입니다. 바뀌지 않는 항도 그대로 씁니다.
- 새 조문은 insert_after 로 가장 알맞은 조 뒤에 둡니다(번호는 프로그램이 매김).
- 의도와 무관한 조문은 고치지 않습니다.
- 고치는 조문 안에서도 의도와 관계없는 부분(띄어쓰기, 따옴표, 용어 순화, 문장 다듬기 포함)은 현행 문구를
  한 글자도 바꾸지 말고 그대로 옮깁니다. 개정문에 꼭 필요한 자구만 바뀌도록 하기 위해서입니다."""


def draft_amendment(cfg: LLMConfig, current: LawDoc, intent: str, extra_context: str = "") -> AmendDraft:
    full = len(render_doc(current, with_history=False)) < 150_000   # 아주 긴 규정만 관련 조문으로 줄인다
    user = (f"[현행 규정]\n{doc_context(current, intent, full)}\n\n"
            + (f"[참고: 관련 상위·하위 규정]\n{extra_context}\n\n" if extra_context else "")
            + f"[개정 의도]\n{intent}\n\nJSON으로만 답하세요.")
    res = complete(cfg, AMEND_SYSTEM, user, max_tokens=16000, effort="high", json_mode=True)
    data = extract_json(res.text)
    d = AmendDraft(model=res.model, usage=f"입력 {res.input_tokens:,} / 출력 {res.output_tokens:,} 토큰")
    for e in data.get("edits", []):
        act = str(e.get("action", "")).strip()
        if act not in ("replace", "insert_after", "delete"):
            continue
        d.edits.append(ArticleEdit(act, str(e.get("target", "")).strip(), str(e.get("text", "")).strip(), str(e.get("why", "")).strip()))
    d.reason = str(data.get("reason", "")).strip()
    d.points = [str(x).strip() for x in data.get("points", []) if str(x).strip()]
    if res.note:
        d.warnings.append(res.note)
    return d


def _key(label: str) -> tuple[int, int] | None:
    m = re.search(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?", label or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def _parse_article(text: str) -> Unit | None:
    nd = parse_text("임시\n" + text)
    arts = nd.articles()
    return arts[0] if arts else None


def curly_quotes(text: str) -> str:
    """AI가 쓴 곧은 따옴표를 입안 기준의 둥근 따옴표로: "직원" → “직원”, '경우' → ‘경우’."""
    text = re.sub(r'"([^"\n]*)"', "“\\1”", text)
    return re.sub(r"(?<![A-Za-z])'([^'\n]+)'(?![A-Za-z])", "‘\\1’", text)


def _keep_spacing(old, new):
    """AI가 띄어쓰기만 바꾼 단위는 현행 글자를 그대로 둔다(개정문엔 안 나오고 대비표에만 바뀐 것처럼 보이는 일 방지)."""
    same = lambda a, b: " ".join(a.split()) == " ".join(b.split())
    if same(old.title, new.title):
        new.title = old.title
    if same(old.text, new.text):
        new.text = old.text
    olds = {(c.kind, c.num, c.branch): c for c in old.children}
    for c in new.children:
        o = olds.get((c.kind, c.num, c.branch))
        if o is not None:
            _keep_spacing(o, c)


def apply_draft(current: LawDoc, base: LawDoc, draft: AmendDraft, delete_mode: str = "mark") -> tuple[LawDoc, list[str]]:
    """초안을 개정안 문서에 적용. 번호 매김·인용 정정은 엔진이 한다."""
    doc = base.clone()
    log = []
    for e in draft.edits:
        k = _key(e.target)
        tgt = doc.find_article(*k) if k else None
        if e.action == "replace":
            nu = _parse_article(e.text)
            if tgt is None or nu is None:
                log.append(f"[건너뜀] {e.target} 대체: 조문을 찾거나 해석하지 못함")
                continue
            _keep_spacing(tgt, nu)
            tgt.title, tgt.text, tgt.children, tgt.deleted = nu.title, nu.text, nu.children, False
            log.append(f"[개정] {tgt.number_label()} — {e.why}")
        elif e.action == "insert_after":
            nu = _parse_article(e.text)
            if nu is None:
                log.append(f"[건너뜀] {e.target} 뒤 신설: 조문 해석 실패")
                continue
            na = numbering.insert_article(doc, tgt, title=nu.title, text=nu.text, mode="branch" if current is not None else "renumber")
            na.children = nu.children
            log.append(f"[신설] {na.number_label()}({na.title}) — {e.why}")
        elif e.action == "delete":
            if tgt is None:
                log.append(f"[건너뜀] {e.target} 삭제: 조문 없음")
                continue
            numbering.delete_article(doc, tgt, delete_mode)
            log.append(f"[삭제] {e.target} — {e.why}")
    return doc, log


# ------------------------------------------------------------------ 제정안 초안
NEW_SYSTEM = """당신은 공공기관 규정(사규)을 새로 만드는 법제 담당자를 돕는 전문가입니다.
제정 목적, 상위 규정의 위임 조항, 참고할 유사 규정을 바탕으로 규정 전체 초안을 작성합니다.
""" + STYLE_RULES + """
[구성] 제1장 총칙(목적·정의·적용범위) → 본문 장 → 보칙(위임 등) 순서. 위원회를 두면 구성·임기·회의·제척 조문을 갖춥니다.
[출력] 규정 본문만 출력합니다(설명·마크다운 금지). 첫 줄은 규정명, 그다음 '제1장 총칙', 조문들, 마지막에 '부칙'과 시행일 조문."""


def draft_new(cfg: LLMConfig, name: str, law_type: str, purpose: str, delegation: str = "", similar: str = "") -> tuple[LawDoc, str]:
    user = (f"[규정명] {name}\n[종류] {law_type}\n[제정 목적]\n{purpose}\n\n"
            + (f"[상위 규정의 위임 조항]\n{delegation}\n\n" if delegation else "")
            + (f"[참고할 유사 규정 조문]\n{similar}\n\n" if similar else "")
            + "규정 본문만 출력하세요.")
    res = complete(cfg, NEW_SYSTEM, user, max_tokens=16000, effort="high")
    text = curly_quotes(re.sub(r"^```\w*\s*|\s*```$", "", res.text.strip()))
    doc = parse_text(text, name=name)
    doc.name = doc.name or name
    doc.law_type = law_type
    doc.amend_type = "제정"
    return doc, f"{res.model} · 입력 {res.input_tokens:,} / 출력 {res.output_tokens:,} 토큰"


# ------------------------------------------------------------------ 상충 검토
REVIEW_SYSTEM = """당신은 공공기관 규정 체계 검토자입니다. 두 조문(상위/하위 또는 관련 규정)이 서로 상충하는지 판단합니다.
상충이란 같은 사항을 다르게 정해 둘 다 지킬 수 없거나, 하위 규정이 상위 규정의 범위를 벗어난 경우입니다.
서로 다른 대상·절차를 정한 것이면 상충이 아닙니다.
[출력] JSON 하나만: {"verdict": "상충" | "상충 아님" | "확인 필요", "reason": "판단 근거 2~3문장", "fix": "고칠 방향(상충일 때)"}"""


def review_conflict(cfg: LLMConfig, a_name: str, a_text: str, b_name: str, b_text: str, detail: str) -> dict:
    user = f"[조문 가: {a_name}]\n{a_text}\n\n[조문 나: {b_name}]\n{b_text}\n\n[프로그램이 찾은 의심 사항]\n{detail}\n\nJSON으로만 답하세요."
    res = complete(cfg, REVIEW_SYSTEM, user, max_tokens=4000, effort="medium", json_mode=True)
    d = extract_json(res.text)
    d["model"] = res.model
    return d


# ------------------------------------------------------------------ 연결 시험
def ping(cfg: LLMConfig) -> str:
    res = complete(cfg, "짧게 답합니다.", "'연결 성공'이라고만 답하세요.", max_tokens=200, effort="low")
    return f"{res.text.strip()[:40]} ({res.model})"


def verify_doc(doc: LawDoc) -> list:
    """AI 초안을 규칙 엔진으로 검사 (번호·인용·부호)."""
    return checks.check_structure(doc) + checks.check_references(doc) + checks.check_marks(doc)


# ------------------------------------------------------------------ 명칭 변경 의도 읽기
_Q = "‘’'“”\""
RE_RENAME = re.compile(
    r"[" + _Q + r"]?([가-힣A-Za-z0-9·ㆍ]{2,20}(?:\s[가-힣A-Za-z0-9·ㆍ]{1,15}){0,2}?)[" + _Q + r"]?\s*(?:을|를|에서)\s*"
    r"[" + _Q + r"]?([가-힣A-Za-z0-9·ㆍ]{2,20}(?:\s[가-힣A-Za-z0-9·ㆍ]{1,15}){0,2}?)[" + _Q + r"]?\s*(?:으로|로)\s*"
    r"(?:명칭(?:을)?\s*)?(?:변경|바꾸|바꿈|바꾼|고치|고침|개칭|개정|수정)")


def rename_pairs(intent: str) -> list[tuple[str, str]]:
    """'경영기획본부를 경영전략본부로 변경' → [('경영기획본부', '경영전략본부')]."""
    out = []
    for m in RE_RENAME.finditer(intent):
        old, new = m.group(1).strip(), m.group(2).strip()
        old = re.sub(r"^(?:조직개편으로|조직\s*개편에\s*따라|그리고|또한|및)\s*", "", old)
        if old and new and old != new and (old, new) not in out:
            out.append((old, new))
    return out


def term_locations(term: str, docs) -> list[tuple[object, int, list[str]]]:
    """여러 규정에서 term 이 나오는 곳: (문서, 횟수, 조문 목록)."""
    out = []
    for d in docs:
        n = sum(a.plain().count(term) for a in d.articles())
        if n:
            out.append((d, n, sorted({a.number_label() for a in d.articles() if term in a.plain()},
                                     key=lambda s: [int(x) for x in re.findall(r"\d+", s)])))
    out.sort(key=lambda x: -x[1])
    return out


def spelling_warnings(intent_pairs, draft_text: str) -> list[str]:
    """의도에 적은 새 명칭과 AI 결과의 표기가 다르면 경고(오타를 AI가 몰래 고친 경우 등)."""
    import difflib
    warns = []
    for old, new in intent_pairs:
        if new in draft_text:
            continue
        cands = set(re.findall(r"[가-힣A-Za-z0-9·ㆍ]{%d,%d}" % (max(2, len(new) - 1), len(new) + 1), draft_text))
        close = difflib.get_close_matches(new, list(cands), n=1, cutoff=0.7)
        if close:
            warns.append(f"개정 의도에는 ‘{new}’라고 적었으나 AI 초안은 ‘{close[0]}’(으)로 썼습니다. 어느 표기가 맞는지 확인하세요.")
        else:
            warns.append(f"개정 의도의 새 명칭 ‘{new}’이(가) AI 초안에 없습니다.")
    return warns
