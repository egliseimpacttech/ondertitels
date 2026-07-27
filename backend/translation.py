"""Translation: DeepL (NL, EN, PT, ES, ZH, FR, SW) with OpenAI fallback; OpenAI for Malgasy/Kikongo/Tshiluba (strong model) and Lingala (lighter)."""
import hashlib
from typing import Dict

import deepl
from openai import OpenAI

from .config import (
    DEEPL_LANGUAGES,
    OPENAI_LANGUAGES,
    OPENAI_TRANSLATION_MODEL,
    OPENAI_TRANSLATION_MODEL_MG_KG_TS,
)

# Use full gpt-4o-class model + French-unknown-word rule for these targets
OPENAI_STRONG_AFRICAN_LANGS = frozenset({"mg", "kg", "ts"})

# Simple in-memory cache for translations (key: hash of text+lang, value: translated text)
_translation_cache: Dict[str, str] = {}


def _get_cache_key(
    text: str,
    target_lang: str,
    source_lang: str = "",
    *,
    openai_model: str | None = None,
) -> str:
    """Generate cache key for translation. openai_model isolates OpenAI cache per model."""
    content = f"{text}|{target_lang}|{source_lang}"
    if openai_model:
        content += f"|openai:{openai_model}"
    return hashlib.md5(content.encode()).hexdigest()


def _get_cached_translation(
    text: str,
    target_lang: str,
    source_lang: str = "",
    *,
    openai_model: str | None = None,
) -> str | None:
    """Get cached translation if available."""
    key = _get_cache_key(text, target_lang, source_lang, openai_model=openai_model)
    return _translation_cache.get(key)


def _cache_translation(
    text: str,
    target_lang: str,
    source_lang: str,
    translated: str,
    *,
    openai_model: str | None = None,
) -> None:
    """Cache a translation result."""
    key = _get_cache_key(text, target_lang, source_lang, openai_model=openai_model)
    _translation_cache[key] = translated


def translate_segments(
    segments: list[dict],
    target_lang: str,
    source_lang: str,
    deepl_key: str,
    openai_key: str,
    progress_callback=None,
) -> list[str]:
    """
    Translate segment texts to target_lang. Returns list of translated strings.
    progress_callback(segment_index, total_segments) is called after each segment if provided.

    Raises:
        ValueError: If no translation API is available for the target language
        Exception: If translation fails and no fallback is available
    """
    target_lang = (target_lang or "").strip().lower()
    texts = [s["text"] for s in segments]
    if not texts:
        return []
    total = len(texts)

    # Primary: DeepL for NL, EN, PT, ES, ZH, FR, SW (with OpenAI fallback)
    if target_lang in DEEPL_LANGUAGES:
        try:
            return _translate_deepl(texts, target_lang, source_lang, deepl_key, progress_callback, total)
        except Exception as deepl_error:
            # Fallback to OpenAI if available
            if openai_key:
                try:
                    return _translate_openai(texts, target_lang, source_lang, openai_key, progress_callback, total)
                except Exception as openai_error:
                    raise Exception(f"DeepL failed: {deepl_error}. OpenAI fallback also failed: {openai_error}")
            raise Exception(f"DeepL translation failed for {target_lang}: {deepl_error}")

    # Primary: OpenAI for Bantu languages (mg, kg, ts, ln). DeepL does not support these — do not call DeepL.
    if target_lang in OPENAI_LANGUAGES:
        try:
            return _translate_openai(texts, target_lang, source_lang, openai_key, progress_callback, total)
        except Exception as openai_error:
            raise Exception(f"OpenAI translation failed for {target_lang}: {openai_error}")

    raise ValueError(f"No translation API available for language: {target_lang}")


def _deepl_target_language_code(target_lang: str) -> str:
    """
    Map our short codes to DeepL API codes.
    DeepL rejects deprecated bare EN/PT (see Translator._check_valid_languages).
    """
    t = (target_lang or "").strip().lower()
    return {
        "pt": "PT-BR",
        "en": "EN-US",
        "zh": "ZH-HANS",
        "nl": "NL",
        "es": "ES",
        "fr": "FR",
        "sw": "SW",
    }.get(t, (target_lang or "").strip().upper())


def _translate_deepl(
    texts: list[str],
    target_lang: str,
    source_lang: str,
    api_key: str,
    progress_callback=None,
    total: int = 0,
) -> list[str]:
    """DeepL: NL, EN, PT, ES, ZH, FR, SW. Use DeepL API language codes."""
    if not api_key:
        raise ValueError("DeepL API key is required but not provided")

    try:
        dl_target = _deepl_target_language_code(target_lang)
        translator = deepl.Translator(api_key)
        out: list[str] = []
        for i, t in enumerate(texts):
            if not t.strip():
                out.append(t)
            else:
                # Check cache first
                cached = _get_cached_translation(t, target_lang, source_lang)
                if cached is not None:
                    out.append(cached)
                else:
                    r = translator.translate_text(t, target_lang=dl_target, source_lang=source_lang.upper() if source_lang else None)
                    translated = r.text
                    out.append(translated)
                    # Cache the result
                    _cache_translation(t, target_lang, source_lang, translated)
            if progress_callback and total:
                progress_callback(i + 1, total)
        return out
    except deepl.exceptions.AuthorizationException:
        raise Exception("DeepL API key is invalid")
    except deepl.exceptions.QuotaExceededException:
        raise Exception("DeepL API quota exceeded")
    except Exception as e:
        raise Exception(f"DeepL translation error: {e}")


