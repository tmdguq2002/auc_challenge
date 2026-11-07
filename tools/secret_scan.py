"""API 키 유출 검사 — 저장소·배포 폴더에서 키 형태 문자열을 찾는다.
사용: python tools/secret_scan.py [경로 ...]   (기본: 저장소 추적 파일 + dist)
pre-commit 훅과 테스트에서 호출한다. 키를 찾으면 종료코드 1.
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    re.compile(rb"sk-ant-[A-Za-z0-9]{2,6}-[A-Za-z0-9_\-]{20,}"),   # Anthropic
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_\-]{32,}"),                # OpenAI 형식
    re.compile(rb"AIza[0-9A-Za-z_\-]{35}"),                           # Google API 키
]
ROOT = Path(__file__).resolve().parent.parent


def _personal_values() -> list[re.Pattern]:
    """이 PC 설정에 있는 법령 API OC 값도 저장소에 들어가면 안 된다."""
    import json
    import os
    out = []
    for base in (os.environ.get("APPDATA"), str(Path.home() / ".config")):
        if not base:
            continue
        f = Path(base) / "LawEdit" / "settings.json"
        try:
            oc = json.loads(f.read_text(encoding="utf-8")).get("oc", "")
        except Exception:
            continue
        if oc and len(oc) >= 4 and oc != "test":
            out.append(re.compile(re.escape(oc).encode()))
    return out


PATTERNS += _personal_values()


def scan_bytes(data: bytes) -> bool:
    return any(p.search(data) for p in PATTERNS)


def targets(args):
    if args:
        for a in args:
            p = Path(a)
            yield from (p.rglob("*") if p.is_dir() else [p])
        return
    try:
        files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
        for f in files:
            if f:
                yield ROOT / f.decode()
    except Exception:
        yield from ROOT.rglob("*.py")
    dist = ROOT / "dist"
    if dist.exists():
        yield from dist.rglob("*")


def main(args) -> int:
    bad = []
    for p in targets(args):
        try:
            if p.is_file() and p.stat().st_size < 200_000_000 and scan_bytes(p.read_bytes()):
                bad.append(p)
        except OSError:
            continue
    for p in bad:
        print(f"[유출 의심] {p}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
