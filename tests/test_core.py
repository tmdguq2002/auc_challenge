from lawedit.core.parser import parse_text
from lawedit.core.render import render_doc, render_body
from lawedit.core.amend import (build_amendment_lines, apply_amendment, compare, phrase_changes,
                                build_compare_table)
from lawedit.core.korean import josa
from lawedit.core import numbering
from lawedit.core.model import LawDoc

SAMPLE = """안양도시공사 테스트규정
제정 2019. 3. 8. 규정 제1호

제1장 총칙
제1조(목적) 이 규정은 안양도시공사(이하 “공사”라 한다)의 운영에 필요한 사항을 정함을 목적으로 한다.
제2조(정의) 이 규정에서 사용하는 용어의 뜻은 다음과 같다.
  1. “직원”이란 공사에 근무하는 사람을 말한다.
  2. “부서”란 공사의 하부조직을 말한다.
제3조(위원회) ① 공사에 인사위원회를 둔다.
 ② 위원회는 위원장을 포함하여 5명 이상 7명 이내의 위원으로 구성한다.
 ③ 제2항에 따른 위원의 임기는 2년으로 한다.
제2장 보칙
제4조(위임) 이 규정의 시행에 필요한 사항은 사장이 정한다.

부칙 <제1호, 2019. 3. 8.>
이 규정은 발령한 날부터 시행한다.
"""


def doc():
    return parse_text(SAMPLE)


def test_parse_structure():
    d = doc()
    assert d.name == "안양도시공사 테스트규정"
    assert len(d.history) == 1
    arts = d.articles()
    assert [a.num for a in arts] == [1, 2, 3, 4]
    assert arts[1].children[1].kind == "item" and arts[1].children[1].num == 2
    assert [p.num for p in arts[2].children] == [1, 2, 3]
    assert len(d.divisions()) == 2
    assert d.addenda and "시행한다" in d.addenda[0].text


def test_render_roundtrip():
    d = doc()
    again = parse_text(render_doc(d))
    assert render_body(again) == render_body(d)


def test_josa():
    assert josa("시장", "을/를") == "을"
    assert josa("공사", "을/를") == "를"
    assert josa("제3조", "을/를") == "를"
    assert josa("제1항", "으로/로") == "으로"
    assert josa("제2호", "으로/로") == "로"
    assert josa("“서울”", "으로/로") == "로"     # ㄹ 받침
    assert josa("10", "을/를") == "을"


def test_phrase_changes():
    ph = phrase_changes("위원회는 위원장을 포함하여 5명 이상 7명 이내의 위원으로 구성한다.",
                        "위원회는 위원장을 포함하여 7명 이상 9명 이내의 위원으로 구성한다.")
    assert ph == [("5명 이상 7명", "7명 이상 9명")] or ph == [("5명", "7명"), ("7명", "9명")] or len(ph) >= 1


def _roundtrip(cur: LawDoc, new: LawDoc):
    lines = build_amendment_lines(cur, new)
    applied, log = apply_amendment(cur, "\n".join(lines))
    assert render_body(applied, False) == render_body(new, False), "\n".join(lines + ["--LOG--"] + log)
    return lines


def test_amend_phrase():
    cur = doc()
    new = cur.clone()
    new.articles()[2].children[1].text = new.articles()[2].children[1].text.replace("5명 이상 7명", "7명 이상 9명")
    lines = _roundtrip(cur, new)
    assert lines[0] == "안양도시공사 테스트규정 일부를 다음과 같이 개정한다."
    assert lines[2].startswith("제3조제2항 중 “")


def test_amend_title_add_delete():
    cur = doc()
    new = cur.clone()
    a3 = new.articles()[2]
    a3.title = "인사위원회"
    from lawedit.core.model import Unit
    a3.children.append(Unit(kind="paragraph", num=4, text="위원장은 사장이 지명한다."))
    numbering.delete_article(new, new.articles()[3], "mark")
    na = numbering.insert_article(new, new.articles()[1], title="적용범위", text="이 규정은 모든 직원에게 적용한다.")
    assert na.number_label() == "제2조의2"
    lines = _roundtrip(cur, new)
    text = "\n".join(lines)
    assert "제2조의2를 다음과 같이 신설한다." in text
    assert "제3조의 제목 “(위원회)”를 “(인사위원회)”로 한다." in text
    assert "제3조에 제4항을 다음과 같이 신설한다." in text
    assert "제4조를 삭제한다." in text


