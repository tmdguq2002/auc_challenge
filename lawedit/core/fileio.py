"""파일 입출력.

읽기: .txt .hwp(HWP 5) .hwpx .pdf .html .lawj(프로젝트)
쓰기: .lawj .txt .html .hwpx (+ 한글이 설치된 PC 에서는 .hwp/.pdf 변환)
"""
from __future__ import annotations

import datetime as dt
import html
import io
import json
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from .model import LawDoc

PROJECT_FORMAT = "lawedit-project"


# ================================================================ 프로젝트(.lawj)
@dataclass
class Project:
    current: LawDoc | None = None          # 현행
    revised: LawDoc | None = None          # 개정안(또는 제정안)
    addenda_text: str = ""                 # 이번 개정 부칙
    reason: str = ""                       # 개정이유
    points: list[str] = field(default_factory=list)
    notice: dict = field(default_factory=dict)
    path: str = ""

    def to_json(self) -> dict:
        return {"format": PROJECT_FORMAT, "version": 1, "saved": dt.datetime.now().isoformat(timespec="seconds"),
                "current": self.current.to_dict() if self.current else None,
                "revised": self.revised.to_dict() if self.revised else None,
                "addenda_text": self.addenda_text, "reason": self.reason, "points": self.points, "notice": self.notice}

    @staticmethod
    def from_json(d: dict) -> "Project":
        if d.get("format") != PROJECT_FORMAT:
            raise ValueError("법령안편집기(LawEdit) 프로젝트 파일이 아닙니다.")
        return Project(current=LawDoc.from_dict(d["current"]) if d.get("current") else None,
                       revised=LawDoc.from_dict(d["revised"]) if d.get("revised") else None,
                       addenda_text=d.get("addenda_text", ""), reason=d.get("reason", ""),
                       points=list(d.get("points", [])), notice=dict(d.get("notice", {})))

    def save(self, path: str | Path):
        p = Path(path)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
        self.path = str(p)

    @staticmethod
    def load(path: str | Path) -> "Project":
        pr = Project.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
        pr.path = str(path)
        return pr


# ================================================================ 읽기
def read_text_file(path: str | Path) -> str:
    b = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def read_hwpx(path: str | Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = sorted([n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)],
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
        out = []
        for n in names:
            x = z.read(n).decode("utf-8")
            # 문단 단위로 텍스트 모으기
            for para in re.findall(r"<hp:p\b[^>]*>(.*?)</hp:p>", x, re.S):
                # 표 안 문단은 표 안에서 다시 잡히므로 바깥 문단의 직접 텍스트만
                inner = re.sub(r"<hp:tbl\b.*?</hp:tbl>", "", para, flags=re.S)
                ts = re.findall(r"<hp:t(?:\s[^>]*)?>(.*?)</hp:t>", inner, re.S)
                txt = "".join(re.sub(r"<[^>]+>", "", t) for t in ts)
                out.append(html.unescape(txt))
        return "\n".join(out)


# ---- HWP 5.0 (OLE 복합 문서) 본문 추출 ----
HWPTAG_PARA_TEXT = 67
_EXT_CTRL = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}     # 8 WCHAR 확장 컨트롤
_INLINE_CTRL = {4, 5, 6, 7, 8, 9, 19, 20}                          # 8 WCHAR 인라인 컨트롤


def _hwp_para_text(data: bytes) -> str:
    out = []
    i = 0
    n = len(data) // 2
    chars = struct.unpack(f"<{n}H", data[:n * 2])
    while i < n:
        c = chars[i]
        if c in _EXT_CTRL or c in _INLINE_CTRL:
            if c == 9:
                out.append("\t")
            i += 8
            continue
        if c in (10,):
            out.append("\n")
        elif c == 13:
            pass
        elif c < 32:
            pass
        else:
            out.append(chr(c))
        i += 1
    return "".join(out)


