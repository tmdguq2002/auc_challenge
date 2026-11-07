"""용어·띄어쓰기 사전 엔진.

규칙 문법(법령안편집기 사전과 호환):
  ■찾을말▶바꿀말[→설명]
  ~        앞말(붙어 있는 낱말)                  ■~조례▶~∨조례
  ∨, ^     띄어쓰기(앞뒤 끝에 오면 낱말 경계)
  [a|b]    대응 선택 — 바꿀말의 같은 순번 [x|y] 와 짝
  {a|b}, <a|b>  단순 선택
  [*이름*] 매크로 (Abbreviation.txt)
  #        숫자
  바꿀말의 '/' 는 여러 후보
법령안편집기가 설치돼 있으면 그 사전을 읽고, 없으면 내장 사전을 쓴다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ORIGINAL_CONF_DIRS = [
    r"C:\Program Files (x86)\LawEditor3.1\Conf",
    r"C:\Program Files\LawEditor3.1\Conf",
    "/mnt/c/Program Files (x86)/LawEditor3.1/Conf",
]

WORD = r"[가-힣A-Za-z0-9·ㆍ]"


@dataclass
class Rule:
    pattern: str
    replacement: str
    note: str = ""
    source: str = ""
    category: str = "용어"
    regex: re.Pattern | None = None
    anchor: str = ""
    groups: list = field(default_factory=list)    # 패턴 그룹 정보: ('tilde'|'alt'|'macro'|'num'|'free', alts)


@dataclass
class Hit:
    start: int
    end: int
    found: str
    suggestions: list[str]
    note: str
    category: str
    source: str


def _read(path: Path) -> str:
    b = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


def load_macros(text: str) -> dict[str, list[str]]:
    mac: dict[str, list[str]] = {}
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, l in enumerate(lines[:-1]):
        m = re.fullmatch(r"\[\*(.+?)\*\]", l)
        if m and lines[i + 1].startswith("["):
            body = lines[i + 1][1:-1] if lines[i + 1].endswith("]") else lines[i + 1][1:]
            mac[m.group(1)] = [x.replace("^", " ") for x in body.split("|")]
    return mac


_TOKEN = re.compile(r"\[\*[^\]]+?\*\]|\[[^\]]*\]|\{[^}]*\}|<[^>]*>|\([^)]*\|[^)]*\)|~|#|∨|\^|.", re.S)


def _alt_regex(alts: list[str]) -> str:
    alts = sorted(set(alts), key=len, reverse=True)
    return "(?:" + "|".join(re.escape(a).replace(r"\ ", r"[ \t]+") for a in alts) + ")"


def compile_rule(r: Rule, macros: dict[str, list[str]]) -> bool:
    pat = r.pattern
    toks = _TOKEN.findall(pat)
    parts: list[str] = []
    groups = []
    literal_runs: list[str] = []
    cur_lit = ""
    n = len(toks)
    for i, t in enumerate(toks):
        if t in ("∨", "^"):
            if i == 0:
                parts.append(r"(?<![가-힣A-Za-z0-9])")
            elif i == n - 1:
                parts.append(r"(?![가-힣A-Za-z0-9])")
            else:
                parts.append(r"[ \t]+")
            literal_runs.append(cur_lit)
            cur_lit = ""
            continue
        if t == "~":
            gi = len(groups)
            groups.append(("tilde", None))
            # 앞말은 낱말 첫머리부터, 두 글자 이상 ('다시'의 '다'는 앞말이 아니다)
            parts.append(("(?<![가-힣A-Za-z0-9])" if not parts else "") + f"(?P<g{gi}>{WORD}{{2,}})")
            literal_runs.append(cur_lit)
            cur_lit = ""
            continue
        if t == "#":
            gi = len(groups)
            groups.append(("num", None))
            parts.append(rf"(?P<g{gi}>\d[\d,]*)")
            literal_runs.append(cur_lit)
            cur_lit = ""
            continue
        if t.startswith("[*") and t.endswith("*]"):
            name = t[2:-2]
            alts = macros.get(name)
            if not alts:
                return False
            gi = len(groups)
            groups.append(("macro", alts))
            parts.append(f"(?P<g{gi}>{_alt_regex(alts)})")
            literal_runs.append(cur_lit)
            cur_lit = ""
            continue
        if len(t) > 1 and t[0] in "[{<(" and "|" in t or (len(t) > 1 and t[0] == "[" and t[-1] == "]"):
            alts = [a.replace("∨", " ").replace("^", " ") for a in t[1:-1].split("|")]
            gi = len(groups)
            groups.append(("alt" if t[0] == "[" else "free", alts))
            parts.append(f"(?P<g{gi}>{_alt_regex(alts)})")
            literal_runs.append(cur_lit)
            cur_lit = ""
            continue
        if t == " ":
            parts.append(r"[ \t]+")
            literal_runs.append(cur_lit)
            cur_lit = ""
            continue
        parts.append(re.escape(t))
        cur_lit += t
    literal_runs.append(cur_lit)
    # 한글로 시작하는 규칙은 낱말 첫머리에서만 (복합어 내부 오검출 방지)
    if toks and re.match(r"[가-힣]", toks[0]):
        parts.insert(0, r"(?<![가-힣])")
    try:
        r.regex = re.compile("".join(parts))
    except re.error:
        return False
    r.groups = groups
    r.anchor = max(literal_runs, key=len) if literal_runs else ""
    return bool(r.anchor) or bool(groups)


def _bare(s: str) -> str:
    return re.sub(r"[\s.,·ㆍ:;]", "", s)


DEFAULT_CATEGORIES = {"용어", "띄어쓰기", "맞춤법", "사용자"}


def _render_repl(repl: str, m: re.Match, groups) -> str:
    toks = _TOKEN.findall(repl)
    out = []
    gi_by_kind: dict[str, list[int]] = {"tilde": [], "alt": [], "macro": [], "num": [], "free": []}
    for i, (k, _) in enumerate(groups):
        gi_by_kind[k].append(i)
    used = {k: 0 for k in gi_by_kind}

    def take(kind):
        lst = gi_by_kind[kind]
        if used[kind] < len(lst):
            used[kind] += 1
            return lst[used[kind] - 1]
        return None
    for t in toks:
        if t in ("∨", "^"):
            out.append(" ")
        elif t == "~":
            g = take("tilde")
            out.append(m.group(f"g{g}") if g is not None else "")
        elif t == "#":
            g = take("num")
            out.append(m.group(f"g{g}") if g is not None else "#")
        elif t.startswith("[*") and t.endswith("*]"):
            g = take("macro")
            out.append(m.group(f"g{g}") if g is not None else "")
        elif len(t) > 1 and t[0] in "[(" and t[-1] in "])" and "|" in t:
            alts = t[1:-1].split("|")
            # 선택지 개수가 같은 패턴 그룹과 짝짓는다(없으면 순서대로)
            g = None
            for gi in gi_by_kind["alt"][used["alt"]:]:
                if len(groups[gi][1]) == len(alts):
                    g = gi
                    break
            if g is not None:
                used["alt"] = gi_by_kind["alt"].index(g) + 1
            else:
                g = take("alt")
            if g is not None:
                src_alts = groups[g][1]
                got = m.group(f"g{g}")
                norm = [a.replace(" ", "") for a in src_alts]
                idx = norm.index(re.sub(r"\s+", "", got)) if re.sub(r"\s+", "", got) in norm else 0
                out.append(alts[idx] if idx < len(alts) else alts[0])
            else:
                out.append(alts[0])
        elif len(t) > 1 and t[0] in "{<" and t[-1] in "}>":
            out.append(t[1:-1].split("|")[0])
        else:
            out.append(t)
    res = "".join(out).replace("^", " ").replace("∨", " ")
    res = re.sub(r"(?<=[가-힣])v(?=[가-힣])", " ", res)     # 원본 사전의 'v' 띄어쓰기 표기
    return re.sub(r" {2,}", " ", res).strip()


def parse_rules(text: str, source: str, category: str) -> list[Rule]:
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("■") or "▶" not in line:
            continue
        pat, rep = line[1:].split("▶", 1)
        note = ""
        if "→" in rep:
            rep, note = rep.split("→", 1)
        if "※" in rep:
            rep, n2 = rep.split("※", 1)
            note = (note + " " + n2).strip()
        pats = pat.split("/") if "/" in pat and pat.count("/") == rep.count("/") else [pat]
        reps = rep.split("/") if len(pats) > 1 else [rep]
        for p, r in zip(pats, reps if len(reps) == len(pats) else reps * len(pats)):
            if p.strip():
                rules.append(Rule(p.strip(), r.strip(), note.strip(), source, category))
    return rules


def parse_ezlaw(text: str, source: str) -> list[Rule]:
    """'어려운말<TAB>한자<TAB>쉬운말' 목록."""
    rules = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        term, hanja, sug = parts[0].strip(), parts[1].strip(), parts[-1].strip().strip('"')
        core = re.sub(r"\([^)]*\)|[~*]", "", term).strip()
        if len(core) < 2 or core == sug or not re.search(r"[가-힣]", core):
            continue
        # 메타 항목(*), 한자 병기만 하는 항목은 제외
        if "*" in sug or sug.startswith(core + "(") or sug.replace(" ", "") == core.replace(" ", ""):
            continue
        rules.append(Rule(core, sug, f"알기 쉬운 법령 용어{(' (' + hanja + ')') if hanja else ''}", source, "알기쉬운용어"))
    return rules


class Dictionary:
    def __init__(self):
        self.rules: list[Rule] = []
        self.sources: list[str] = []
        self.ignored: set[str] = set(read_ignored())

    def add_rules(self, rules: list[Rule], macros: dict[str, list[str]] | None = None):
        for r in rules:
            if r.regex is None:
                if r.category == "알기쉬운용어":
                    # 낱말 앞 경계 필수 (안양도시공사의 '도시' 같은 오검출 방지)
                    r.regex = re.compile(r"(?<![가-힣A-Za-z0-9])" + re.escape(r.pattern).replace(r"\ ", r"[ \t]+"))
                    r.anchor = r.pattern.split()[0] if r.pattern.split() else r.pattern
                elif not compile_rule(r, macros or {}):
                    continue
            self.rules.append(r)

    def check(self, text: str, categories: set[str] | None = None) -> list[Hit]:
        hits: list[Hit] = []
        for r in self.rules:
            if categories and r.category not in categories:
                continue
            if r.anchor and r.anchor not in text:
                continue
            for m in r.regex.finditer(text):
                found = m.group(0)
                if found.strip() in self.ignored:
                    continue
                if r.category == "알기쉬운용어":
                    sugs = [r.replacement]
                else:
                    sugs = [s for s in (_render_repl(x, m, r.groups) for x in r.replacement.split("/")) if s]
                note = r.note
                # 설명문이 바꿀말 자리에 들어간 경우 → 비고로
                keep = []
                for sg in sugs:
                    if len(sg) > 12 and sg.endswith(("다.", "다")) and " " in sg or sg.startswith("["):
                        note = (note + " " + sg).strip()
                    else:
                        keep.append(sg)
                sugs = keep
                if r.category == "띄어쓰기":
                    same = [sg for sg in sugs if re.sub(r"\s+", " ", sg) == re.sub(r"\s+", " ", found).strip()]
                else:
                    same = [sg for sg in sugs if _bare(sg) == _bare(found)]
                if same and r.category != "띄어쓰기":
                    continue        # 원문 그대로가 후보에 있으면(동음이의어 안내 등) 지적하지 않음
                sugs = [sg for sg in sugs if sg not in same]
                if not sugs and not (note and r.category == "알기쉬운용어"):
                    continue
                hits.append(Hit(m.start(), m.end(), found, sugs, note, r.category, r.source))
        # 같은 위치는 하나로 합치고 제안을 모은다
        hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
        merged: dict[tuple[int, int], Hit] = {}
        for h in hits:
            k = (h.start, h.end)
            if k in merged:
                m = merged[k]
                for sgg in h.suggestions:
                    if sgg not in m.suggestions:
                        m.suggestions.append(sgg)
                if h.note and h.note not in m.note:
                    m.note = (m.note + " / " + h.note).strip(" /")
            else:
                merged[k] = Hit(h.start, h.end, h.found, list(h.suggestions), h.note, h.category, h.source)
        return list(merged.values())


def builtin_rules() -> list[Rule]:
    from .builtin_terms import TERM_RULES, SPACING_RULES
    return parse_rules(TERM_RULES, "내장", "용어") + parse_rules(SPACING_RULES, "내장", "띄어쓰기")


def user_dict_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "LawEdit"
    base.mkdir(parents=True, exist_ok=True)
    return base / "user_terms.txt"


def load_default(conf_dir: str | None = None) -> Dictionary:
    d = Dictionary()
    found = None
    for c in ([conf_dir] if conf_dir else []) + ORIGINAL_CONF_DIRS:
        if c and Path(c, "용어정비.txt").exists():
            found = Path(c)
            break
    macros = {}
    if found:
        if (found / "Abbreviation.txt").exists():
            macros = load_macros(_read(found / "Abbreviation.txt"))
        for fn, cat in [("용어정비.txt", "용어"), ("용어정비2.txt", "용어"), ("띄어쓰기.txt", "띄어쓰기"),
                        ("틀리기 쉬운 단어 및 한자.txt", "맞춤법")]:
            p = found / fn
            if p.exists():
                d.add_rules(parse_rules(_read(p), f"법령안편집기:{fn}", cat), macros)
        if (found / "EzLaw.txt").exists():
            d.add_rules(parse_ezlaw(_read(found / "EzLaw.txt"), "법령안편집기:EzLaw.txt"))
        d.sources.append(str(found))
    d.add_rules(builtin_rules(), macros)
    d.sources.append("내장 사전")
    up = user_dict_path()
    if up.exists():
        d.add_rules(parse_rules(_read(up), "사용자", "사용자"), macros)
        d.sources.append(str(up))
    return d


def add_user_term(find: str, replace: str, note: str = "") -> None:
    p = user_dict_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(f"■{find}▶{replace}" + (f"→{note}" if note else "") + "\n")


def read_user_terms() -> list[tuple[str, str, str]]:
    p = user_dict_path()
    if not p.exists():
        return []
    out = []
    for r in parse_rules(_read(p), "사용자", "사용자"):
        out.append((r.pattern, r.replacement, r.note))
    return out


def write_user_terms(rows: list[tuple[str, str, str]]) -> None:
    p = user_dict_path()
    p.write_text("".join(f"■{a}▶{b}" + (f"→{c}" if c else "") + "\n" for a, b, c in rows if a), encoding="utf-8")


def ignore_path() -> Path:
    return user_dict_path().with_name("ignored_terms.txt")


def read_ignored() -> list[str]:
    p = ignore_path()
    return [l.strip() for l in _read(p).splitlines() if l.strip()] if p.exists() else []


def add_ignored(word: str) -> None:
    with ignore_path().open("a", encoding="utf-8") as f:
        f.write(word.strip() + "\n")
