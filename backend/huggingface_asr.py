"""Hugging Face Inference API helpers for live ASR."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("ondertitels.huggingface")

# Fast multilingual Whisper on HF Inference Providers / serverless
DEFAULT_ASR_MODEL = "openai/whisper-large-v3-turbo"


def hf_transcribe_file(
    file_path: Path,
    token: str,
    *,
    model: str | None = None,
    language: str | None = None,
) -> str:
    """
    Transcribe a short audio chunk via Hugging Face InferenceClient ASR.
    Requires a token with Inference Providers permission (hf_…).
    """
    tok = (token or "").strip()
    if not tok:
        raise ValueError("HUGGINGFACE_API_TOKEN / HF_TOKEN is not set.")

    try:
        from huggingface_hub import InferenceClient
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is not installed. Run: pip install huggingface_hub"
        ) from e

    model_id = (model or DEFAULT_ASR_MODEL).strip() or DEFAULT_ASR_MODEL
    client = InferenceClient(token=tok)

    extra_body: dict[str, Any] | None = None
    lang = (language or "").strip().lower()
    if lang and lang != "auto":
        # Best-effort: some providers forward Whisper generate_kwargs
        extra_body = {
            "parameters": {
                "generate_kwargs": {
                    "language": lang,
                    "task": "transcribe",
                }
            }
        }

    try:
        if extra_body:
            result = client.automatic_speech_recognition(
                str(file_path),
                model=model_id,
                extra_body=extra_body,
            )
        else:
            result = client.automatic_speech_recognition(str(file_path), model=model_id)
    except Exception as first_err:
        # Retry without extra_body (router ASR schema is strict on some providers)
        if extra_body:
            logger.info("HF ASR retry without language kwargs: %s", first_err)
            result = client.automatic_speech_recognition(str(file_path), model=model_id)
        else:
            raise

    if result is None:
        return ""
    text = getattr(result, "text", None)
    if text:
        return str(text).strip()
    if isinstance(result, dict):
        return str(result.get("text") or "").strip()
    if isinstance(result, str):
        return result.strip()
    return str(result).strip()
