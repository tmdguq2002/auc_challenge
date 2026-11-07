"""개정 분석: 현행 ↔ 개정안 비교 → 개정문, 신ㆍ구조문대비표.

법제처 「법령 입안·심사 기준」의 개정문 문형을 따른다.
  제3조제1항 중 “시장”을 “안양시장”으로 한다.
  제5조를 다음과 같이 한다.
  제5조의2를 다음과 같이 신설한다.
  제7조제2항에 제4호를 다음과 같이 신설한다.
  제9조를 삭제한다.
  제10조의 제목 “(임원)”을 “(임원의 구성)”으로 한다.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .korean import josa
from .model import LawDoc, Unit, DIVISION_LABEL, UNIT_LABEL
from .render import render_unit

PHRASE_LIMIT = 3            # 한 단위에서 자구 개정이 이보다 많으면 전체를 다시 씀
WHOLE_RATIO = 0.55          # 바뀐 비율이 이보다 크면 전체를 다시 씀


# ---------------------------------------------------------------- 정렬(매칭)
def _sim(a: str, b: str, floor: float = 0.0) -> float:
    """유사도. floor 보다 낮을 게 분명하면 빠른 상한값으로 끊는다."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if floor:
        if sm.real_quick_ratio() <= floor or sm.quick_ratio() <= floor:
            return 0.0
    return sm.ratio()


def align_units(cur: list[Unit], new: list[Unit]) -> list[tuple[Unit | None, Unit | None]]:
    """같은 종류 단위 목록을 짝짓는다 (uid → 번호 → 내용 유사도)."""
    pairs: dict[int, int] = {}
    cp = [u.plain() for u in cur]          # 한 번만 렌더링
    np_ = [u.plain() for u in new]
    cur_uid = {u.uid: i for i, u in enumerate(cur)}
    for j, n in enumerate(new):
        if n.uid in cur_uid and cur_uid[n.uid] not in pairs.values():
            pairs[j] = cur_uid[n.uid]
    used = set(pairs.values())
    # 번호만 옮긴 단위(번호 정리·맞바꾸기): 번호를 뺀 내용이 같고 양쪽에서 하나뿐이면 짝
    def sig(u):
        return (u.kind, u.deleted, u.title, u.text, tuple(c.plain() for c in u.children))
    cs, ns = {}, {}
    for i, u in enumerate(cur):
        cs.setdefault(sig(u), []).append(i)
    for j, u in enumerate(new):
        ns.setdefault(sig(u), []).append(j)
    for k, js in ns.items():
        if len(js) == 1 and len(cs.get(k, [])) == 1 and js[0] not in pairs and cs[k][0] not in used \
                and (new[js[0]].text or new[js[0]].children or new[js[0]].title):
            pairs[js[0]] = cs[k][0]
            used.add(cs[k][0])
    # 제목이 같은 조(양쪽에서 하나뿐)
    ct, nt = {}, {}
    for i, u in enumerate(cur):
        if u.title and i not in used:
            ct.setdefault(u.title, []).append(i)
    for j, u in enumerate(new):
        if u.title and j not in pairs:
            nt.setdefault(u.title, []).append(j)
    for t, js in nt.items():
        if len(js) == 1 and len(ct.get(t, [])) == 1:
            pairs[js[0]] = ct[t][0]
            used.add(ct[t][0])
    cur_key = {(u.kind, u.num, u.branch): i for i, u in enumerate(cur)}
    for j, n in enumerate(new):
        if j in pairs:
            continue
        i = cur_key.get((n.kind, n.num, n.branch))
        if i is not None and i not in used:
            # 번호는 같지만 완전히 다른 내용이면(중간 신설로 밀린 경우) 보류
            c = cur[i]
            # 'n조 삭제'로 바꾼 조는 내용이 달라도 같은 조
            if c.title and c.title == n.title or c.deleted != n.deleted or _sim(cp[i], np_[j], 0.35) > 0.35:
                pairs[j] = i
                used.add(i)
    for j, n in enumerate(new):
        if j in pairs:
            continue
        best, bi = 0.6, None
        for i, c in enumerate(cur):
            if i in used or c.kind != n.kind:
                continue
            s = _sim(cp[i], np_[j], best)
            if s > best:
                best, bi = s, i
        if bi is not None:
            pairs[j] = bi
            used.add(bi)
    # 순서대로 병합
    out: list[tuple[Unit | None, Unit | None]] = []
    ci = 0
    inv = {i: j for j, i in pairs.items()}
    for j, n in enumerate(new):
        if j in pairs:
            i = pairs[j]
            while ci < len(cur) and ci not in inv and ci < i:
                out.append((cur[ci], None))
                ci += 1
            out.append((cur[i], n))
            ci = max(ci, i + 1)
        else:
            out.append((None, n))
    for i in range(len(cur)):
        if i not in inv and not any(p[0] is cur[i] for p in out):
            # 남은 삭제 단위는 원래 위치 근처에 넣는다
            pos = next((k for k, p in enumerate(out) if p[0] is not None and cur.index(p[0]) > i), len(out))
            out.insert(pos, (cur[i], None))
    return out


# ---------------------------------------------------------------- 자구 비교
_TOK = re.compile(r"\s+|[^\s]+")


class EachStr(str):
    """한 단위 안에서 같은 자구가 여러 번 같은 말로 바뀔 때 — 개정문에 '각각'을 쓴다."""
    each = True