def read_hwp(path: str | Path) -> str:
    import olefile
    with olefile.OleFileIO(str(path)) as ole:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack("<I", header[36:40])[0]
        compressed = bool(flags & 1)
        if flags & 2:
            raise ValueError("암호가 걸린 HWP 문서는 읽을 수 없습니다.")
        sections = sorted([e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")],
                          key=lambda e: int(e[1][7:]))
        if not sections and any(e[0] == "ViewText" for e in ole.listdir()):
            raise ValueError("배포용 HWP 문서는 읽을 수 없습니다. 한글에서 HWPX로 저장한 뒤 불러오세요.")
        paras = []
        for sec in sections:
            raw = ole.openstream(sec).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            pos = 0
            L = len(raw)
            while pos + 4 <= L:
                hdr = struct.unpack("<I", raw[pos:pos + 4])[0]
                tag = hdr & 0x3FF
                size = (hdr >> 20) & 0xFFF
                pos += 4
                if size == 0xFFF:
                    size = struct.unpack("<I", raw[pos:pos + 4])[0]
                    pos += 4
                if tag == HWPTAG_PARA_TEXT:
                    paras.append(_hwp_para_text(raw[pos:pos + size]))
                pos += size
        return "\n".join(paras)


def read_pdf(path: str | Path) -> str:
    from ..regs.regbook import load_pdf_text, _parse_header, RegBook
    pages = load_pdf_text(path)
    rb = RegBook()
    out = []
    for t in pages:
        t = re.sub(r"[\ue000-\uf8ff]", "", t.replace("\r\n", "\n").replace("\r", "\n"))
        lines = t.split("\n")
        head = _parse_header(lines, rb)       # 규정집 형식 머리글이면 떼어 낸다
        if head:
            lines = lines[head[3]:]
        else:
            lines = [l for l in lines if not re.fullmatch(r"\s*-?\s*\d+\s*-?\s*", l)]
        out.append("\n".join(lines))
    return "\n".join(out)


def read_html(path: str | Path) -> str:
    t = read_text_file(path)
    t = re.sub(r"(?is)<(script|style).*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)


def read_any(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".hwpx":
        return read_hwpx(path)
    if ext == ".hwp":
        try:
            return read_hwp(path)
        except Exception:
            # 한글이 설치돼 있으면 한글로 변환해서 읽기
            t = hancom_extract_text(path)
            if t is not None:
                return t
            raise
    if ext == ".pdf":
        return read_pdf(path)
    if ext in (".html", ".htm"):
        return read_html(path)
    if ext == ".law3":
        raise ValueError("원본 법령안편집기(.law3) 파일은 원본 프로그램에서 [한글로 저장](HWP/HWPX) 후 불러오세요.")
    return read_text_file(path)


# ================================================================ 쓰기: HTML
HTML_STYLE = """
body{font-family:'함초롬바탕','HCR Batang','바탕',serif;font-size:11pt;line-height:1.6;margin:24px}
h1,h2,h3{text-align:center} p{margin:0 0 2px 0;white-space:pre-wrap}
table{border-collapse:collapse;width:100%} td,th{border:1px solid #000;vertical-align:top;padding:4px 6px}
th{background:#eee} u{text-decoration:underline}
"""


def text_to_html(text: str, title: str = "") -> str:
    body = "".join(f"<p>{html.escape(l) if l.strip() else '&nbsp;'}</p>" for l in text.split("\n"))
    return wrap_html(body, title)


def wrap_html(body: str, title: str = "") -> str:
    return (f"<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{HTML_STYLE}</style></head><body>{body}</body></html>")


# ================================================================ 쓰기: HWPX
NS = {
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
}
_XMLNS = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items())

# 글자 모양: 0 보통, 1 제목(굵게 14pt), 2 밑줄, 3 굵게
_CHARS = [(1100, False, False), (1400, True, False), (1100, False, True), (1100, True, False)]
# 문단 모양: 0 양쪽, 1 가운데, 2 내어쓰기(조문), 3 오른쪽
_PARAS = [("JUSTIFY", 0, 0), ("CENTER", 0, 0), ("JUSTIFY", 0, -1100), ("RIGHT", 0, 0)]


def _font_xml():
    langs = ["HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"]
    return "".join(f'<hh:fontface lang="{l}" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0">'
                   f'<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="4" contrast="0" strokeVariation="1" '
                   f'armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font></hh:fontface>' for l in langs)


def _lang_attrs(v):
    return " ".join(f'{k}="{v}"' for k in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"))


def _border_fill(i, solid):
    t = "SOLID" if solid else "NONE"
    return (f'<hh:borderFill id="{i}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
            f'<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            f'<hh:leftBorder type="{t}" width="0.12 mm" color="#000000"/><hh:rightBorder type="{t}" width="0.12 mm" color="#000000"/>'
            f'<hh:topBorder type="{t}" width="0.12 mm" color="#000000"/><hh:bottomBorder type="{t}" width="0.12 mm" color="#000000"/>'
            f'<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>')


def _header_xml() -> str:
    langs = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")
    attrs = lambda v: " ".join(f'{k}="{v}"' for k in langs)
    chars = []
    for i, (h, bold, ul) in enumerate(_CHARS):
        bold_xml = "<hh:bold/>" if bold else ""
        ul_type = "BOTTOM" if ul else "NONE"
        chars.append(
            f'<hh:charPr id="{i}" height="{h}" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" '
            f'symMark="NONE" borderFillIDRef="1"><hh:fontRef {attrs(0)}/><hh:ratio {attrs(100)}/>'
            f'<hh:spacing {attrs(0)}/><hh:relSz {attrs(100)}/><hh:offset {attrs(0)}/>{bold_xml}'
            f'<hh:underline type="{ul_type}" shape="SOLID" color="#000000"/>'
            '<hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/>'
            '<hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>')
    paras = []
    for i, (al, left, indent) in enumerate(_PARAS):
        paras.append(
            f'<hh:paraPr id="{i}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">'
            f'<hh:align horizontal="{al}" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/>'
            f'<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" '
            f'keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            f'<hh:margin><hc:intent value="{indent}" unit="HWPUNIT"/><hc:left value="{left}" unit="HWPUNIT"/>'
            f'<hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin>'
            f'<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>'
            f'<hh:border borderFillIDRef="1" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>'
            f'</hh:paraPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hh:head {_XMLNS} version="1.4" secCnt="1">'
            f'<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList>'
            f'<hh:fontfaces itemCnt="7">{_font_xml()}</hh:fontfaces>'
            f'<hh:borderFills itemCnt="2">{_border_fill(1, False)}{_border_fill(2, True)}</hh:borderFills>'
            f'<hh:charProperties itemCnt="{len(chars)}">{"".join(chars)}</hh:charProperties>'
            f'<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>'
            f'<hh:paraProperties itemCnt="{len(paras)}">{"".join(paras)}</hh:paraProperties>'
            f'<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" '
            f'charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>'
            f'</hh:refList><hh:compatibleDocument targetProgram="HWP201X"><hh:layoutCompatibility/></hh:compatibleDocument>'
            f'<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>'
            f'<hh:trackchageConfig flags="56"/></hh:head>')


_SECPR = ('<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" '
          'tabStopUnit="HWPUNIT" outlineShapeIDRef="0" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
          '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
          '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
          '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" '
          'hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
          '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
          '<hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">'
          '<hp:margin header="4252" footer="4252" gutter="0" left="7087" right="7087" top="5668" bottom="4252"/></hp:pagePr>'
          '</hp:secPr><hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>')

TEXT_WIDTH = 59528 - 7087 * 2


class HwpxBuilder:
    """문단·표로 HWPX 문서를 만든다."""

    def __init__(self, title: str = ""):
        self.title = title
        self.items: list[str] = []
        self._pid = 0

    def _p(self, runs: list[tuple[str, int]], para: int = 0, first: bool = False) -> str:
        self._pid += 1
        inner = []
        for k, (t, cp) in enumerate(runs):
            sec = _SECPR if (first and k == 0) else ""
            inner.append(f'<hp:run charPrIDRef="{cp}">{sec}<hp:t>{html.escape(t, quote=False)}</hp:t></hp:run>')
        if not inner:
            inner.append(f'<hp:run charPrIDRef="0">{_SECPR if first else ""}</hp:run>')
        return (f'<hp:p id="{self._pid}" paraPrIDRef="{para}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
                + "".join(inner) + '</hp:p>')

    def para(self, text: str, style: str = "normal"):
        cp, pp = {"normal": (0, 0), "title": (1, 1), "center": (0, 1), "bold": (3, 0), "right": (0, 3), "article": (0, 2)}[style]
        self.items.append(("p", [(text, cp)], pp))

    def rich(self, spans: list[tuple[str, bool]], style: str = "normal"):
        pp = {"normal": 0, "center": 1, "article": 2}[style]
        self.items.append(("p", [(t, 2 if u else 0) for t, u in spans if t], pp))

    def table(self, header: list[str], rows: list[list[list[list[tuple[str, bool]]]]], widths: list[int] | None = None):
        """rows[r][c] = 문단 목록, 문단 = [(텍스트, 밑줄)]."""
        self.items.append(("tbl", header, rows, widths))

    def _cell(self, paras, r, c, w, header=False):
        ps = []
        for spans in paras or [[("", False)]]:
            self._pid += 1
            runs = "".join(f'<hp:run charPrIDRef="{3 if header else (2 if u else 0)}"><hp:t>{html.escape(t, quote=False)}</hp:t></hp:run>'
                           for t, u in spans if t) or '<hp:run charPrIDRef="0"/>'
            ps.append(f'<hp:p id="{self._pid}" paraPrIDRef="{1 if header else 0}" styleIDRef="0" pageBreak="0" '
                      f'columnBreak="0" merged="0">{runs}</hp:p>')
        return (f'<hp:tc name="" header="{1 if header else 0}" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="2">'
                f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="{"CENTER" if header else "TOP"}" '
                f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                + "".join(ps) +
                f'</hp:subList><hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="{w}" height="1000"/><hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>')

    def _table_xml(self, header, rows, widths):
        ncol = len(header)
        widths = widths or [TEXT_WIDTH // ncol] * ncol
        trs = []
        all_rows = [[[[(h, False)]] for h in header]] + rows
        for r, row in enumerate(all_rows):
            tcs = "".join(self._cell(row[c] if c < len(row) else [], r, c, widths[c], header=(r == 0)) for c in range(ncol))
            trs.append(f"<hp:tr>{tcs}</hp:tr>")
        self._pid += 1
        tbl = (f'<hp:tbl id="{1000 + self._pid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" '
               f'lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" rowCnt="{len(all_rows)}" colCnt="{ncol}" '
               f'cellSpacing="0" borderFillIDRef="2" noAdjust="0">'
               f'<hp:sz width="{sum(widths)}" widthRelTo="ABSOLUTE" height="{1000 * len(all_rows)}" heightRelTo="ABSOLUTE" protect="0"/>'
               f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               f'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="510" right="510" top="141" bottom="141"/>'
               + "".join(trs) + '</hp:tbl>')
        self._pid += 1
        return (f'<hp:p id="{self._pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
                f'<hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run></hp:p>')

    def section_xml(self) -> str:
        parts = []
        first = True
        for it in self.items:
            if it[0] == "p":
                parts.append(self._p(it[1], it[2], first))
                first = False
            else:
                if first:
                    parts.append(self._p([], 0, True))
                    first = False
                parts.append(self._table_xml(it[1], it[2], it[3]))
        if first:
            parts.append(self._p([], 0, True))
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec {_XMLNS}>' + "".join(parts) + "</hs:sec>"

    def preview_text(self) -> str:
        out = []
        for it in self.items:
            if it[0] == "p":
                out.append("".join(t for t, _ in it[1]))
        return "\n".join(out)[:1000]

    def save(self, path: str | Path):
        version = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hv:HCFVersion '
                   'xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" '
                   'minor="1" micro="0" buildNumber="1" os="1" xmlVersion="1.4" application="Hancom Office Hangul" appVersion="11.0.0.0"/>')
        container = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><ocf:container '
                     'xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
                     '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
                     '</ocf:rootfiles></ocf:container>')
        manifest = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                    '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')
        hpf = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><opf:package xmlns:opf="http://www.idpf.org/2007/opf/" '
               'xmlns:dc="http://purl.org/dc/elements/1.1/" version="" unique-identifier="" id="">'
               f'<opf:metadata><opf:title>{html.escape(self.title)}</opf:title><opf:language>ko</opf:language></opf:metadata>'
               '<opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
               '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
               '<opf:item id="settings" href="settings.xml" media-type="application/xml"/></opf:manifest>'
               '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine>'
               '</opf:package>')
        settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><ha:HWPApplicationSetting '
                    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
                    '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/></ha:HWPApplicationSetting>')
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
            for name, data in [("version.xml", version), ("META-INF/container.xml", container),
                               ("META-INF/manifest.xml", manifest), ("Contents/content.hpf", hpf),
                               ("Contents/header.xml", _header_xml()), ("Contents/section0.xml", self.section_xml()),
                               ("settings.xml", settings), ("Preview/PrvText.txt", self.preview_text())]:
                z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


