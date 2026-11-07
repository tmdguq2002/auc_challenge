"""LLM 연결 계층 — API 교체형(모델 비종속).

- anthropic : Claude (공식 Anthropic SDK)
- openai    : OpenAI 호환 API (OpenAI, Google Gemini 호환 주소, 행정안전부 AI 공통기반·사내 API 서버 등)
설정은 %APPDATA%/LawEdit/settings.json 의 "llm" 항목.
API 키 보호:
  - Windows 보안 저장소(DPAPI)로 암호화해 저장한다. 같은 PC·같은 사용자만 복호화할 수 있다.
  - 평문 키는 파일·로그·화면 어디에도 남기지 않는다. 환경변수(LAWEDIT_API_KEY)로도 줄 수 있다.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from ..core import lawapi

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"

# 모델 이름은 각 API 회사 안내에 따라 입력한다(Claude 만 기본값 제공)
PRESETS = {
    "Claude (Anthropic API)": {"provider": "anthropic", "model": DEFAULT_CLAUDE_MODEL, "base_url": ""},
    "OpenAI API": {"provider": "openai", "model": "", "base_url": "https://api.openai.com/v1"},
    "Google Gemini API (OpenAI 호환 주소)": {"provider": "openai", "model": "", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "행정안전부 AI 공통기반 · 사내 API 서버 (주소 입력)": {"provider": "openai", "model": "", "base_url": "https://"},
}

KEY_ENV = "LAWEDIT_API_KEY"


# ------------------------------------------------------------------ 키 암호화 (Windows DPAPI)
def _protect(key: str) -> str:
    import base64
    import win32crypt
    blob = win32crypt.CryptProtectData(key.encode("utf-8"), "LawEdit API key", None, None, None, 0)
    return base64.b64encode(blob).decode("ascii")


def _unprotect(enc: str) -> str:
    import base64
    import win32crypt
    _, data = win32crypt.CryptUnprotectData(base64.b64decode(enc), None, None, None, 0)
    return data.decode("utf-8")


def secure_store_available() -> bool:
    try:
        import win32crypt  # noqa: F401
        return True
    except Exception:
        return False


def mask(key: str) -> str:
    return (key[:7] + "…" + key[-4:]) if key and len(key) > 12 else ("설정됨" if key else "")


@dataclass
class LLMConfig:
    provider: str = "anthropic"          # anthropic | openai
    model: str = DEFAULT_CLAUDE_MODEL
    api_key: str = ""
    base_url: str = ""                   # openai 호환 서버 주소 (…/v1)
    workspace_id: str = ""               # 워크스페이스에 묶이지 않은 Anthropic 키용
    effort: str = "medium"               # Claude: low | medium | high | xhigh | max
    timeout: float = 180.0
    extra: dict = field(default_factory=dict)

    @staticmethod
    def load() -> "LLMConfig":
        s = lawapi.load_settings()
        d = s.get("llm", {})
        c = LLMConfig()
        for k, v in d.items():
            if hasattr(c, k) and k != "api_key":
                setattr(c, k, v)
        enc = d.get("api_key_enc", "")
        if enc:
            try:
                c.api_key = _unprotect(enc)
            except Exception:
                c.api_key = ""          # 다른 PC·다른 사용자에서 복사해 온 설정 → 복호화 불가
        elif d.get("api_key"):
            # 예전 평문 저장분 → 암호화로 옮기고 평문 삭제
            c.api_key = d["api_key"]
            try:
                c.save()
            except Exception:
                pass
        if not c.api_key:
            c.api_key = os.environ.get(KEY_ENV, "")
        return c

    def save(self):
        s = lawapi.load_settings()
        d = {k: getattr(self, k) for k in ("provider", "model", "base_url", "workspace_id", "effort", "timeout")}
        if self.api_key and self.api_key != os.environ.get(KEY_ENV, ""):
            if not secure_store_available():
                raise LLMError("이 환경에서는 키를 안전하게 저장할 수 없습니다. 환경변수 LAWEDIT_API_KEY 로 지정하세요.")
            d["api_key_enc"] = _protect(self.api_key)
        s["llm"] = d                      # 평문 api_key 항목은 남기지 않는다
        lawapi.save_settings(s)

    @property
    def ready(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.api_key and self.model)
        return bool(self.base_url and self.model)

    def label(self) -> str:
        return f"{'Claude' if self.provider == 'anthropic' else 'OpenAI 호환 API'} · {self.model}"


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    note: str = ""


def complete(cfg: LLMConfig, system: str, user: str, max_tokens: int = 16000, effort: str | None = None,
             json_mode: bool = False) -> LLMResult:
    """한 번 묻고 답 받기."""
    if not cfg.ready:
        raise LLMError("AI API가 설정되지 않았습니다. [AI 도우미] → [AI 설정]에서 API 키를 입력하세요.")
    if cfg.provider == "anthropic":
        return _anthropic(cfg, system, user, max_tokens, effort or cfg.effort)
    return _openai_compat(cfg, system, user, max_tokens, json_mode)


_CLIENT: tuple | None = None       # (설정 지문, 클라이언트) — 연결을 다시 쓰려고 하나만 둔다(메모리에만)


def _anthropic_client(cfg: LLMConfig):
    global _CLIENT
    import anthropic
    fp = hashlib.sha256(f"{cfg.api_key}|{cfg.timeout}|{cfg.workspace_id}".encode()).hexdigest()
    if _CLIENT is None or _CLIENT[0] != fp:
        headers = {"anthropic-workspace-id": cfg.workspace_id} if cfg.workspace_id else None
        _CLIENT = (fp, anthropic.Anthropic(api_key=cfg.api_key, timeout=cfg.timeout, max_retries=2, default_headers=headers))
    return _CLIENT[1]


def _anthropic(cfg: LLMConfig, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
    import anthropic
    client = _anthropic_client(cfg)
    kwargs = dict(model=cfg.model, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": user}],
                  output_config={"effort": effort})
    # 최신 모델은 안전 분류기가 거절하면 같은 요청을 다른 모델로 다시 처리하도록(server-side fallback)
    use_fallback = cfg.model in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
    try:
        if use_fallback:
            with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs) as st:
                r = st.get_final_message()
        else:
            with client.messages.stream(**kwargs) as st:
                r = st.get_final_message()
    except anthropic.AuthenticationError:
        raise LLMError("API 키가 올바르지 않습니다.")
    except anthropic.PermissionDeniedError as e:
        raise LLMError(f"권한이 없습니다: {_redact(e.message, cfg.api_key)}")
    except anthropic.BadRequestError as e:
        msg = _redact(e.message, cfg.api_key)
        if "workspace" in msg:
            msg = "이 API 키는 워크스페이스 지정이 필요합니다. 설정에 워크스페이스 ID(wrkspc_…)를 입력하세요."
        raise LLMError(msg)
    except anthropic.RateLimitError:
        raise LLMError("요청 한도를 넘었습니다. 잠시 후 다시 시도하세요.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"AI 서버 오류({e.status_code}). 잠시 후 다시 시도하세요.")
    except anthropic.APIConnectionError:
        raise LLMError("AI 서버에 연결할 수 없습니다. 인터넷(또는 기관 방화벽)을 확인하세요.")
    if r.stop_reason == "refusal":
        raise LLMError("AI가 이 요청을 처리하지 않았습니다(안전 정책). 표현을 바꿔 다시 시도하세요.")
    text = "".join(b.text for b in r.content if b.type == "text")
    note = "응답이 길이 제한에서 잘렸습니다." if r.stop_reason == "max_tokens" else ""
    return LLMResult(text, r.model, r.usage.input_tokens, r.usage.output_tokens, note)


def _openai_compat(cfg: LLMConfig, system: str, user: str, max_tokens: int, json_mode: bool) -> LLMResult:
    import requests
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    body = {"model": cfg.model, "max_tokens": min(max_tokens, 8192), "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    try:
        r = requests.post(url, headers=headers, data=json.dumps(body), timeout=cfg.timeout)
    except requests.RequestException as e:
        raise LLMError(f"AI API({cfg.base_url})에 연결할 수 없습니다. 주소와 인터넷(방화벽)을 확인하세요. ({e.__class__.__name__})")
    if r.status_code in (401, 403):
        raise LLMError("API 키가 올바르지 않거나 권한이 없습니다.")
    if r.status_code != 200:
        raise LLMError(f"AI API 오류({r.status_code}): {_redact(r.text[:200], cfg.api_key)}")
    d = r.json()
    ch = (d.get("choices") or [{}])[0]
    text = (ch.get("message") or {}).get("content") or ""
    u = d.get("usage") or {}
    note = "응답이 길이 제한에서 잘렸습니다." if ch.get("finish_reason") == "length" else ""
    return LLMResult(text, d.get("model", cfg.model), u.get("prompt_tokens", 0), u.get("completion_tokens", 0), note)


def _redact(text: str, key: str) -> str:
    """오류 메시지에 키가 섞여 나오지 않게."""
    import re
    if key:
        text = text.replace(key, "***")
    return re.sub(r"(sk-[A-Za-z0-9_\-]{6})[A-Za-z0-9_\-]{10,}", r"\1***", text)


def extract_json(text: str):
    """응답에서 JSON 덩어리 꺼내기 (```json … ``` 포함)."""
    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    s = m.group(1) if m else text
    i = min([k for k in (s.find("{"), s.find("[")) if k >= 0], default=-1)
    if i < 0:
        raise LLMError("AI 응답에서 결과(JSON)를 찾지 못했습니다.")
    s = s[i:]
    for end in range(len(s), 0, -1):
        if s[end - 1] in "}]":
            try:
                return json.loads(s[:end])
            except json.JSONDecodeError:
                continue
    raise LLMError("AI 응답 형식을 해석하지 못했습니다.")
