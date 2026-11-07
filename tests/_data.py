"""시험용 규정집 분석 결과 — 없으면 sample/ 의 공개 규정집 PDF로 만든다(처음 1회 20초 안팎)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lawedit.core.parser import PARSER_VERSION     # noqa: E402

CACHE = ROOT / "cache" / f"regbook_v{PARSER_VERSION}.json"
PDF = ROOT / "sample" / "안양도시공사 규정집(20260507).pdf"


def regbook_path() -> Path | None:
    if CACHE.exists():
        return CACHE
    if not PDF.exists():
        return None
    from lawedit.regs.regbook import build_regbook
    CACHE.parent.mkdir(exist_ok=True)
    build_regbook(PDF).save(CACHE)
    return CACHE