def text_to_hwpx(text: str, path: str | Path, title: str = "", title_lines: int = 0):
    b = HwpxBuilder(title)
    for i, line in enumerate(text.split("\n")):
        if i < title_lines:
            b.para(line, "title")
        elif re.match(r"^\s*제\d+조", line):
            b.para(line, "article")
        else:
            b.para(line)
    b.save(path)


def compare_table_to_hwpx(rows, path: str | Path, title: str):
    """amend.build_compare_table 결과를 HWPX 표로."""
    b = HwpxBuilder(title)
    b.para(title, "title")
    b.para("")
    b.table(["현      행", "개   정   안"], [[r.left, r.right] for r in rows])
    b.save(path)


# ================================================================ 한글(HWP) 연동 — Windows + 한글 설치 시
def hancom_available() -> bool:
    try:
        import win32com.client  # noqa: F401
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "HWPFrame.HwpObject")
        return True
    except Exception:
        return False


def _hwp_app():
    import win32com.client
    hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception:
        pass
    try:
        hwp.XHwpWindows.Item(0).Visible = False
    except Exception:
        pass
    return hwp


def hancom_convert(src: str | Path, dst: str | Path, fmt: str = "HWP") -> bool:
    """한글로 src(HWPX/HTML)를 열어 dst(HWP/PDF/HWPX)로 저장."""
    if not hancom_available():
        return False
    hwp = _hwp_app()
    try:
        src_fmt = {".hwpx": "HWPX", ".html": "HTML", ".htm": "HTML", ".hwp": "HWP", ".txt": "TEXT"}.get(Path(src).suffix.lower(), "")
        hwp.Open(str(Path(src).resolve()), src_fmt, "forceopen:true")
        ok = hwp.SaveAs(str(Path(dst).resolve()), fmt, "")
        return bool(ok)
    finally:
        try:
            hwp.Clear(1)
            hwp.Quit()
        except Exception:
            pass


def hancom_extract_text(src: str | Path) -> str | None:
    if not hancom_available():
        return None
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "out.txt"
    hwp = _hwp_app()
    try:
        hwp.Open(str(Path(src).resolve()), "", "forceopen:true")
        hwp.SaveAs(str(tmp), "TEXT", "")
        return read_text_file(tmp)
    except Exception:
        return None
    finally:
        try:
            hwp.Clear(1)
            hwp.Quit()
        except Exception:
            pass