def _same_replacement(old: str, new: str):
    """old 의 모든 X 를 Y 로 바꾸면 new 가 되는 (X, Y) 가 있으면 돌려준다 (X 가 2번 이상)."""
    a, b = _TOK.findall(old), _TOK.findall(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    if len(ops) < 2 or any(op[0] != "replace" for op in ops):
        return None
    cores = set()
    for _, i1, i2, j1, j2 in ops:
        o, n = "".join(a[i1:i2]).strip(), "".join(b[j1:j2]).strip()
        # 붙어 있는 조사·문장부호 덜어내기
        while o and n and o[-1] == n[-1] and not ("가" <= o[-1] <= "힣" and len(o) <= 2):
            if o[:-1] and n[:-1] and o[-1] in ",.)」”" or o[-1] in "으로를을는은이가에의와과":
                o, n = o[:-1], n[:-1]
            else:
                break
        cores.add((o, n))
    if len(cores) != 1:
        return None
    x, y = cores.pop()
    if x and old.count(x) == len(ops) and old.replace(x, y) == new:
        return x, y
    return None


def phrase_changes(old: str, new: str) -> list[tuple[str, str]]:
    """어절 단위로 바뀐 부분을 (현행, 개정) 쌍으로 뽑는다.

    - 가까운 변경(사이에 어절 2개 이하)은 하나로 묶는다: “5명 이상 7명 이내”
    - 끼워 넣기는 뒤 어절(문장 끝이면 앞 어절)을 문맥으로 붙인다: “사장이”→“공사의 사장이”
    - 현행 문구가 그 단위 안에서 유일하도록 앞뒤로 넓힌다.
    """
    same = _same_replacement(old, new)
    if same:
        return [(EachStr(same[0]), same[1])]
    a = _TOK.findall(old)
    b = _TOK.findall(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = [list(op[1:]) for op in sm.get_opcodes() if op[0] != "equal"]
    if not ops:
        return []

    def words(lst, i, j):
        return sum(1 for t in lst[i:j] if not t.isspace())
    # 1) 가까운 변경 합치기
    merged = [ops[0]]
    for op in ops[1:]:
        last = merged[-1]
        if words(a, last[1], op[0]) <= 2:
            last[1], last[3] = op[1], op[3]
        else:
            merged.append(op)
    out = []
    for i1, i2, j1, j2 in merged:
        # 2) 순수 삽입·삭제 → 문맥 어절 붙이기
        if i1 == i2 or j1 == j2:
            nxt = i2
            while nxt < len(a) and a[nxt].isspace():
                nxt += 1
            if nxt < len(a):
                i2, j2 = nxt + 1, j2 + (nxt + 1 - i2)
            else:
                prv = i1 - 1
                while prv > 0 and a[prv].isspace():
                    prv -= 1
                if prv >= 0:
                    j1 -= (i1 - prv)
                    i1 = prv
        # 공백 토큰 경계 정리
        while i1 < i2 and a[i1].isspace():
            i1 += 1
            j1 += 1 if j1 < j2 and b[j1].isspace() else 0
        o = "".join(a[i1:i2]).strip()
        n = "".join(b[j1:j2]).strip()
        # 3) 유일하게 넓히기
        guard = 0
        while o and old.count(o) > 1 and guard < 10:
            guard += 1
            if i1 > 0:
                i1 -= 1
                j1 -= 1
            elif i2 < len(a):
                i2 += 1
                j2 += 1
            else:
                break
            o = "".join(a[i1:i2]).strip()
            n = "".join(b[max(j1, 0):j2]).strip()
        if o != n:
            o, n = _trim_common(old, o, n)
            out.append((o, n))
    # 4) 앞 변경의 결과가 뒤 변경의 현행 문구와 겹치면 합친다(순차 적용 충돌 방지)
    final: list[tuple[str, str]] = []
    for o, n in out:
        if final and (o in final[-1][1] or final[-1][0] in o):
            fo, fn = final[-1]
            s0, s1 = old.find(fo), old.find(o)
            if s0 >= 0 and s1 >= 0:
                lo, hi = min(s0, s1), max(s0 + len(fo), s1 + len(o))
                span = old[lo:hi]
                nn = apply_phrases(span, [(fo, fn), (o, n)])
                final[-1] = (span, nn)
                continue
        final.append((o, n))
    return final


_PARTICLES = ("에서는", "으로는", "에게는", "에서", "으로", "에게", "부터", "까지", "에는", "에", "을", "를", "이", "가", "은", "는",
              "로", "의", "와", "과", "도", "만")


def _trim_common(text: str, o: str, n: str) -> tuple[str, str]:
    """앞뒤 공통 조사·문장부호를 덜어낸다: “제23조에”→“제24조에” ⇒ “제23조”→“제24조”."""
    changed = True
    while changed and o and n:
        changed = False
        for p in [",", ".", ")", "」", "”"] + list(_PARTICLES):
            if p == "로" and (o.endswith("으로") or n.endswith("으로")):
                continue            # '으로'와 '로'는 같은 조사로 보지 않는다(받침에 따라 갈림)
            if o.endswith(p) and n.endswith(p) and len(o) > len(p) and len(n) > len(p):
                ro, rn = o[:-len(p)], n[:-len(p)]
                oo, nn = ro.rstrip(), rn.rstrip()
                # 조사는 앞 낱말에 붙어 있어야 하고(‘같으며, 이’의 ‘이’는 낱말), 현행 문구가 여전히 유일해야 한다
                if oo and nn and text.count(oo) == 1 and (p in ",.)」”" or not (ro[-1:].isspace() or rn[-1:].isspace())):
                    o, n, changed = oo, nn, True
                    break
    return o, n


def apply_phrases(text: str, pairs: list[tuple[str, str]]) -> str:
    """자구 개정을 앞에서부터 한 번씩(이미 바꾼 부분은 다시 보지 않고) 적용."""
    out, pos = [], 0
    for o, n in pairs:
        k = text.find(o, pos)
        if k < 0:
            k = text.find(o)
            if k < 0 or k < pos:
                continue
        out.append(text[pos:k])
        out.append(n)
        pos = k + len(o)
    out.append(text[pos:])
    return "".join(out)


def diff_spans(old: str, new: str) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """대비표용: 각 쪽 문자열을 (조각, 밑줄여부) 목록으로. 가까운 변경(사이 어절 2개 이하)은 한 덩어리로."""
    a = _TOK.findall(old)
    b = _TOK.findall(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = [list(op) for op in sm.get_opcodes()]
    # 사이에 낀 짧은 equal 을 변경으로 흡수
    for k in range(1, len(ops) - 1):
        tag, i1, i2, j1, j2 = ops[k]
        if tag == "equal" and ops[k - 1][0] != "equal" and ops[k + 1][0] != "equal" and \
                sum(1 for t in a[i1:i2] if not t.isspace()) <= 2:
            ops[k][0] = "replace"
    L, R = [], []
    for tag, i1, i2, j1, j2 in ops:
        sa, sb = "".join(a[i1:i2]), "".join(b[j1:j2])
        if tag == "equal":
            L.append((sa, False))
            R.append((sb, False))
        else:
            if sa:
                L.append((sa, not sa.isspace()))
            if sb:
                R.append((sb, not sb.isspace()))
    return _merge_spans(L), _merge_spans(R)


def _merge_spans(sp):
    out = []
    for t, u in sp:
        if out and out[-1][1] == u:
            out[-1] = (out[-1][0] + t, u)
        else:
            out.append((t, u))
    return out


# ---------------------------------------------------------------- 변경 목록
@dataclass
class Change:
    kind: str                      # phrase / whole / add / delete / title / renumber / div_title / div_add
    path: str                      # 현행 기준 위치 (제3조제1항)
    order: tuple = ()
    phrases: list[tuple[str, str]] = field(default_factory=list)
    new_label: str = ""            # renumber 대상, add 의 새 번호
    parent_path: str = ""          # add 의 부모 위치
    block: list[str] = field(default_factory=list)   # '다음과 같이' 본문
    old_unit: Unit | None = None
    new_unit: Unit | None = None
    art_path: str = ""             # 소속 조 표기

    def describe(self) -> str:
        return sentence_for(self)


def _path(art: Unit | None, chain: list[Unit]) -> str:
    s = art.number_label() if art else ""
    for u in chain:
        if u.kind == "article":
            continue
        if u.kind == "paragraph":
            s += f"제{u.num}항"
        elif u.kind == "item":
            s += f"제{u.num}호" + (f"의{u.branch}" if u.branch else "")
        elif u.kind == "subitem":
            s += u.ref_label()
    return s


def _own_label(u: Unit) -> str:
    if u.kind == "article":
        return u.number_label()
    if u.kind == "paragraph":
        return f"제{u.num}항"
    if u.kind == "item":
        return f"제{u.num}호" + (f"의{u.branch}" if u.branch else "")
    if u.kind == "subitem":
        return u.ref_label()
    return u.number_label()


def _block(u: Unit) -> list[str]:
    lines = render_unit(u, with_history=False)
    return [l.strip() if u.kind == "article" else l.strip() for l in lines]


def _unit_text_changes(cu: Unit, nu: Unit, art: Unit, chain_c: list[Unit], chain_n: list[Unit],
                       order: tuple, out: list[Change]):
    """같은 단위로 짝지어진 cu/nu 비교 (하위 포함)."""
    path = _path(art, chain_c)
    # 번호 변경 (삭제된 자리도 번호가 바뀌면 적는다)
    if (cu.num, cu.branch) != (nu.num, nu.branch):
        out.append(Change("renumber", path, order + (-1,), new_label=_own_label(nu), old_unit=cu, new_unit=nu,
                          art_path=art.number_label()))
    if nu.deleted and not cu.deleted:
        out.append(Change("delete", path, order, old_unit=cu, new_unit=nu, art_path=art.number_label()))
        return
    if cu.deleted and not nu.deleted:
        out.append(Change("whole", path, order, block=_block(nu), old_unit=cu, new_unit=nu, art_path=art.number_label()))
        return
    if cu.deleted and nu.deleted:
        return
    if cu.kind == "article" and cu.title != nu.title:
        out.append(Change("title", path, order + (0,), phrases=[(f"({cu.title})", f"({nu.title})")],
                          old_unit=cu, new_unit=nu, art_path=art.number_label()))
    if cu.text != nu.text:
        ph = phrase_changes(cu.text, nu.text)
        changed_ratio = 1 - _sim(cu.text, nu.text)
        if not cu.text or len(ph) > PHRASE_LIMIT or changed_ratio > WHOLE_RATIO or any(not o for o, _ in ph):
            if cu.kind == "article" and not cu.text and nu.text:
                out.append(Change("whole", path, order + (1,), block=_block(nu), old_unit=cu, new_unit=nu,
                                  art_path=art.number_label()))
                return
            out.append(Change("whole", path, order + (1,), block=_block(nu) if nu.kind != "article" else _block(nu),
                              old_unit=cu, new_unit=nu, art_path=art.number_label()))
            return   # 하위까지 통째로 다시 씀
        out.append(Change("phrase", path, order + (1,), phrases=ph, old_unit=cu, new_unit=nu, art_path=art.number_label()))
    # 하위 단위
    for kind in ("paragraph", "item", "subitem"):
        cc = [c for c in cu.children if c.kind == kind]
        nc = [c for c in nu.children if c.kind == kind]
        if not cc and not nc:
            continue
        for k, (c, n) in enumerate(align_units(cc, nc)):
            sub_order = order + (2, k)
            if c is not None and n is not None:
                _unit_text_changes(c, n, art, chain_c + [c], chain_n + [n], sub_order, out)
            elif c is None:
                out.append(Change("add", _path(art, chain_c + [n]), sub_order, new_label=_own_label(n),
                                  parent_path=path, block=_block(n), new_unit=n, art_path=art.number_label()))
            else:
                out.append(Change("delete", _path(art, chain_c + [c]), sub_order, old_unit=c,
                                  art_path=art.number_label()))


def compare(cur: LawDoc, new: LawDoc) -> list[Change]:
    out: list[Change] = []
    ca, na = cur.articles(), new.articles()
    for k, (c, n) in enumerate(align_units(ca, na)):
        order = (k,)
        if c is not None and n is not None:
            # 내용이 대부분 바뀐 조는 '다음과 같이 한다'
            if c.plain() != n.plain() or (c.num, c.branch) != (n.num, n.branch):
                before = len(out)
                _unit_text_changes(c, n, c, [c], [n], order, out)
                parts = [x for x in out[before:] if x.kind not in ("renumber", "title")]
                if len(parts) > 4 and not c.deleted and not n.deleted:
                    keep = [x for x in out[before:] if x.kind in ("renumber",)]
                    del out[before:]
                    out.extend(keep)
                    out.append(Change("whole", c.number_label(), order + (1,), block=_block(n), old_unit=c, new_unit=n,
                                      art_path=c.number_label()))
        elif c is None:
            out.append(Change("add", n.number_label(), order, new_label=n.number_label(), block=_block(n),
                              new_unit=n, art_path=n.number_label()))
        else:
            if not c.deleted:
                out.append(Change("delete", c.number_label(), order, old_unit=c, art_path=c.number_label()))
    # 장·절: 같은 경로끼리, 경로가 바뀌었으면 제목이 같은 것끼리 짝짓는다 (절·관은 '제3장제2절'처럼 구분)
    ci, ni = _div_index(cur), _div_index(new)
    pair: dict[str, str] = {lab: lab for lab in ni if lab in ci and ci[lab][0].title == ni[lab][0].title}
    for lab, (d, _, _) in ni.items():
        if lab in pair:
            continue
        cands = [cl for cl, (c, _, _) in ci.items() if c.kind == d.kind and c.title == d.title and cl not in pair.values()]
        if len(cands) == 1:
            pair[lab] = cands[0]
    for lab, (d, _, _) in ni.items():      # 제목만 바뀐 장·절
        if lab not in pair and lab in ci and ci[lab][0].kind == d.kind and lab not in pair.values():
            pair[lab] = lab
    for lab, (d, _, _) in ni.items():
        cl = pair.get(lab)
        if cl is not None:
            c = ci[cl][0]
            if cl != lab:
                out.append(Change("renumber", cl, (-2, len(out)), new_label=re.findall(r"제\d+(?:편|장|절|관)(?:의\d+)?", lab)[-1]))
            if c.title != d.title:
                out.append(Change("div_title", cl, (-1,), phrases=[(c.title, d.title)]))
        else:
            first = next((a for a in d.iter() if a.kind == "article"), None)
            out.append(Change("div_add", lab, (-1,), new_label=lab, block=[d.heading()],
                              parent_path=first.number_label() if first else ""))
    return out


_DIV_RANK = {"part": 0, "chapter": 1, "section": 2, "subsection": 3}
RE_DIV_PATH = r"(?:제\d+(?:편|장|절|관)(?:의\d+)?)+(?:\([^)]*\))?"


def _div_label(u: Unit, orig: bool) -> str:
    o = getattr(u, "_orig", None) if orig else None
    num, branch = o if o else (u.num, u.branch)
    return f"제{num}{DIVISION_LABEL[u.kind]}" + (f"의{branch}" if branch else "")


def _div_index(doc: LawDoc, orig: bool = False) -> dict[str, tuple[Unit, list, Unit | None]]:
    """'제3장', '제3장제2절' → (단위, 담긴 목록, 담은 단위). 편·장 번호는 규정 전체에서, 절·관은 장 안에서 매긴다.
    orig=True 이면 개정문 적용 중 현행 번호(_orig)로 찾는다(새로 생긴 장·절은 지금 번호)."""
    out: dict = {}

    def walk(lst, owner, anc):
        for u in lst:
            if u.kind not in DIVISION_LABEL:
                continue
            lab = _div_label(u, orig)
            pre = "".join(anc[k] for k in ("chapter", "section") if k in anc and _DIV_RANK[k] < _DIV_RANK[u.kind]) \
                if u.kind in ("section", "subsection") else ""
            key = pre + lab
            if key in out:            # 원문 오타로 번호가 겹치면 '제5장(보 칙)'처럼 제목으로 구분
                key += f"({u.title})"
            out.setdefault(key, (u, lst, owner))
            walk(u.children, u, {**anc, u.kind: lab})
    walk(doc.body, None, {})
    return out


def _apply_division(doc: LawDoc, d: "Directive", find_article) -> bool | None:
    """장·절 문장. 해당 없으면 None."""
    sent = d.sentence
    m = re.match(r"^(" + RE_DIV_PATH + r")의 제목 “(.*)”(?:을|를) “(.*)”(?:으로|로) 한다\.?$", sent)
    if m:
        hit = _div_index(doc, True).get(m.group(1))
        if hit is None:
            return False
        hit[0].title = m.group(3)
        return True
    m = re.match(r"^(" + RE_DIV_PATH + r")(?:을|를)\s*(?:" + RE_DIV_PATH + r")?제(\d+)(?:편|장|절|관)(?:의(\d+))?(?:으로|로) 한다\.?$", sent)
    if m:
        hit = _div_index(doc, True).get(m.group(1))
        if hit is None:
            return False
        hit[0].num, hit[0].branch = int(m.group(2)), int(m.group(3) or 0)
        return True
    m = re.match(r"^(?:(제(\d+)조(?:의(\d+))?)\s*앞에\s*)?(" + RE_DIV_PATH + r")(?:을|를)\s*다음과 같이 신설한다", sent)
    if not m:
        return None
    hm = re.match(r"^\s*제(\d+)(편|장|절|관)(?:의(\d+))?\s*(.*)$", d.block[0]) if d.block else None
    if hm is None:
        return False
    from .model import LABEL_DIVISION
    kind = LABEL_DIVISION[hm.group(2)]
    nu = Unit(kind=kind, num=int(hm.group(1)), branch=int(hm.group(3) or 0), title=hm.group(4).strip())
    if not m.group(1):
        doc.body.append(nu)
        return True
    a = find_article(int(m.group(2)), int(m.group(3) or 0))
    where = doc.parent_of(a) if a is not None else None
    if where is None:
        return False
    lst, idx = where
    owner = next((x for x in doc.divisions() if x.children is lst), None)
    if owner is not None and _DIV_RANK[owner.kind] >= _DIV_RANK[kind]:
        return False                 # 절 안의 조 앞에 장을 넣는 식은 구조가 모호하다
    j = idx + 1
    while j < len(lst) and not (lst[j].kind in DIVISION_LABEL and _DIV_RANK[lst[j].kind] <= _DIV_RANK[kind]):
        j += 1
    nu.children = lst[idx:j]
    lst[idx:j] = [nu]
    return True


# ---------------------------------------------------------------- 문장 만들기
def q(s: str) -> str:
    """인용 부호. 안쪽 큰따옴표는 작은따옴표로 바꾼다(입안 기준)."""
    return "“" + s.replace("“", "‘").replace("”", "’").replace('"', "'") + "”"


def unq(s: str, target: str) -> str:
    """q() 의 역변환 — 대상 본문에 그대로 있으면 그대로, 아니면 작은따옴표를 큰따옴표로."""
    if s in target:
        return s
    t = s.replace("‘", "“").replace("’", "”")
    return t if t in target else s


def _phrase_clause(pairs: list[tuple[str, str]], each: bool = False) -> str:
    parts = []
    for o, n in pairs:
        if n:
            e = each or getattr(o, "each", False)
            parts.append(f"{q(o)}{josa(o, '을/를')} {'각각 ' if e else ''}{q(n)}{josa(n, '으로/로')}")
        else:
            parts.append(f"{q(o)}{josa(o, '을/를')} 삭제")
    return " 하고, ".join(parts)


def sentence_for(c: Change) -> str:
    p = c.path
    if c.kind == "phrase":
        dels = [x for x in c.phrases if not x[1]]
        reps = [x for x in c.phrases if x[1]]
        cl = []
        if reps:
            cl.append(_phrase_clause(reps))
        for o, _ in dels:
            cl.append(f"{q(o)}{josa(o, '을/를')} 삭제")
        return f"{p} 중 " + " 하고, ".join(cl) + (" 한다." if reps or dels else "")
    if c.kind == "whole":
        return f"{p}{josa(p, '을/를')} 다음과 같이 한다."
    if c.kind == "add":
        if c.parent_path:
            return f"{c.parent_path}에 {c.new_label}{josa(c.new_label, '을/를')} 다음과 같이 신설한다."
        return f"{c.new_label}{josa(c.new_label, '을/를')} 다음과 같이 신설한다."
    if c.kind == "delete":
        return f"{p}{josa(p, '을/를')} 삭제한다."
    if c.kind == "title":
        o, n = c.phrases[0]
        return f"{p}의 제목 {q(o)}{josa(o, '을/를')} {q(n)}{josa(n, '으로/로')} 한다."
    if c.kind == "renumber":
        return f"{p}{josa(p, '을/를')} {c.new_label}{josa(c.new_label, '으로/로')} 한다."
    if c.kind == "div_title":
        o, n = c.phrases[0]
        return f"{p}의 제목 {q(o)}{josa(o, '을/를')} {q(n)}{josa(n, '으로/로')} 한다."
    if c.kind == "div_add":
        anchor = f"{c.parent_path} 앞에 " if c.parent_path else ""
        return f"{anchor}{c.new_label}{josa(c.new_label, '을/를')} 다음과 같이 신설한다."
    return p


def _join_paths(paths: list[str]) -> str:
    """['제3조제1항','제3조제2항','제5조'] → '제3조제1항ㆍ제2항 및 제5조'."""
    shown = []
    prev_art = None
    for p in paths:
        m = re.match(r"^(제\d+조(?:의\d+)?)(.*)$", p)
        art, rest = (m.group(1), m.group(2)) if m else (p, "")
        if art == prev_art and rest:
            shown.append(rest)
        else:
            shown.append(p)
        prev_art = art
    if len(shown) == 1:
        return shown[0]
    return "ㆍ".join(shown[:-1]) + " 및 " + shown[-1] if len(shown) <= 3 else ", ".join(shown[:-1]) + " 및 " + shown[-1]


def build_amendment_lines(cur: LawDoc, new: LawDoc, changes: list[Change] | None = None,
                          group_same: bool = True) -> list[str]:
    """개정문 본문 줄 목록."""
    name = cur.name or new.name
    if new.amend_type == "전부개정":
        from .render import render_doc
        body = render_doc(new, with_history=False, with_header=False).strip().split("\n")
        return [f"{name} 전부를 다음과 같이 개정한다.", ""] + body
    if new.amend_type == "폐지":
        return [f"{name}{josa(name, '을/를')} 폐지한다."]
    if new.amend_type == "제정":
        from .render import render_doc
        return render_doc(new, with_history=False, with_header=False).strip().split("\n")
    if changes is None:
        changes = compare(cur, new)
    changes = sorted(changes, key=lambda c: c.order)
    lines = [f"{name} 일부를 다음과 같이 개정한다.", ""]
    i = 0
    pending_prefix = ""
    while i < len(changes):
        c = changes[i]
        # 같은 자구 한 쌍만 바뀐 연속 단위 묶기
        if group_same and c.kind == "phrase" and len(c.phrases) == 1:
            grp = [c]
            j = i + 1
            each = lambda x: getattr(x.phrases[0][0], "each", False)
            while j < len(changes) and changes[j].kind == "phrase" and changes[j].phrases == c.phrases \
                    and each(changes[j]) == each(c):
                grp.append(changes[j])
                j += 1
            if len(grp) > 1:
                o, n = c.phrases[0]
                paths = _join_paths([g.path for g in grp])
                s = f"{paths} 중 {q(o)}{josa(o, '을/를')} 각각 {q(n)}{josa(n, '으로/로')} 한다." if n else \
                    f"{paths} 중 {q(o)}{josa(o, '을/를')} 각각 삭제한다."
                if pending_prefix and s.startswith(c.art_path) and all(g.art_path == c.art_path for g in grp):
                    s = "같은 조" + (" " if s[len(c.art_path):].startswith("제") else "") + s[len(c.art_path):]
                lines.append(pending_prefix + s)
                pending_prefix = ""
                i = j
                continue
        # 번호 이동은 다음 문장과 '하고,'로 잇는다
        if c.kind == "renumber":
            nxt = changes[i + 1] if i + 1 < len(changes) else None
            clause = f"{c.path}{josa(c.path, '을/를')} {c.new_label}{josa(c.new_label, '으로/로')} 하고, "
            if nxt is not None and c.art_path and nxt.art_path == c.art_path and nxt.kind not in ("renumber", "add", "div_add"):
                pending_prefix += clause
                i += 1
                continue
            lines.append(pending_prefix + clause[:-4] + "한다.")
            pending_prefix = ""
            i += 1
            continue
        s = sentence_for(c)
        if pending_prefix:
            # '제5조를 제6조로 하고, 같은 조 제1항 중 …'
            if c.path.startswith(c.art_path):
                s = "같은 조" + (" " + s[len(c.art_path):].lstrip() if s[len(c.art_path):].startswith("제") else s[len(c.art_path):])
        lines.append(pending_prefix + s)
        pending_prefix = ""
        if c.block and c.kind in ("whole", "add", "div_add"):
            lines.extend(c.block)
        i += 1
    if pending_prefix:
        lines.append(pending_prefix.rstrip(", ").rstrip("하고").rstrip() + "한다.")
    return lines


def build_amendment_text(cur: LawDoc, new: LawDoc, addenda_text: str = "") -> str:
    lines = build_amendment_lines(cur, new)
    if addenda_text:
        lines += ["", "부칙", addenda_text]
    return "\n".join(lines)


# ---------------------------------------------------------------- 신ㆍ구조문대비표
Span = list[tuple[str, bool]]


@dataclass
class CompareRow:
    left: list[Span]
    right: list[Span]


def _label_line(u: Unit) -> str:
    return u.heading() if u.kind == "article" else u.number_label()


def _same_children_rows(c: Unit, n: Unit) -> list[tuple[Span, Span]]:
    """조 안의 단위별 줄을 만든다(변경 없는 단위는 생략 표기)."""
    rows: list[tuple[Span, Span]] = []
    run: list[Unit] = []

    def flush():
        if not run:
            return
        a, b = run[0], run[-1]
        lab = a.number_label() if a is b else f"{a.number_label()} ∼ {b.number_label()}"
        pad = "  " if a.kind in ("item", "subitem") else ""
        rows.append(([(f"{pad}{lab} (생 략)", False)], [(f"{pad}{lab} (현행과 같음)", False)]))
        run.clear()

    for kind in ("paragraph", "item", "subitem"):
        cc = [x for x in c.children if x.kind == kind]
        nc = [x for x in n.children if x.kind == kind]
        for x, y in align_units(cc, nc):
            if x is not None and y is not None and x.plain() == y.plain() and (x.num, x.branch) == (y.num, y.branch):
                run.append(x)
                continue
            flush()
            pad = "  " if (x or y).kind in ("item", "subitem") else ""
            if x is None:
                rows.append(([(f"{pad}<신 설>", False)], [(f"{pad}{y.number_label()} ", False), (y.text, True)]))
                for gc in y.children:
                    for line in render_unit(gc, False):
                        rows.append(([], [(line, True)]))
            elif y is None or (y.deleted and not x.deleted):
                rows.append(([(f"{pad}{x.number_label()} ", False), (x.text, True)], [(f"{pad}{x.number_label()} <삭 제>", False)]))
            else:
                l, r = diff_spans(x.text, y.text)
                ln = x.number_label() + " "
                rn = y.number_label() + " "
                rows.append(([(pad + ln, (x.num, x.branch) != (y.num, y.branch))] + l,
                             [(pad + rn, (x.num, x.branch) != (y.num, y.branch))] + _dash_unchanged(r)))
                sub = _same_children_rows(x, y)
                rows.extend(sub)
    flush()
    return rows


def _dash_unchanged(spans: Span) -> Span:
    """개정안 쪽: 변경 없는 부분을 '---' 로 줄이고 밑줄 부분과는 한 칸 띄운다."""
    out: Span = []
    for k, (t, u) in enumerate(spans):
        if u or not t.strip():
            out.append((t, u))
            continue
        dash = "-" * max(3, min(len(t.strip()), 16))     # 좁은 칸에서 줄표만 한 줄을 차지하지 않게 짧게
        lead = " " if k > 0 else ""
        trail = " " if k < len(spans) - 1 else ""
        out.append((lead + dash + trail, False))
    return _merge_spans(out)


def build_compare_table(cur: LawDoc, new: LawDoc) -> list[CompareRow]:
    rows: list[CompareRow] = []
    ca, na = cur.articles(), new.articles()
    pairs = align_units(ca, na)
    skipped: list[Unit] = []

    def flush_skip():
        if skipped:
            a, b = skipped[0], skipped[-1]
            lab = a.number_label() if a is b else f"{a.number_label()} ∼ {b.number_label()}"
            rows.append(CompareRow([[(f"{lab} (생 략)", False)]], [[(f"{lab} (현행과 같음)", False)]]))
            skipped.clear()

    for c, n in pairs:
        if c is not None and n is not None and c.plain() == n.plain() and (c.num, c.branch) == (n.num, n.branch):
            skipped.append(c)
            continue
        flush_skip()
        if c is None:
            right = [[(line, True)] for line in render_unit(n, False)]
            rows.append(CompareRow([[("<신 설>", False)]], right))
            continue
        if n is None or (n.deleted and not c.deleted):
            left = [[(line, True)] for line in render_unit(c, False)]
            rows.append(CompareRow(left, [[(f"{c.number_label()} 삭제", True)]]))
            continue
        head_l: Span = [(c.number_label(), (c.num, c.branch) != (n.num, n.branch))]
        head_r: Span = [(n.number_label(), (c.num, c.branch) != (n.num, n.branch))]
        if c.title or n.title:
            head_l.append((f"({c.title})", c.title != n.title))
            head_r.append((f"({n.title})", c.title != n.title))
        if c.text or n.text:
            l, r = diff_spans(c.text, n.text)
            head_l += [(" ", False)] + l
            head_r += [(" ", False)] + _dash_unchanged(r)
        left = [head_l]
        right = [head_r]
        for l, r in _same_children_rows(c, n):
            left.append(l)
            right.append(r)
        rows.append(CompareRow(left, right))
    flush_skip()
    return rows


def compare_table_html(cur: LawDoc, new: LawDoc, title: str = "") -> str:
    rows = build_compare_table(cur, new)

    def cell(lines):
        out = []
        for spans in lines:
            s = "".join(f"<u>{_esc(t)}</u>" if u else _esc(t) for t, u in spans)
            out.append(f"<p>{s}</p>")
        return "".join(out)
    body = "".join(f"<tr><td>{cell(r.left)}</td><td>{cell(r.right)}</td></tr>" for r in rows)
    t = title or f"{cur.name or new.name} 신ㆍ구조문대비표"
    return (f"<h3 style='text-align:center'>{_esc(t)}</h3>"
            "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;width:100%'>"
            "<tr><th width='50%'>현 행</th><th width='50%'>개 정 안</th></tr>" + body + "</table>")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- 개정문 → 개정본문 (개정문분석)
RE_PATH = r"제\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호(?:의\d+)?)?(?:[가-하]목)?|제\d+항(?:제\d+호(?:의\d+)?)?(?:[가-하]목)?|제\d+호(?:의\d+)?(?:[가-하]목)?"
RE_PATH_PARTS = re.compile(r"제(\d+)조(?:의(\d+))?|제(\d+)항|제(\d+)호(?:의(\d+))?|([가-하])목")
RE_DIRECTIVE = re.compile(r"^(?:같은\s*조\s*)?(?:" + RE_PATH + r").*(한다|신설한다|삭제한다)\.\s*$")
RE_DIV_DIRECTIVE = re.compile(r"^(?:" + RE_DIV_PATH + r")(?:을|를|의 제목)\s.*한다\.\s*$")


@dataclass
class Directive:
    sentence: str
    block: list[str] = field(default_factory=list)


def split_directives(text: str) -> tuple[str, list[Directive]]:
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n")]
    head = ""
    out: list[Directive] = []
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if not head and "다음과 같이 개정한다" in s:
            head = s
            continue
        if s.startswith("부칙") or s.startswith("부 칙"):
            break
        is_dir = bool(RE_DIRECTIVE.match(s)) and not re.match(r"^제\d+조(?:의\d+)?\s*\(", s) \
            or bool(RE_DIV_DIRECTIVE.match(s))
        if is_dir:
            out.append(Directive(s))
        elif out:
            out[-1].block.append(s)
    return head, out


def _num_is(u: Unit, num: int, branch: int, fresh: bool) -> bool:
    """개정문의 번호는 현행 번호다. 현행에 있던 단위는 현행 번호(_orig)로, 새로 생긴 단위는 지금 번호로 찾는다."""
    o = getattr(u, "_orig", None)
    if fresh:
        return o is None and (u.num, u.branch) == (num, branch)
    return o == (num, branch) if o is not None else False


def _find(units, pred_kind, num: int, branch: int = 0) -> Unit | None:
    cand = [u for u in units if pred_kind(u)]
    return next((u for u in cand if _num_is(u, num, branch, False)), None) or \
        next((u for u in cand if _num_is(u, num, branch, True)), None)


def _resolve_path(doc: LawDoc, path: str, ctx_art: Unit | None = None) -> list[Unit]:
    """'제3조제1항제2호' → [조, 항, 호] 체인."""
    chain: list[Unit] = []
    cur: Unit | None = None
    for m in RE_PATH_PARTS.finditer(path):
        if m.group(1):
            cur = _find(doc.articles(), lambda u: True, int(m.group(1)), int(m.group(2) or 0))
            if cur is None:
                return []
            chain = [cur]
        else:
            if cur is None:
                cur = ctx_art
                if cur is None:
                    return []
                chain = [cur]
            if m.group(3):
                nxt = _find(cur.children, lambda c: c.kind == "paragraph", int(m.group(3)))
            elif m.group(4):
                nxt = _find(cur.children, lambda c: c.kind == "item", int(m.group(4)), int(m.group(5) or 0))
            else:
                from .model import subitem_number
                nxt = _find(cur.children, lambda c: c.kind == "subitem", subitem_number(m.group(6)))
            if nxt is None:
                return []
            cur = nxt
            chain.append(cur)
    return chain


def _all_units(lst):
    for u in lst:
        yield u
        yield from _all_units(u.children)


def _moved(u: Unit) -> bool:
    return getattr(u, "_orig", None) not in (None, (u.num, u.branch))


def _claims(u: Unit) -> bool:
    """이 번호를 차지하는 단위: 살아 있거나, 번호를 옮겨 온 단위(옮겨 온 '삭제' 자리 포함)."""
    return not u.deleted or _moved(u)


def _drop_taken_over(lst: list[Unit], art_keys: set):
    """'삭제' 자리의 번호를 다른 단위가 당겨 받았으면 그 자리 표시는 없앤다
    (조는 장이 달라도 같은 번호를 쓸 수 없으므로 규정 전체에서 본다)."""
    keys = {(u.kind, u.num, u.branch) for u in lst if _claims(u)}
    taken = lambda u: (u.num, u.branch) in art_keys if u.kind == "article" else (u.kind, u.num, u.branch) in keys
    lst[:] = [u for u in lst if _claims(u) or not taken(u)]
    for u in lst:
        _drop_taken_over(u.children, art_keys)


def _sort_numbered(lst: list[Unit]):
    """번호를 바꾼 뒤 같은 목록 안의 조·항·호를 번호 순서로 (장·절 위치는 그대로)."""
    for kind in ("article", "paragraph", "item", "subitem"):
        idx = [i for i, u in enumerate(lst) if u.kind == kind]
        units = sorted((lst[i] for i in idx), key=lambda u: (u.num, u.branch))
        for i, u in zip(idx, units):
            lst[i] = u
    for u in lst:
        _sort_numbered(u.children)


def _split_clauses(sentence: str) -> list[str]:
    s = sentence.rstrip(".")
    return [x.strip() for x in re.split(r"\s*하고,\s*", s)]


def apply_amendment(cur: LawDoc, text: str) -> tuple[LawDoc, list[str]]:
    """개정문을 현행에 적용한 개정본문과 처리 로그."""
    from .parser import parse_text
    doc = cur.clone()
    for u in _all_units(doc.body):
        u._orig = (u.num, u.branch)
    _, directives = split_directives(text)
    log: list[str] = []
    ctx_art: Unit | None = None
    for d in (x for dd in directives for x in _split_renumber(dd)):
        sent = d.sentence
        dv = _apply_division(doc, d, lambda n, b: _find(doc.articles(), lambda u: True, n, b))
        if dv is not None:
            log.append(("[적용] " if dv else "[해석불가] ") + sent)
            continue
        m_paths = re.match(r"^((?:같은\s*조\s*)?(?:" + RE_PATH + r")(?:\s*(?:및|ㆍ|·|,)\s*(?:" + RE_PATH + r"))*)", sent)
        if not m_paths:
            log.append(f"[건너뜀] {sent}")
            continue
        path_expr = m_paths.group(1)
        rest = sent[m_paths.end():]
        paths = []
        last_art = ctx_art
        for p in re.split(r"\s*(?:및|ㆍ|·|,)\s*", path_expr.replace("같은 조", "").replace("같은조", "")):
            p = p.strip()
            if not p:
                continue
            chain = _resolve_path(doc, p, last_art)
            if chain:
                last_art = chain[0]
            paths.append((p, chain))
        if paths and paths[0][1]:
            ctx_art = paths[0][1][0]
        try:
            ok = _apply_one(doc, paths, rest, d.block, parse_text, log, sent)
        except Exception as e:     # noqa: BLE001 — 개별 문장 실패는 기록 후 계속
            ok = False
            log.append(f"[오류] {sent}: {e}")
        if ok:
            log.append(f"[적용] {sent}")
    for nu in doc.__dict__.pop("_pending_adds", []):
        _insert_article(doc, nu)
    if any(_moved(u) for u in _all_units(doc.body)):
        _drop_taken_over(doc.body, {(a.num, a.branch) for a in doc.articles() if _claims(a)})
        _sort_numbered(doc.body)
    for u in _all_units(doc.body):
        u.__dict__.pop("_orig", None)
    return doc, log


def _insert_article(doc: LawDoc, nu: Unit):
    """번호 순서에 맞는 자리(바로 앞 번호 조 다음)에 조를 넣는다."""
    arts = doc.articles()
    prev = None
    for a in arts:
        if (a.num, a.branch) < (nu.num, nu.branch):
            prev = a
    if prev is None:
        (doc.body if not arts else doc.parent_of(arts[0])[0]).insert(0, nu)
    else:
        lst, idx = doc.parent_of(prev)
        lst.insert(idx + 1, nu)


def _split_renumber(d: Directive) -> list[Directive]:
    """'제5조를 제6조로 하고, 같은 조 제1항 중 …' → 번호 변경 문장 + '제5조제1항 중 …'
    (개정문의 번호는 모두 현행 번호이므로 뒷부분도 현행 번호 제5조로 찾는다)."""
    m = re.match(r"^(" + RE_PATH + r")\s*(?:을|를)\s*(" + RE_PATH + r")\s*(?:으로|로)\s*하고,\s*(같은\s*조\s*)?(.*)$", d.sentence)
    if not m:
        return [d]
    old, new, rest = m.group(1), m.group(2), m.group(4)
    first = Directive(f"{old}{josa(old, '을/를')} {new}{josa(new, '으로/로')} 한다.")
    if not m.group(3):
        return [first] + _split_renumber(Directive(rest, d.block))
    art = re.match(r"제\d+조(?:의\d+)?", old)
    if art is None:
        return [d]
    old = art.group(0)          # '같은 조'는 조를 가리킨다
    return [first] + _split_renumber(Directive(old + ("" if rest[:1] in ("를", "을", "의", "에") or rest.startswith("제") else " ") + rest,
                                               d.block))


def _parse_block_unit(block: list[str], kind: str, parse_text):
    """'다음과 같이' 아래 본문을 단위 하나로 해석 (번호는 호출한 쪽에서 맞춘다)."""
    if not block:
        return None
    if kind == "article":
        nd = parse_text("\n".join(["임시"] + block))
        arts = nd.articles()
        return arts[0] if arts else None
    lines = list(block)
    first = lines[0].lstrip()
    from .model import CIRCLED
    if kind == "paragraph" and first and first[0] in CIRCLED:
        lines[0] = "①" + first[1:]
        fake = "임시\n제1조(임시) 임시\n" + "\n".join(lines)
    elif kind == "item":
        lines[0] = re.sub(r"^\d+(?:의\d+)?\.", "1.", first)
        fake = "임시\n제1조(임시) 임시\n" + "\n".join(lines)
    elif kind == "subitem":
        lines[0] = re.sub(r"^[가-하]\.", "가.", first)
        fake = "임시\n제1조(임시) 임시\n1. 임시\n" + "\n".join(lines)
    else:
        return None
    nd = parse_text(fake)
    a = nd.articles()[0]
    for u in a.iter():
        if u.kind == kind and u is not a and u.text != "임시":
            return u
    return None


def _apply_one(doc: LawDoc, paths, rest: str, block: list[str], parse_text, log, sent) -> bool:
    from .model import subitem_number
    # 1) 자구: 중 “A”를 “B”로 하고, “C”를 “D”로 한다
    if rest.lstrip().startswith("중"):
        pairs = re.findall(r"[“\"]([^”\"]*)[”\"]\s*(?:을|를)\s*(?:각각\s*)?(?:[“\"]([^”\"]*)[”\"]\s*(?:으로|로)|삭제)", rest)
        if not pairs:
            log.append(f"[해석불가] {sent}")
            return False
        for p, chain in paths:
            if not chain:
                log.append(f"[위치없음] {p}")
                continue
            u = chain[-1]
            fixed = []
            for o, n in pairs:
                o2 = unq(o, u.text)
                # 현행 문구를 큰따옴표로 되돌렸으면 개정 문구도 같은 방식으로
                n2 = n.replace("‘", "“").replace("’", "”") if o2 != o else n
                fixed.append((o2, n2))
            pairs = fixed
            for o, n in pairs:
                if o not in u.text:
                    log.append(f"[문구없음] {p}: “{o}”")
            if len(paths) == 1 and "각각" in rest and len(pairs) == 1:
                u.text = u.text.replace(pairs[0][0], pairs[0][1])      # 한 단위 안의 같은 자구 전부
            else:
                u.text = apply_phrases(u.text, pairs) if len(paths) == 1 else apply_phrases(u.text, [x for x in pairs if x[0] in u.text])
        return True
    # 2) 제목
    m = re.match(r"^\s*의\s*제목\s*[“\"]([^”\"]*)[”\"]\s*(?:을|를)\s*[“\"]([^”\"]*)[”\"]", rest)
    if m:
        for p, chain in paths:
            if chain:
                chain[0].title = m.group(2).strip("()（）")
        return True
    # 3) 삭제
    if re.match(r"^\s*(?:을|를)\s*삭제한다", rest):
        for p, chain in paths:
            if chain:
                u = chain[-1]
                u.deleted, u.text, u.children = True, "", []
                if u.kind == "article":
                    u.title = ""
        return True
    # 4) 다음과 같이 한다 (전체 교체)
    if re.match(r"^\s*(?:을|를)\s*다음과\s*같이\s*한다", rest):
        p, chain = paths[0]
        if not chain:
            log.append(f"[위치없음] {p}")
            return False
        u = chain[-1]
        nu = _parse_block_unit(block, u.kind, parse_text)
        if nu is None:
            log.append(f"[본문해석불가] {sent}")
            return False
        u.title, u.text, u.children, u.deleted = nu.title, nu.text, nu.children, False
        return True
    # 5) 신설: '제5조의2를 다음과 같이 신설한다' / '제3조에 제4항을 다음과 같이 신설한다'
    m = re.match(r"^\s*에\s*(" + RE_PATH + r")\s*(?:을|를)\s*다음과\s*같이\s*신설한다", rest)
    if m:
        p, chain = paths[0]
        if not chain:
            return False
        parent = chain[-1]
        lab = m.group(1)
        kind = "paragraph" if lab.endswith("항") else "item" if "호" in lab else "subitem"
        nu = _parse_block_unit(block, kind, parse_text)
        if nu is None:
            return False
        pm = RE_PATH_PARTS.search(lab)
        if kind == "paragraph":
            nu.num = int(pm.group(3))
        elif kind == "item":
            nu.num, nu.branch = int(pm.group(4)), int(pm.group(5) or 0)
        else:
            nu.num = subitem_number(pm.group(6))
        # 번호 순서에 맞게 삽입
        sibs = parent.children
        pos = len(sibs)
        for i, s in enumerate(sibs):
            if s.kind == kind and (s.num, s.branch) > (nu.num, nu.branch):
                pos = i
                break
        sibs.insert(pos, nu)
        return True
    m = re.match(r"^\s*(?:을|를)\s*다음과\s*같이\s*신설한다", rest)
    if m:
        p, _ = paths[0]
        pm = RE_PATH_PARTS.search(p)
        if pm and pm.group(1):
            nu = _parse_block_unit(block, "article", parse_text)
            if nu is None:
                return False
            nu.num, nu.branch = int(pm.group(1)), int(pm.group(2) or 0)
            # 신설 조의 번호는 개정 후 번호다 — 번호 이동을 모두 마친 뒤 자리를 잡는다
            doc.__dict__.setdefault("_pending_adds", []).append(nu)
            return True
    # 6) 번호 변경 '제5조를 제6조로 한다'
    m = re.match(r"^\s*(?:을|를)\s*(?:각각\s*)?(" + RE_PATH + r")\s*(?:으로|로)\s*한다", rest)
    if m:
        p, chain = paths[0]
        if chain:
            u = chain[-1]
            pm = RE_PATH_PARTS.search(m.group(1))
            if pm.group(1):
                u.num, u.branch = int(pm.group(1)), int(pm.group(2) or 0)
            elif pm.group(3):
                u.num = int(pm.group(3))
            elif pm.group(4):
                u.num, u.branch = int(pm.group(4)), int(pm.group(5) or 0)
            return True
    log.append(f"[해석불가] {sent}")
    return False
