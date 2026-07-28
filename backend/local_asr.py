"""Local offline ASR via faster-whisper (no API costs)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("ondertitels.local_asr")

_model = None
_model_lock = threading.Lock()
_model_name: str | None = None


def local_asr_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _get_whisper_model(model_size: str, device: str, compute_type: str):
    global _model, _model_name
    key = f"{model_size}|{device}|{compute_type}"
    with _model_lock:
        if _model is not None and _model_name == key:
            return _model
        from faster_whisper import WhisperModel

        logger.info(
            "Loading faster-whisper model=%s device=%s compute_type=%s (first load can take a while)",
            model_size,
            device,
            compute_type,
        )
        _model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _model_name = key
        return _model


def warm_local_asr(
    *,
    model_size: str = "base",
    device: str = "auto",
    compute_type: str = "default",
) -> None:
    """Load model into memory so the first live chunk is not cold-start."""
    if not local_asr_available():
        return
    dev = (device or "auto").strip().lower()
    ctype = (compute_type or "default").strip().lower()
    if dev == "auto":
        dev = "cpu"
    if ctype == "default":
        ctype = "int8" if dev == "cpu" else "float16"
    _get_whisper_model(model_size, dev, ctype)


def local_transcribe_file(
    file_path: Path,
    *,
    model_size: str = "base",
    device: str = "auto",
    compute_type: str = "default",
    language: str | None = None,
    with_timestamps: bool = False,
    vad_filter: bool = False,
) -> list[dict[str, Any]] | str:
    """
    Transcribe with faster-whisper.
    Returns plain text when with_timestamps=False, else list of {start,end,text}.

    vad_filter defaults False: short live mic chunks are often wiped entirely by VAD.
    """
    if not local_asr_available():
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        )

    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    # Resolve device/compute defaults for CPU-friendly Macs
    dev = (device or "auto").strip().lower()
    ctype = (compute_type or "default").strip().lower()
    if dev == "auto":
        # Prefer CPU on most laptops; CUDA if explicitly available later
        dev = "cpu"
    if ctype == "default":
        ctype = "int8" if dev == "cpu" else "float16"

    model = _get_whisper_model(model_size, dev, ctype)
    lang = (language or "").strip().lower()
    if lang in ("", "auto"):
        lang = None

    segments_iter, _info = model.transcribe(
        str(path),
        language=lang,
        vad_filter=bool(vad_filter),
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        without_timestamps=not with_timestamps,
    )

    segments: list[dict[str, Any]] = []
    parts: list[str] = []
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        parts.append(text)
        segments.append(
            {
                "start": float(getattr(seg, "start", 0.0) or 0.0),
                "end": float(getattr(seg, "end", 0.0) or 0.0),
                "text": text,
            }
        )

    if with_timestamps:
        return segments
    return " ".join(parts).strip()