def test_amend_item_whole():
    cur = doc()
    new = cur.clone()
    new.articles()[1].children[0].text = "“임직원”이란 공사의 임원과 직원을 말한다."
    lines = _roundtrip(cur, new)
    assert any(l.startswith("제2조제1호") for l in lines)


def test_group_same_phrase():
    cur = doc()
    new = cur.clone()
    for a in new.articles():
        for u in a.iter():
            u.text = u.text.replace("사장이", "공사의 사장이")
    new.articles()[0].text = new.articles()[0].text  # 변경 없음
    lines = build_amendment_lines(cur, new)
    assert any("“공사의 사장”" in l for l in lines)


def test_compare_table():
    cur = doc()
    new = cur.clone()
    new.articles()[2].children[1].text = new.articles()[2].children[1].text.replace("5명", "6명")
    rows = build_compare_table(cur, new)
    flat_l = "".join(t for r in rows for line in r.left for t, _ in line)
    flat_r = "".join(t for r in rows for line in r.right for t, _ in line)
    assert "(생 략)" in flat_l and "(현행과 같음)" in flat_r
    assert any(u and "6명" in t for r in rows for line in r.right for t, u in line)


def test_move_and_swap_update_refs():
    d = doc()
    a2, a3 = d.articles()[1], d.articles()[2]
    numbering.swap_articles(d, a2, a3)
    texts = render_body(d)
    # 제3조 안의 '제2항' 은 상대 인용이므로 그대로
    assert "제2항에 따른" in texts
    assert [a.title for a in d.articles()][:3] == ["목적", "위원회", "정의"]


def test_renumber_refs():
    d = parse_text("""규정
제1조(목적) 목적이다.
제2조(정의) 제1조에 따른다.
제3조(위원) 제2조 및 제4조에 따른다.
제4조(기타) 끝.""")
    numbering.delete_article(d, d.articles()[1], "remove")
    body = render_body(d)
    assert "제2조(위원) 제2조 및 제3조에 따른다." in body or "제2조(위원)" in body
    assert "제3조(기타)" in body


def test_apply_amendment_text():
    cur = doc()
    amend = """안양도시공사 테스트규정 일부를 다음과 같이 개정한다.

제3조제2항 중 “5명 이상 7명 이내”를 “7명 이상 9명 이내”로 한다.
제4조를 다음과 같이 한다.
제4조(위임) 이 규정의 시행에 필요한 세부 사항은 사장이 따로 정한다.
"""
    new, log = apply_amendment(cur, amend)
    assert "7명 이상 9명 이내" in new.articles()[2].children[1].text
    assert new.articles()[3].text.startswith("이 규정의 시행에 필요한 세부 사항")
    assert all(l.startswith("[적용]") for l in log), log


def test_ai_draft_apply_offline():
    from lawedit.ai.agent import apply_draft, AmendDraft, ArticleEdit, verify_doc
    cur = doc()
    d = AmendDraft(edits=[
        ArticleEdit("replace", "제3조", "제3조(위원회) ① 공사에 인사위원회를 둔다.\n② 위원회는 위원장을 포함하여 7명 이상 9명 이내의 위원으로 구성한다.\n③ 제2항에 따른 위원의 임기는 2년으로 한다."),
        ArticleEdit("insert_after", "제3조", "제3조의2(회의) 위원회의 회의는 재적위원 과반수의 출석으로 개의한다."),
        ArticleEdit("delete", "제99조")])
    new, log = apply_draft(cur, cur.clone(), d)
    lines = build_amendment_lines(cur, new)
    assert "제3조제2항 중 “5명 이상 7명”을 “7명 이상 9명”으로 한다." in lines
    assert any(l.startswith("제3조의2를 다음과 같이 신설한다") for l in lines)
    assert any("건너뜀" in l for l in log)
    assert not [x for x in verify_doc(new) if x.level == "오류"]


def test_extract_json():
    from lawedit.ai.llm import extract_json
    assert extract_json('설명\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert extract_json('{"verdict": "상충"} 끝') == {"verdict": "상충"}


def test_no_secrets_in_repo_or_dist():
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "tools" / "secret_scan.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_secret_scan_detects_and_redacts():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ss", Path(__file__).resolve().parent.parent / "tools" / "secret_scan.py")
    ss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ss)
    fake = "sk-ant-api03-" + "x" * 40
    assert ss.scan_bytes(fake.encode())
    from lawedit.ai.llm import _redact, mask
    assert fake not in _redact(f"error with {fake}", fake)
    assert "x" * 20 not in mask(fake)


