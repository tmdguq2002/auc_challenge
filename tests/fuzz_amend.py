"""실제 규정집으로 개정문 왕복 검증: 무작위 수정 → 개정문 → 현행에 적용 → 수정본과 같은가."""
import random
import sys

from lawedit.regs.regbook import RegBook
from lawedit.core.amend import build_amendment_lines, apply_amendment
from lawedit.core.render import render_body, render_doc
from lawedit.core.parser import parse_text
from lawedit.core.model import Unit
from lawedit.core import numbering


BASE_OPS = ["word", "word", "title", "add_item", "add_para", "del", "new_art"]
OPS = BASE_OPS + ["swap", "swap_para", "renumber", "remove"]


def mutate(doc, rng):
    arts = [a for a in doc.articles() if not a.deleted]
    if not arts:
        return []
    done = []
    for _ in range(rng.randint(1, 4)):
        a = rng.choice(arts)
        if a.deleted:
            continue
        units = [u for u in a.iter() if u.text and not u.deleted]
        op = rng.choice(OPS)
        if op == "word" and units:
            u = rng.choice(units)
            ws = u.text.split(" ")
            k = rng.randrange(len(ws))
            ws[k] = ws[k] + "등" if rng.random() < .5 else "변경" + ws[k]
            u.text = " ".join(ws)
            done.append(f"word {u.kind}")
        elif op == "title" and a.title:
            a.title = a.title + " 등"
            done.append("title")
        elif op == "add_item":
            owner = rng.choice([u for u in a.iter() if u.kind in ("article", "paragraph")])
            items = [c for c in owner.children if c.kind == "item"]
            if items:
                owner.children.append(Unit(kind="item", num=items[-1].num + 1, text="새로 추가한 호"))
                done.append("add_item")
        elif op == "add_para":
            paras = [c for c in a.children if c.kind == "paragraph"]
            if paras:
                a.children.append(Unit(kind="paragraph", num=paras[-1].num + 1, text="새로 추가한 항이다."))
                done.append("add_para")
        elif op == "del":
            paras = [c for c in a.children if c.kind == "paragraph" and not c.deleted]
            if len(paras) > 1:
                numbering.delete_child(doc, a, rng.choice(paras), "mark")
                done.append("del_para")
            else:
                numbering.delete_article(doc, a, "mark")
                done.append("del_art")
        elif op == "swap":
            k = arts.index(a)
            b = arts[k + 1] if k + 1 < len(arts) else None
            if b is not None and doc.parent_of(a)[0] is doc.parent_of(b)[0]:
                numbering.swap_articles(doc, a, b)
                done.append("swap")
        elif op == "swap_para":
            paras = [c for c in a.children if c.kind == "paragraph" and not c.deleted]
            if len(paras) > 1:
                numbering.swap_children(a, paras[0], paras[1])
                done.append("swap_para")
        elif op == "renumber":
            if any(x.deleted for x in doc.articles()):
                continue     # '제n조 삭제' 자리를 없애는 일부개정 문형은 없다(앱에서 안내)
            numbering.insert_article(doc, a, title="신설", text="신설한 조문이다.")
            numbering.renumber_sequential(doc)
            done.append("renumber")
            return done          # 번호가 모두 바뀌었으니 이번 회차는 여기까지
        elif op == "remove":
            trial = doc.clone()
            numbering.delete_article(trial, trial.find_uid(a.uid), "remove")
            if {x.uid: x.number_label() for x in trial.articles()} == \
                    {x.uid: x.number_label() for x in doc.articles() if x.uid != a.uid}:
                continue     # 번호를 당겨 받는 조가 없으면 일부개정에서는 '삭제' 자리가 남는다(= del)
            numbering.delete_article(doc, a, "remove")
            done.append("remove")
            return done
        elif op == "new_art":
            numbering.insert_article(doc, a, title="신설", text="신설한 조문이다.")
            done.append("new_art")
            arts = [x for x in doc.articles() if not x.deleted]
    return done


def main(seed=1, rounds=3, reparse=False):
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _data import regbook_path
    rb = RegBook.load(regbook_path())
    rng = random.Random(seed)
    ok = fail = 0
    fails = []
    for e in rb.entries:
        for r in range(rounds):
            cur = e.doc
            new = cur.clone()
            ops = mutate(new, rng)
            if reparse:          # 편집기에서 고친 것처럼 글 → 다시 분석
                new = parse_text(render_doc(new))
            lines = build_amendment_lines(cur, new)
            applied, log = apply_amendment(cur, "\n".join(lines))
            got, want = render_body(applied, False), render_body(new, False)
            if got == want:
                ok += 1
            else:
                fail += 1
                import difflib
                diff = [l for l in difflib.unified_diff(want.split("\n"), got.split("\n"), "기대", "적용", n=0, lineterm="")][2:8]
                fails.append((e.code, ops, lines, log + ["DIFF"] + diff))
    print(f"ok={ok} fail={fail}")
    for code, ops, lines, log in fails[:6]:
        print("====", code, ops)
        print("\n".join(lines[:12]))
        print("LOG:", [l for l in log if not l.startswith("[적용]")][:12])
    return fail


if __name__ == "__main__":
    if "--base" in sys.argv:
        OPS[:] = BASE_OPS
    sys.exit(1 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 1, reparse="--reparse" in sys.argv) else 0)
