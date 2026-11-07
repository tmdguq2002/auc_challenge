"""타법개정 — 이번 개정 때문에 함께 고쳐야 하는 다른 규정 찾기, 부칙 '다른 규정의 개정' 문안 만들기."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .amend import compare, build_amendment_lines
from .model import LawDoc
from .refs import extract_refs, iter_text_units


@dataclass
class OtherHit:
    doc_name: str
    where: str
    text: str
    reason: str
    uid: str = ""


@dataclass
class OtherAmend:
    doc: LawDoc
    new: LawDoc
    hits: list[OtherHit] = field(default_factory=list)

    def sentences(self) -> list[str]:
        lines = build_amendment_lines(self.doc, self.new)
        return [l for l in lines[2:] if l.strip()]


def _short(name: str) -> str:
    return re.sub(r"^안양도시공사\s*", "", name).strip()


def _norm(s: str) -> str:
    return re.sub(r"[\s·ㆍ・‧․]", "", s or "")


def _cites(ref_target: str, name: str, other: LawDoc, cur: LawDoc) -> bool:
    t = _norm(ref_target)
    n = _norm(name)
    if not t:
        return False
    if t == n or n.endswith(t) and len(t) >= 3 or t.endswith(_norm(_short(name))) and len(_norm(_short(name))) >= 3:
        return True
    # 시행내규의 '규정' = 상위 규정
    if t in ("규정",) and _norm(other.name).startswith(n.replace("규정", "")) and other.law_type in ("시행내규", "내규"):
        return True
    return False


def renumber_map(cur: LawDoc, new: LawDoc) -> tuple[dict, set]:
    """현행→개정 조 번호 대응과 삭제된 조."""
    mp, deleted = {}, set()
    for c in compare(cur, new):
        if c.kind == "renumber" and c.old_unit is not None and c.old_unit.kind == "article":
            mp[(c.old_unit.num, c.old_unit.branch)] = (c.new_unit.num, c.new_unit.branch)
        if c.kind == "delete" and c.old_unit is not None and c.old_unit.kind == "article":
            deleted.add((c.old_unit.num, c.old_unit.branch))
    return mp, deleted


def find_other_amendments(cur: LawDoc, new: LawDoc, others: list[LawDoc],
                          term_changes: list[tuple[str, str]] | None = None) -> list[OtherAmend]:
    """다른 규정 각각에 대해 고칠 곳과 고친 문서를 만든다."""
    mp, deleted = renumber_map(cur, new)
    name_change = (cur.name, new.name) if cur.name and new.name and cur.name != new.name else None
    terms = list(term_changes or [])
    if name_change:
        terms.insert(0, (f"「{cur.name}」", f"「{new.name}」"))
        if _short(cur.name) != _short(new.name):
            terms.append((_short(cur.name), _short(new.name)))
    out: list[OtherAmend] = []
    for o in others:
        if o is cur or o is new or _norm(o.name) == _norm(cur.name):
            continue
        no = o.clone()
        hits: list[OtherHit] = []
        # 1) 조 번호 인용 갱신
        if mp or deleted:
            refs = extract_refs(no)
            by_uid: dict[str, list] = {}
            for r in refs:
                if r.article and _cites(r.target, cur.name, o, cur):
                    by_uid.setdefault(r.src_uid, []).append(r)
            for uid, rs in by_uid.items():
                u = no.find_uid(uid)
                text = u.text
                for r in sorted(rs, key=lambda r: -r.start):
                    k = (r.article, r.article_branch)
                    if k in mp:
                        nk = mp[k]
                        newlab = f"제{nk[0]}조" + (f"의{nk[1]}" if nk[1] else "")
                        seg = re.sub(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?", newlab, text[r.start:r.end])
                        text = text[:r.start] + seg + text[r.end:]
                        hits.append(OtherHit(o.name, r.src_label, u.text, f"{r.target_raw or r.target} {r.text} → {newlab}", uid))
                    elif k in deleted:
                        hits.append(OtherHit(o.name, r.src_label, u.text,
                                             f"삭제되는 조문을 인용: {r.target_raw or r.target} {r.text} (직접 정비 필요)", uid))
                u.text = text
        # 2) 명칭·용어 변경
        for old, nw in terms:
            if not old or old == nw:
                continue
            for u, art, para in iter_text_units(no, True):
                if old in u.text:
                    hits.append(OtherHit(o.name, (art.number_label() if art else "") + (para.ref_label() if para and u is not art else ""),
                                         u.text, f"“{old}” → “{nw}”", u.uid))
                    u.text = u.text.replace(old, nw)
        if hits:
            out.append(OtherAmend(o, no, hits))
    return out


def addenda_other_amend_text(amends: list[OtherAmend], start_no: int = 2) -> str:
    """부칙 '제2조(다른 규정의 개정)' 문안."""
    if not amends:
        return ""
    title = "다른 규정의 개정" if len(amends) == 1 or True else ""
    lines = [f"제{start_no}조({title})"]
    circ = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
    for i, a in enumerate(amends):
        head = f"{a.doc.name} 일부를 다음과 같이 개정한다."
        prefix = (circ[i] + " ") if len(amends) > 1 else ""
        if i == 0:
            lines[0] += " " + prefix + head
        else:
            lines.append(prefix + head)
        lines.extend(a.sentences())
    return "\n".join(lines)


def citing_list(cur: LawDoc, others: list[LawDoc]) -> list[OtherHit]:
    """타법목록 추출 — cur 를 인용하는 다른 규정 조문 목록."""
    out = []
    for o in others:
        if _norm(o.name) == _norm(cur.name):
            continue
        for r in extract_refs(o):
            if _cites(r.target, cur.name, o, cur):
                u = o.find_uid(r.src_uid)
                out.append(OtherHit(o.name, r.src_label, u.text if u else "", f"{r.target_raw or r.target} {r.text}", r.src_uid))
        for u, art, para in iter_text_units(o):
            if f"「{cur.name}」" in u.text or (len(_short(cur.name)) >= 4 and _short(cur.name) in u.text and not any(
                    h.uid == u.uid for h in out)):
                out.append(OtherHit(o.name, art.number_label() if art else "", u.text, "규정명 인용", u.uid))
    # 중복 제거
    seen, res = set(), []
    for h in out:
        k = (h.doc_name, h.uid, h.reason)
        if k not in seen:
            seen.add(k)
            res.append(h)
    return res
