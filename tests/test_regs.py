"""규정집 분석 테스트 — sample/ 의 공개 규정집으로."""
import pytest

from _data import regbook_path


@pytest.fixture(scope="module")
def env():
    from lawedit.regs.regbook import RegBook
    from lawedit.regs.analysis import RegGraph, Corpus
    path = regbook_path()
    if path is None:
        pytest.skip("sample/ 에 규정집 PDF 없음")
    rb = RegBook.load(path)
    return rb, RegGraph(rb), Corpus(rb)


def test_hierarchy(env):
    rb, g, c = env
    assert len(rb.entries) == 73
    assert g.parent("020201") == "0202"
    assert g.ancestors("0202") == ["0101", "01"]


def test_impact_finds_upper_and_lower(env):
    from lawedit.regs.analysis import analyze_impact
    rb, g, c = env
    imp = analyze_impact(rb, g, c, "0101", [(10, 0)])
    got = {(i.code, i.label) for i in imp}
    assert ("0201", "제6조") in got          # 직제규정 이사와 감사
    assert any(i.code == "01" and i.direction == "상위" for i in imp)


def test_injected_numeric_conflict(env):
    from lawedit.regs.regbook import RegBook
    from lawedit.regs.analysis import RegGraph, Corpus, find_conflicts
    rb, _, _ = env
    rb2 = RegBook.from_json(rb.to_json())
    a = rb2.by_code("0201").doc.find_article(6)
    a.children[0].text = a.children[0].text.replace("10명 이내의 이사", "12명 이내의 이사")
    cf = find_conflicts(rb2, RegGraph(rb2), Corpus(rb2), ["0201", "0101", "01"])
    assert any(x.kind == "수치 불일치" and {x.a_code, x.b_code} == {"0101", "0201"} for x in cf)
