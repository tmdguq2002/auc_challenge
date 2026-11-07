"""한글 조사 처리."""
from __future__ import annotations

# 숫자를 읽을 때 마지막 음절의 받침: 0영 1일 2이 3삼 4사 5오 6육 7칠 8팔 9구
_DIGIT_JONG = {"0": 21, "1": 8, "2": 0, "3": 16, "4": 0, "5": 0, "6": 21, "7": 8, "8": 8, "9": 0}
_LATIN_JONG = {"l": 8, "m": 16, "n": 4, "r": 8}
_SKIP = set(" )]}」』”’\"'.,·ㆍ>〉")


def last_jong(word: str) -> int:
    """마지막 글자의 종성 번호(0=받침 없음, 8=ㄹ)."""
    for ch in reversed(word):
        if ch in _SKIP:
            continue
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return (code - 0xAC00) % 28
        if ch in _DIGIT_JONG:
            return _DIGIT_JONG[ch]
        if ch.lower() in _LATIN_JONG:
            return _LATIN_JONG[ch.lower()]
        if ch.isalpha():
            return 0
        if ch in "①②③④⑤⑥⑦⑧⑨⑩":
            return _DIGIT_JONG[str(("①②③④⑤⑥⑦⑧⑨⑩".index(ch) + 1) % 10)]
        return 0
    return 0


def josa(word: str, pair: str) -> str:
    """josa('시장', '을/를') -> '을'. pair: 을/를, 이/가, 은/는, 과/와, 으로/로, 이라/라."""
    a, b = pair.split("/")
    j = last_jong(word)
    if pair in ("으로/로",):
        return b if j in (0, 8) else a
    return a if j else b


def with_josa(word: str, pair: str) -> str:
    return word + josa(word, pair)
