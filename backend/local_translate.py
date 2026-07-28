"""Ollama / NLLB translation (local or remote VPS with optional Bearer token)."""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request

logger = logging.getLogger("ondertitels.local_translate")

# ISO-639-1 → NLLB Flores codes (subset used by Ondertitels)
_NLLB_CODES = {
    "en": "eng_Latn",
    "nl": "nld_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
    "zh": "zho_Hans",
    "sw": "swh_Latn",
    "ln": "lin_Latn",
    "mg": "plt_Latn",
}

_LANG_NAMES = {
    "nl": "Dutch",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "zh": "Chinese",
    "sw": "Swahili",
    "mg": "Malagasy",
    "kg": "Kikongo",
    "ts": "Tshiluba",
    "ln": "Lingala",
}

_nllb_pipe = None
_nllb_lock = threading.Lock()


def _ollama_headers(api_token: str | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    tok = (api_token or "").strip()
    if tok:
        # Support raw token or already-prefixed "Bearer …"
        if tok.lower().startswith("bearer "):
            headers["Authorization"] = tok
        else:
            headers["Authorization"] = f"Bearer {tok}"
    return headers


def _ollama_request(
    base_url: str,
    path: str,
    *,
    api_token: str | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
    method: str | None = None,
) -> dict | list | None:
    url = (base_url or "").rstrip("/") + path
    meth = method or ("POST" if data is not None else "GET")
    req = urllib.request.Request(
        url,
        data=data,
        headers=_ollama_headers(api_token),
        method=meth,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user-configured Ollama
        raw = resp.read().decode("utf-8")
        if not raw:
            return None
        return json.loads(raw)


def ollama_available(
    base_url: str,
    api_token: str | None = None,
    timeout: float = 3.0,
) -> bool:
    try:
        body = _ollama_request(
            base_url,
            "/api/tags",
            api_token=api_token,
            timeout=timeout,
        )
        return isinstance(body, dict)
    except Exception as e:
        logger.debug("Ollama availability check failed: %s", e)
        return False


def nllb_available() -> bool:
    try:
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def local_translate_available(
    ollama_base_url: str,
    api_token: str | None = None,
) -> bool:
    return ollama_available(ollama_base_url, api_token=api_token) or nllb_available()


def _ollama_list_models(
    base_url: str,
    api_token: str | None = None,
    timeout: float = 5.0,
) -> list[str]:
    try:
        body = _ollama_request(
            base_url,
            "/api/tags",
            api_token=api_token,
            timeout=timeout,
        )
        if not isinstance(body, dict):
            return []
        return [str(m.get("name") or "") for m in (body.get("models") or []) if m.get("name")]
    except Exception:
        return []


def _resolve_ollama_model(
    base_url: str,
    preferred: str,
    api_token: str | None = None,
) -> str:
    preferred = (preferred or "").strip() or "qwen2.5:7b"
    installed = _ollama_list_models(base_url, api_token=api_token)
    if not installed:
        return preferred
    if preferred in installed:
        return preferred
    pref_base = preferred.split(":")[0]
    for name in installed:
        if name == preferred or name.startswith(pref_base + ":"):
            return name
    for candidate in (
        "qwen2.5:7b",
        "qwen2.5:14b",
        "mistral:latest",
        "mistral:7b",
        "llama3.1:8b",
        "llama3.2:3b",
    ):
        for name in installed:
            if name == candidate or name.startswith(candidate.split(":")[0] + ":"):
                logger.info("Ollama model %s missing; using installed %s", preferred, name)
                return name
    return installed[0]


def _ollama_translate(
    text: str,
    target_lang: str,
    source_lang: str,
    *,
    base_url: str,
    model: str,
    api_token: str | None = None,
    timeout: float = 90.0,
) -> str:
    candidates = [model]
    # If preferred model OOMs on a small VPS, fall through to lighter ones.
    for alt in ("llama3.2:3b", "llama3.2:1b", "mistral:latest", "mistral:7b", "qwen2.5:7b"):
        if alt not in candidates:
            candidates.append(alt)

    last_err: Exception | None = None
    for cand in candidates:
        try:
            resolved = _resolve_ollama_model(base_url, cand, api_token=api_token)
            return _ollama_translate_once(
                text,
                target_lang,
                source_lang,
                base_url=base_url,
                model=resolved,
                api_token=api_token,
                timeout=timeout,
            )
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "memory" in msg or "system memory" in msg or "out of memory" in msg:
                logger.warning("Ollama model %s OOM/unavailable, trying smaller model…", cand)
                continue
            # Non-memory errors: still try next only if model missing
            if "not found" in msg or "pull" in msg:
                continue
            raise
    raise RuntimeError(str(last_err) if last_err else "Ollama translate failed")


def _ollama_translate_once(
    text: str,
    target_lang: str,
    source_lang: str,
    *,
    base_url: str,
    model: str,
    api_token: str | None = None,
    timeout: float = 90.0,
) -> str:
    tgt = _LANG_NAMES.get(target_lang, target_lang)
    src = (
        _LANG_NAMES.get(source_lang, source_lang)
        if source_lang and source_lang != "auto"
        else "French"
    )
    user = (
        f"Translate to {tgt}. Keep biblical terms. Output only the translation.\n"
        f"({src})\n{text}"
    )
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": "30m",
        "messages": [{"role": "user", "content": user}],
        "options": {
            "temperature": 0.0,
            "num_predict": 220,
            "num_ctx": 2048,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    try:
        body = _ollama_request(
            base_url,
            "/api/chat",
            api_token=api_token,
            data=data,
            timeout=timeout,
        )
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        raise RuntimeError(f"Ollama HTTP {e.code}: {detail}") from e

    if not isinstance(body, dict):
        raise RuntimeError("Ollama returned invalid JSON")
    msg = (body.get("message") or {}).get("content") or body.get("response") or ""
    out = str(msg).strip()
    if not out:
        raise RuntimeError("Ollama returned empty translation")
    return out


def _get_nllb_pipeline(model_id: str):
    global _nllb_pipe
    with _nllb_lock:
        if _nllb_pipe is not None:
            return _nllb_pipe
        from transformers import pipeline

        logger.info("Loading NLLB model %s (first load downloads weights)", model_id)
        _nllb_pipe = pipeline("translation", model=model_id, device=-1)
        return _nllb_pipe


def _nllb_translate(
    text: str,
    target_lang: str,
    source_lang: str,
    *,
    model_id: str,
) -> str:
    tgt = _NLLB_CODES.get(target_lang)
    if not tgt:
        raise ValueError(f"NLLB does not support target language: {target_lang}")
    src = _NLLB_CODES.get(source_lang) if source_lang and source_lang != "auto" else None
    if not src:
        src = _NLLB_CODES.get("fr", "fra_Latn")

    pipe = _get_nllb_pipeline(model_id)
    try:
        result = pipe(text, src_lang=src, tgt_lang=tgt, max_length=512)
    except TypeError:
        result = pipe(f"{src} {text}", max_length=512)

    if isinstance(result, list) and result:
        item = result[0]
        if isinstance(item, dict):
            return str(item.get("translation_text") or item.get("text") or "").strip()
    return str(result or "").strip()


def local_translate_text(
    text: str,
    target_lang: str,
    source_lang: str = "auto",
    *,
    ollama_base_url: str,
    ollama_model: str,
    nllb_model: str,
    ollama_api_token: str | None = None,
    prefer: str = "ollama",
) -> tuple[str, str]:
    """
    Translate text via Ollama (remote/local) or NLLB.
    Returns (translated_text, provider) where provider is 'ollama' or 'nllb'.
    """
    text = (text or "").strip()
    if not text:
        return "", "none"
    target = (target_lang or "").strip().lower()
    source = (source_lang or "auto").strip().lower()
    prefer = (prefer or "ollama").strip().lower()
    token = (ollama_api_token or "").strip() or None

    errors: list[str] = []
    order = ["ollama", "nllb"] if prefer != "nllb" else ["nllb", "ollama"]

    for provider in order:
        if provider == "ollama":
            if not ollama_available(ollama_base_url, api_token=token):
                errors.append("Ollama not reachable (check URL + Bearer token)")
                continue
            try:
                out = _ollama_translate(
                    text,
                    target,
                    source,
                    base_url=ollama_base_url,
                    model=ollama_model,
                    api_token=token,
                )
                return out, "ollama"
            except Exception as e:
                errors.append(f"Ollama: {e}")
                logger.warning("Ollama translate failed: %s", e)
        elif provider == "nllb":
            if not nllb_available():
                errors.append("transformers/NLLB not installed")
                continue
            try:
                out = _nllb_translate(
                    text,
                    target,
                    source,
                    model_id=nllb_model,
                )
                if not out:
                    raise RuntimeError("empty NLLB output")
                return out, "nllb"
            except Exception as e:
                errors.append(f"NLLB: {e}")
                logger.warning("NLLB translate failed: %s", e)

    raise RuntimeError("Local translation failed. " + " | ".join(errors))
