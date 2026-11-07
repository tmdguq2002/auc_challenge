"""국가법령정보 공동활용 Open API (open.law.go.kr) 연동.

OC 값(가입한 이메일 아이디)이 있어야 한다. https://open.law.go.kr → 회원가입 → OPEN API 신청.
target=law(법령), ordin(자치법규), admrul(행정규칙)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .model import LawDoc
from .parser import parse_text

BASE = "https://www.law.go.kr/DRF"
TARGETS = {"law": "법령", "ordin": "자치법규", "admrul": "행정규칙"}


@dataclass
class LawHit:
    target: str
    name: str
    mst: str          # 일련번호
    law_id: str
    kind: str         # 법령구분
    ministry: str
    promulgated: str
    effective: str
    amend: str
    link: str
    abbr: str = ""


def settings_dir() -> Path:
    p = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "LawEdit"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_settings() -> dict:
    f = settings_dir() / "settings.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(d: dict):
    (settings_dir() / "settings.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


_SESSION = None


def _session():
    """연결·TLS·인증서 묶음을 요청마다 새로 만들지 않도록 한 세션을 함께 쓴다(요청당 1~2초 → 0.2초)."""
    global _SESSION
    if _SESSION is None:
        import requests
        s = requests.Session()
        s.headers["User-Agent"] = "LawEdit/1.0"
        _SESSION = s
    return _SESSION


class LawAPI:
    def __init__(self, oc: str | None = None, timeout: float = 15.0, cache_days: int = 7):
        self.oc = (oc if oc is not None else load_settings().get("oc", "")).strip()
        self.timeout = timeout
        self.cache = settings_dir() / "cache"
        self.cache.mkdir(exist_ok=True)
        self.cache_sec = cache_days * 86400

    @property
    def ready(self) -> bool:
        return bool(self.oc)

    def _get(self, url: str) -> dict:
        key = hashlib.sha1(url.encode()).hexdigest()
        cf = self.cache / f"{key}.json"
        if cf.exists() and time.time() - cf.stat().st_mtime < self.cache_sec:
            return json.loads(cf.read_text(encoding="utf-8"))
        r = _session().get(url, timeout=self.timeout)
        r.raise_for_status()
        txt = r.text.strip()
        if not txt.startswith("{"):
            if "사용자 정보 검증에 실패" in txt or "OC" in txt[:200]:
                raise RuntimeError("법령 API 인증 실패: 설정에서 OC(이메일 아이디)와 API 신청 상태를 확인하세요.")
            raise RuntimeError("법령 API 응답을 해석할 수 없습니다: " + re.sub(r"<[^>]+>", " ", txt)[:200])
        d = r.json()
        cf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return d

    def search(self, query: str, target: str = "law", display: int = 30, page: int = 1, body: bool = False) -> list[LawHit]:
        if not self.ready:
            raise RuntimeError("법령 API OC 값이 설정되지 않았습니다. [설정]에서 입력하세요.")
        url = (f"{BASE}/lawSearch.do?OC={quote(self.oc)}&target={target}&type=JSON&query={quote(query)}"
               f"&display={display}&page={page}" + ("&search=2" if body else ""))
        d = self._get(url)
        root = next(iter(d.values())) if d else {}
        items = root.get(target) or root.get("law") or []
        if isinstance(items, dict):
            items = [items]
        out = []
        for it in items:
            g = lambda *ks: next((str(it[k]) for k in ks if it.get(k)), "")
            out.append(LawHit(target, g("법령명한글", "자치법규명", "행정규칙명"), g("법령일련번호", "자치법규일련번호", "행정규칙일련번호"),
                              g("법령ID", "자치법규ID", "행정규칙ID"), g("법령구분명", "자치법규종류", "행정규칙종류"),
                              g("소관부처명", "지자체기관명", "소관부처명"), g("공포일자", "발령일자"), g("시행일자"),
                              g("제개정구분명"), g("법령상세링크", "자치법규상세링크", "행정규칙상세링크"), g("법령약칭명")))
        return out

    def detail_json(self, hit_or_mst, target: str = "law") -> dict:
        mst = hit_or_mst.mst if isinstance(hit_or_mst, LawHit) else str(hit_or_mst)
        target = hit_or_mst.target if isinstance(hit_or_mst, LawHit) else target
        key = "MST" if target != "admrul" else "ID"
        return self._get(f"{BASE}/lawService.do?OC={quote(self.oc)}&target={target}&{key}={mst}&type=JSON")

    def fetch_doc(self, hit: LawHit) -> LawDoc:
        d = self.detail_json(hit)
        lines = json_to_lines(d)
        doc = parse_text("\n".join([hit.name] + lines), name=hit.name)
        doc.law_type = hit.kind or doc.law_type
        doc.org = hit.ministry
        doc.meta.update({"source": "law.go.kr", "mst": hit.mst, "promulgated": hit.promulgated, "effective": hit.effective})
        return doc

    def find_law(self, name: str) -> LawHit | None:
        """법령명으로 찾기 (법령 → 자치법규 → 행정규칙). 정확히 같은 이름, 약칭, 앞부분이 빠진 이름 순."""
        n = norm_law_name(name)
        q = re.sub(r"[․·・‧]", "ㆍ", name)
        for target in ("law", "ordin", "admrul"):
            try:
                hits = self.search(q, target, display=30)
            except RuntimeError:
                raise
            except Exception:
                continue
            for h in hits:
                if norm_law_name(h.name) == n or (h.abbr and norm_law_name(h.abbr) == n):
                    return h
            for h in hits:      # '단시간근로자 보호 등에 관한 법률' → '기간제 및 단시간근로자 …'
                hn = norm_law_name(h.name)
                if len(n) >= 8 and hn.endswith(n) and hn.endswith(("시행령", "시행규칙")) == n.endswith(("시행령", "시행규칙")):
                    return h
        return None

    def suggest_name(self, name: str) -> str:
        """찾지 못한 법령명과 가장 비슷한 현행 법령명 (이름이 바뀐 경우)."""
        import difflib
        try:
            hits = self.search(re.sub(r"\s*(에\s*관한\s*법률|법)$", "", name)[:20] or name, "law", display=10)
        except Exception:
            return ""
        best, score = "", 0.0
        for h in hits:
            sc = difflib.SequenceMatcher(None, norm_law_name(name), norm_law_name(h.name)).ratio()
            if sc > score:
                best, score = h.name, sc
        return best if score >= 0.6 else ""


def json_to_lines(d) -> list[str]:
    """법령 본문 JSON → 텍스트 줄 (조문·항·호·목 '내용' 필드를 순서대로)."""
    out: list[str] = []
    # 자치법규: LawService.조문.조[].조내용 (본칙만)
    jo = (d.get("LawService") or {}).get("조문", {}).get("조") if isinstance(d, dict) else None
    if isinstance(jo, list):
        res = []
        last = 0
        for x in jo:
            num_raw = x.get("조문번호")
            num_raw = num_raw[0] if isinstance(num_raw, list) and num_raw else str(num_raw or "")
            if str(x.get("조문여부", "")).upper() == "Y" and num_raw[:4].isdigit():
                n = int(num_raw[:4])
                if n < last:          # 부칙 조문이 섞여 들어온 경우
                    continue
                last = n
            t = re.sub(r"\s*부\s*칙\s*$", "", str(x.get("조내용", "")))
            if str(x.get("조문여부", "")).upper() == "N":
                # 장·절 제목 항목에 다른 내용이 붙어 오는 경우 제목만
                t = re.split(r"(?=제\d+조(?:의\d+)?\()|부\s*칙", t)[0].strip()
            for line in split_inline(t).split("\n"):
                if line.strip():
                    res.append(line.strip())
        return res

    def walk(x, depth=0):
        if isinstance(x, dict):
            # 조문단위 우선 처리
            for k, v in x.items():
                if k in ("기본정보", "자치법규기본정보", "개정문", "제개정이유", "별표", "부칙", "법령키", "행정규칙기본정보"):
                    continue
                if isinstance(v, str):
                    if k.endswith("내용") and v.strip():
                        for line in v.replace("\r", "").split("\n"):
                            if line.strip():
                                out.append(line.strip())
                else:
                    walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1)
    units = (d.get("법령") or {}).get("조문", {}).get("조문단위") if isinstance(d, dict) else None
    if isinstance(units, dict):
        units = [units]
    if isinstance(units, list):
        # 법령: 조문내용(제목 줄) → 항 → 호 → 목 순서로 (JSON 키 순서는 항이 먼저 올 수 있음)
        def emit(text):
            for line in str(text or "").replace("\r", "").split("\n"):
                if line.strip():
                    out.append(line.strip())

        def sub(x, key, content):
            lst = x.get(key) or []
            if isinstance(lst, dict):
                lst = [lst]
            for it in lst:
                if isinstance(it, dict):
                    emit(it.get(content))
                    if key == "항":
                        sub(it, "호", "호내용")
                    elif key == "호":
                        sub(it, "목", "목내용")
        for u in units:
            if not isinstance(u, dict):
                continue
            emit(u.get("조문내용"))
            sub(u, "항", "항내용")
            if not u.get("항"):
                sub(u, "호", "호내용")
    else:
        walk(d)
    # 자치법규처럼 항·호가 한 줄에 붙어 오는 경우 나눈다
    split: list[str] = []
    for l in out:
        split.extend(x.strip() for x in split_inline(l).split("\n") if x.strip())
    # 중복 제거(조문내용과 항내용이 겹치는 경우)
    res: list[str] = []
    for l in split:
        if res and res[-1] == l:
            continue
        res.append(l)
    return res


def split_inline(t: str) -> str:
    t = re.sub(r"(?<=\S)\s*(?=[②-⑳㉑-㉟])", "\n", t)
    t = re.sub(r"(?<=[.다])\s*(?=제\d+조(?:의\d+)?\()", "\n", t)
    t = re.sub(r"(?<=[가-힣.)」])(?=\d{1,2}(?:의\d+)?\.(?:\s|[「“(가-힣]))", "\n", t)
    return t


def norm_law_name(n: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"[․·・‧ㆍ]", "ㆍ", n or ""))


def law_url(name: str, article: str = "") -> str:
    return f"https://www.law.go.kr/법령/{quote(name)}" + (f"/{quote(article)}" if article else "")
