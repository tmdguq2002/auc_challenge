"""조문 번호 조작: 신설·삭제·이동·맞교환·일괄변경 + 본문 인용 자동 갱신."""
from __future__ import annotations

import re

from .model import LawDoc, Unit, DIVISION_LABEL
from .refs import extract_refs_text, find_abbreviations, iter_text_units

Key = tuple[int, int]   # (번호, 가지번호)


def art_key(a: Unit) -> Key:
    return (a.num, a.branch)


def key_label(k: Key) -> str:
    return f"제{k[0]}조" + (f"의{k[1]}" if k[1] else "")


def _all_article_lists(doc: LawDoc) -> list[list[Unit]]:
    """조를 직접 담고 있는 리스트들(본칙/장/절)."""
    out = []

    def walk(lst):
        if any(u.kind == "article" for u in lst):
            out.append(lst)
        for u in lst:
            if u.kind in DIVISION_LABEL:
                walk(u.children)
    walk(doc.body)
    return out


def update_internal_refs(doc: LawDoc, mapping: dict[Key, Key], para_map: dict[tuple[Key, int], int] | None = None) -> int:
    """본문 안의 '제N조' 인용을 mapping 에 따라 바꾼다. 바뀐 개수를 돌려준다."""
    if not mapping and not para_map:
        return 0
    full = "\n".join(u.text for u, _, _ in iter_text_units(doc, True))
    abbrs = find_abbreviations(full)
    changed = 0
    for u, art, para in iter_text_units(doc, True):
        if not u.text:
            continue
        refs = extract_refs_text(u.text, abbrs, art.num if art else 0, art.branch if art else 0, para.num if para else 0)
        new = u.text
        for r in sorted(refs, key=lambda r: -r.start):
            if r.target:
                continue
            old_key = (r.article, r.article_branch)
            seg = new[r.start:r.end]
            rep = seg
            if not r.relative and old_key in mapping and mapping[old_key] != old_key:
                nk = mapping[old_key]
                rep = re.sub(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?", key_label(nk), rep)
            pk = (old_key, r.para)
            if para_map and r.para and pk in para_map and para_map[pk] != r.para:
                rep = re.sub(r"제\s*\d+\s*항", f"제{para_map[pk]}항", rep, count=1)
            if rep != seg:
                new = new[:r.start] + rep + new[r.end:]
                changed += 1
        u.text = new
    return changed


def renumber_sequential(doc: LawDoc, remove_branches: bool = True, update_refs: bool = True) -> dict[Key, Key]:
    """조 번호를 1부터 차례로 다시 매긴다(전부개정·일괄변경). 삭제된 조는 제거."""
    for lst in _all_article_lists(doc):
        lst[:] = [u for u in lst if not (u.kind == "article" and u.deleted)]
    mapping: dict[Key, Key] = {}
    n = 0
    prev: Key | None = None
    for a in doc.articles():
        old = art_key(a)
        if remove_branches or a.branch == 0:
            n += 1
            new = (n, 0)
        else:
            new = (n, a.branch)
        mapping[old] = new
        a.num, a.branch = new
        prev = new
    if update_refs:
        update_internal_refs(doc, mapping)
    # 장·절 번호도 정리: 편·장은 처음부터 이어서, 절은 장마다, 관은 절마다 1부터
    cnt = {k: 0 for k in DIVISION_LABEL}
    reset = {"part": (), "chapter": ("section", "subsection"), "section": ("subsection",), "subsection": ()}
    for d in doc.divisions():
        cnt[d.kind] += 1
        for k in reset[d.kind]:
            cnt[k] = 0
        d.num, d.branch = cnt[d.kind], 0
    return mapping


def renumber_children(u: Unit, kind: str) -> dict[int, int]:
    """항/호/목 번호를 차례로 다시 매김."""
    mp = {}
    n = 0
    for c in u.children:
        if c.kind == kind:
            n += 1
            mp[c.num] = n
            c.num, c.branch = n, 0
    return mp


def next_branch_key(doc: LawDoc, after: Unit) -> Key:
    """after 다음에 끼워 넣을 가지조 번호 (제5조 → 제5조의2, 제5조의2 → 제5조의3)."""
    base = after.num
    used = {a.branch for a in doc.articles() if a.num == base}
    b = max(after.branch, 1) + 1
    while b in used:
        b += 1
    return (base, b)


def insert_article(doc: LawDoc, after: Unit | None, title: str = "", text: str = "",
                   mode: str = "branch") -> Unit:
    """조 신설. mode='branch' → 가지조(제N조의M), 'renumber' → 뒤 조문 번호를 밀어냄."""
    new = Unit(kind="article", title=title, text=text)
    if after is None:
        lst = _all_article_lists(doc)[0] if _all_article_lists(doc) else doc.body
        lst.insert(0, new)
        new.num = 1
        if mode == "renumber":
            _shift_after(doc, new)
        return new
    if mode == "branch":
        # 제18조 뒤에 신설하는데 제18조의2가 이미 있으면 그 뒤(제18조의3)에 둔다
        same = [a for a in doc.articles() if a.num == after.num and a.branch > after.branch]
        if same:
            after = same[-1]
    lst, idx = doc.parent_of(after)
    lst.insert(idx + 1, new)
    if mode == "branch":
        new.num, new.branch = next_branch_key(doc, after)
    else:
        new.num, new.branch = after.num + 1, 0
        _shift_after(doc, new)
    return new


def _shift_after(doc: LawDoc, new: Unit):
    mapping = {}
    seen = False
    for a in doc.articles():
        if a is new:
            seen = True
            continue
        if seen and a.num >= new.num:
            old = art_key(a)
            a.num += 1
            mapping[old] = art_key(a)
    update_internal_refs(doc, mapping)


def delete_article(doc: LawDoc, a: Unit, mode: str = "mark", date: str = "") -> None:
    """mode='mark' → '삭제' 표시(일부개정 관행), 'remove' → 제거 후 번호 정리."""
    if mode == "mark":
        a.deleted = True
        a.children = []
        a.text = ""
        a.title = ""
        a.history = f"<{date}>" if date else ""
        return
    lst, idx = doc.parent_of(a)
    del lst[idx]
    mapping = {}
    for b in doc.articles():
        if b.num > a.num and a.branch == 0:
            old = art_key(b)
            b.num -= 1
            mapping[old] = art_key(b)
    update_internal_refs(doc, mapping)


def delete_child(doc: LawDoc, parent: Unit, child: Unit, mode: str = "mark") -> None:
    if mode == "mark":
        child.deleted = True
        child.text = ""
        child.children = []
        return
    parent.children.remove(child)
    mp = renumber_children(parent, child.kind)
    if child.kind == "paragraph" and parent.kind == "article":
        pm = {((parent.num, parent.branch), o): n for o, n in mp.items()}
        update_internal_refs(doc, {}, pm)


def move_article(doc: LawDoc, a: Unit, target_after: Unit | None, renumber: bool = True,
                 mark_moved: bool = False, date: str = "") -> dict[Key, Key]:
    """조문이동. target_after 다음 위치로 옮긴다."""
    old_label = a.number_label()
    lst, idx = doc.parent_of(a)
    del lst[idx]
    if target_after is None:
        lists = _all_article_lists(doc)
        (lists[0] if lists else doc.body).insert(0, a)
    else:
        tl, ti = doc.parent_of(target_after)
        tl.insert(ti + 1, a)
    mapping: dict[Key, Key] = {}
    if renumber:
        # 이동 범위 안의 조문만 번호를 다시 매긴다(가지번호 유지)
        arts = doc.articles()
        keys = sorted(art_key(x) for x in arts)
        old_keys = [art_key(x) for x in arts]
        for x, k in zip(arts, keys):
            if art_key(x) != k:
                mapping[art_key(x)] = k
        for x, k in zip(arts, keys):
            x.num, x.branch = k
        update_internal_refs(doc, mapping)
    if mark_moved:
        tag = f"<{old_label}에서 이동{(' ' + date) if date else ''}>"
        a.history = (a.history + " " + tag).strip()
    return mapping


def swap_articles(doc: LawDoc, a: Unit, b: Unit) -> None:
    """맞교환: 두 조문의 위치와 번호를 서로 바꾼다."""
    la, ia = doc.parent_of(a)
    lb, ib = doc.parent_of(b)
    ka, kb = art_key(a), art_key(b)
    la[ia], lb[ib] = b, a
    a.num, a.branch = kb
    b.num, b.branch = ka
    update_internal_refs(doc, {ka: kb, kb: ka})


def swap_children(parent: Unit, x: Unit, y: Unit) -> None:
    i, j = parent.children.index(x), parent.children.index(y)
    parent.children[i], parent.children[j] = y, x
    x.num, y.num = y.num, x.num
    x.branch, y.branch = y.branch, x.branch


def batch_rename_titles(doc: LawDoc, old: str, new: str) -> int:
    """일괄변경 — 조 제목·본문의 자구를 한꺼번에 바꾼다."""
    n = 0
    for u in [x for top in doc.body for x in top.iter()]:
        if old in u.text:
            n += u.text.count(old)
            u.text = u.text.replace(old, new)
        if old in u.title:
            n += u.title.count(old)
            u.title = u.title.replace(old, new)
    for ad in doc.addenda:
        if old in ad.text:
            n += ad.text.count(old)
            ad.text = ad.text.replace(old, new)
    return n