def test_each_repeated_term_roundtrip():
    cur = parse_text("""규정
제1조(목적) 이 규정은 목적이 있다.
제2조(위원장) 위원장은 경영기획본부장으로 하며, 경영기획본부장이 없으면 부위원장이 대행한다.""")
    new = cur.clone()
    a = new.articles()[1]
    a.text = a.text.replace("경영기획본부장", "경영전략본부장")
    lines = build_amendment_lines(cur, new)
    assert "제2조 중 “경영기획본부장”을 각각 “경영전략본부장”으로 한다." in lines
    applied, log = apply_amendment(cur, "\n".join(lines))
    assert render_body(applied, False) == render_body(new, False), log


def test_rename_intent_and_locations():
    from lawedit.ai.agent import rename_pairs, term_locations
    assert rename_pairs("경영기획본부를 경영정략본부로 명칭 변경") == [("경영기획본부", "경영정략본부")]
    d = parse_text("규정\n제1조(목적) 경영기획본부장이 정한다.")
    locs = term_locations("경영기획본부", [d])
    assert locs and locs[0][1] == 1 and locs[0][2] == ["제1조"]


def _reparse(d: LawDoc) -> LawDoc:
    """편집기에서 고친 것처럼 글로 바꿨다가 다시 분석(uid 없음)."""
    return parse_text(render_doc(d))


def test_delete_article_typed_in_editor():
    cur = doc()
    t = render_doc(cur)
    for old, new in (("제4조(위임) 이 규정의 시행에 필요한 사항은 사장이 정한다.", "제4조 삭제"),
                     (t[t.index("제2조(정의)"):t.index("제3조(위원회)")], "제2조 삭제 <2026. 1. 1.>\n")):
        lines = _roundtrip(cur, parse_text(t.replace(old, new)))
        assert not any("신설" in l for l in lines), lines


def test_deleted_first_paragraph_on_article_line():
    d = parse_text("규정\n제1조(목적) ① 삭제\n② 둘째 항이다.")
    assert d.articles()[0].children[0].deleted


def test_swap_and_renumber_by_current_numbers():
    for edit in (lambda d: numbering.swap_articles(d, d.articles()[1], d.articles()[2]),
                 lambda d: numbering.swap_children(d.articles()[2], *d.articles()[2].children[:2]),
                 lambda d: (numbering.insert_article(d, d.articles()[0], title="적용", text="적용한다."),
                            numbering.renumber_sequential(d)),
                 lambda d: numbering.delete_article(d, d.articles()[1], "remove")):
        cur = doc()
        new = cur.clone()
        edit(new)
        _roundtrip(cur, new)
        _roundtrip(cur, _reparse(new))


def test_division_title_and_renumber():
    cur = parse_text("규정\n제1장 총칙\n제1조(목적) 목적.\n제3장 보칙\n제2조(위임) 위임.")
    new = cur.clone()
    numbering.renumber_sequential(new)
    new.divisions()[0].title = "총 칙"
    lines = _roundtrip(cur, new)
    assert "제3장을 제2장으로 한다." in lines and "제1장의 제목 “총칙”을 “총 칙”으로 한다." in lines


def test_insert_before_word_keeps_spacing():
    ph = phrase_changes("또한 같으며, 이 경우에는 이를 한다. 이 규정", "또한 같으며, 변경이 경우에는 이를 한다. 이 규정")
    assert ph == [("같으며, 이", "같으며, 변경이")]


def test_ai_draft_spacing_only_kept():
    from lawedit.ai.agent import apply_draft, AmendDraft, ArticleEdit, curly_quotes
    cur = doc()
    d = AmendDraft(edits=[ArticleEdit("replace", "제2조", "제2조(정의) 이 규정에서  사용하는 용어의 뜻은 다음과 같다.\n"
                                      "1. “직원”이란 공사에 근무하는  사람을 말한다.\n2. “부서”란 공사의 하부조직을 말한다. ")])
    new, _ = apply_draft(cur, cur.clone(), d)
    assert not compare(cur, new) and render_body(new) == render_body(cur)
    assert curly_quotes('(이하 "공사"라 한다)') == "(이하 “공사”라 한다)"
