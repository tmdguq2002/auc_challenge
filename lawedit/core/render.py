"""LawDoc → 텍스트."""
from __future__ import annotations

from .model import LawDoc, Unit, DIVISION_LABEL

INDENT = {"paragraph": " ", "item": "  ", "subitem": "    "}


def _tagged(text: str, hist: str, with_history: bool) -> str:
    if with_history and hist:
        return (text + " " + hist).strip()
    return text


def render_unit(u: Unit, with_history: bool = True) -> list[str]:
    out: list[str] = []
    if u.kind in DIVISION_LABEL:
        out.append(u.heading())
        for c in u.children:
            out.extend(render_unit(c, with_history))
        return out
    if u.kind == "article":
        head = u.heading()
        if u.deleted:
            out.append(f"{u.number_label()} 삭제" + (f" {u.history}" if with_history and u.history else ""))
            return out
        kids = list(u.children)
        if not u.text and kids and kids[0].kind == "paragraph":
            first = kids.pop(0)
            line = f"{head} {first.number_label()} " + _tagged(first.text, first.history, with_history) if not first.deleted \
                else f"{head} {first.number_label()} 삭제 {first.history if with_history else ''}".rstrip()
            out.append(_tagged(line, u.history, with_history))
            for c in first.children:
                out.extend(render_unit(c, with_history))
        else:
            out.append(_tagged(f"{head} {u.text}".rstrip(), u.history, with_history))
        for c in kids:
            out.extend(render_unit(c, with_history))
        return out
    pad = INDENT.get(u.kind, "")
    if u.deleted:
        out.append(f"{pad}{u.number_label()} 삭제" + (f" {u.history}" if with_history and u.history else ""))
    else:
        out.append(f"{pad}{u.number_label()} " + _tagged(u.text, u.history, with_history))
    for c in u.children:
        out.extend(render_unit(c, with_history))
    return out


def render_body(doc: LawDoc, with_history: bool = True) -> str:
    lines: list[str] = []
    for u in doc.body:
        lines.extend(render_unit(u, with_history))
    return "\n".join(lines)


def render_doc(doc: LawDoc, with_history: bool = True, with_header: bool = True) -> str:
    lines: list[str] = []
    if with_header:
        if doc.name:
            lines.append(doc.name)
        lines.extend(doc.history)
        if lines:
            lines.append("")
    lines.append(render_body(doc, with_history))
    for ad in doc.addenda:
        lines.append("")
        lines.append(ad.header)
        if ad.text:
            lines.append(ad.text)
        for u in ad.units:
            lines.extend(render_unit(u, with_history))
    for ap in doc.appendices:
        lines.append("")
        lines.append(f"{ap.label()}" + (f" <{ap.ref}>" if ap.ref else "") + (f" {ap.title}" if ap.title else "")
                     + (f" {ap.history}" if ap.history else ""))
        if ap.text:
            lines.append(ap.text)
    return "\n".join(lines).strip() + "\n"