def _translate_openai(
    texts: list[str],
    target_lang: str,
    source_lang: str,
    api_key: str,
    progress_callback=None,
    total: int = 0,
) -> list[str]:
    """OpenAI: Malgasy, Kikongo, Tshiluba, Lingala, or as fallback for DeepL languages."""
    if not api_key:
        raise ValueError("OpenAI API key is required but not provided")

    lang_names = {
        "nl": "Dutch",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "pt": "Portuguese",
        "zh": "Chinese",
        "mg": "Malagasy",
        "kg": "Kikongo",
        "ts": "Tshiluba",
        "ln": "Lingala",
        "sw": "Swahili",
    }
    target_name = lang_names.get(target_lang, target_lang)
    model = (
        OPENAI_TRANSLATION_MODEL_MG_KG_TS
        if target_lang in OPENAI_STRONG_AFRICAN_LANGS
        else OPENAI_TRANSLATION_MODEL
    )

    fr_unknown = (
        "The source is often French. If you do not know the correct word in "
        f"{target_name}, use the French word from the source as-is—do not invent or guess a fake translation. "
    )
    if target_lang == "kg":
        system_msg = (
            "You are an expert translator into Kikongo (Kituba), for church or spoken subtitles. "
            "Preserve proper names and Scripture references faithfully. "
            "Use natural, clear Kikongo; do not invent a different language. "
            + fr_unknown
            + "Reply with only the translated text, no notes."
        )
    elif target_lang == "mg":
        system_msg = (
            "You are an expert translator into Malagasy for subtitles or spoken church content. "
            "Preserve proper names and Scripture references. "
            + fr_unknown
            + "Reply with only the translation, no explanation."
        )
    elif target_lang == "ts":
        system_msg = (
            "You are an expert translator into Tshiluba for subtitles or spoken church content. "
            "Preserve proper names and Scripture references. "
            + fr_unknown
            + "Reply with only the translation, no explanation."
        )
    else:
        system_msg = f"Translate the following text to {target_name}. Reply only with the translation, no explanation."

    def _sanitize_user_text(s: str) -> str:
        # NUL and lone surrogates break JSON on some paths; strip control chars except common whitespace
        s = s.replace("\x00", "")
        return s

    # After first successful segment for mg/kg/ts, keep using that model (stable + correct cache key).
    strong_locked_model: str | None = None

    try:
        client = OpenAI(api_key=api_key)
        out: list[str] = []
        n = total or len(texts)
        for i, t in enumerate(texts):
            if not t.strip():
                out.append(t)
            else:
                t_safe = _sanitize_user_text(t)
                use_strong = target_lang in OPENAI_STRONG_AFRICAN_LANGS
                eff_model = strong_locked_model if (use_strong and strong_locked_model) else model

                cached = _get_cached_translation(t, target_lang, source_lang, openai_model=eff_model)
                if cached is not None:
                    out.append(cached)
                else:
                    if use_strong and strong_locked_model:
                        try_models = [strong_locked_model]
                    elif use_strong and model not in ("gpt-4o", "gpt-4o-mini"):
                        # Premium model first; step down on quota/model errors (4.1 → 4o)
                        try_models = [model]
                        for fb in ("gpt-4.1", "gpt-4o"):
                            if fb != model and fb not in try_models:
                                try_models.append(fb)
                    else:
                        try_models = [model]

                    last_err: Exception | None = None
                    translated: str | None = None
                    used_model: str | None = None
                    for try_m in try_models:
                        try:
                            resp = client.chat.completions.create(
                                model=try_m,
                                messages=[
                                    {"role": "system", "content": system_msg},
                                    {"role": "user", "content": t_safe},
                                ],
                            )
                            raw = (resp.choices[0].message.content or "").strip()
                            if not raw and t.strip():
                                raise Exception(
                                    "Empty reply from OpenAI (check API access and model name)."
                                )
                            translated = raw
                            used_model = try_m
                            break
                        except Exception as ex:
                            last_err = ex
                    if translated is None or used_model is None:
                        raise Exception(f"OpenAI translation error: {last_err}") from last_err
                    if use_strong:
                        strong_locked_model = used_model
                    out.append(translated)
                    _cache_translation(
                        t, target_lang, source_lang, translated, openai_model=used_model
                    )
            if progress_callback and n:
                progress_callback(i + 1, n)
        return out
    except Exception as e:
        raise Exception(f"OpenAI translation error: {e}")
