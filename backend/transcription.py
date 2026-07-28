"""Transcription via ElevenLabs Speech-to-Text (Scribe), optional Voice Isolator preprocessing."""
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Dict

from elevenlabs import ElevenLabs
from openai import OpenAI
from io import BytesIO


def _write_audio_stream_to_file(audio_stream, out_path: Path) -> None:
    """
    ElevenLabs SDK can return bytes, a file-like object, or an iterator of bytes.
    Normalize and write to out_path.
    """
    if audio_stream is None:
        raise ValueError("No audio returned from Voice Isolator.")
    if isinstance(audio_stream, (bytes, bytearray)):
        out_path.write_bytes(bytes(audio_stream))
        return
    if hasattr(audio_stream, "read"):
        out_path.write_bytes(audio_stream.read())
        return
    chunks = bytearray()
    for chunk in audio_stream:
        if chunk:
            chunks.extend(chunk)
    out_path.write_bytes(bytes(chunks))


def _voice_isolate(audio_path: Path, client: ElevenLabs) -> Path:
    """
    Run ElevenLabs Voice Isolator (audio isolation) and return path to isolated audio file.
    Falls back by raising if not supported.
    """
    out_path = Path(tempfile.gettempdir()) / f"{audio_path.stem}_isolated.mp3"
    data = audio_path.read_bytes()
    audio_stream = client.audio_isolation.convert(audio=BytesIO(data))
    _write_audio_stream_to_file(audio_stream, out_path)
    return out_path


def _extract_audio(video_path: Path) -> Path:
    """
    Extract audio from video file using ffmpeg.
    Returns path to temporary MP3 file (much smaller than video).
    """
    temp_audio = Path(tempfile.gettempdir()) / f"{video_path.stem}_audio.mp3"
    
    cmd = [
        "ffmpeg", "-y",  # overwrite output
        "-i", str(video_path),
        "-vn",  # no video
        "-acodec", "libmp3lame",
        "-ab", "128k",  # 128kbps is enough for speech
        "-ar", "44100",  # sample rate
        str(temp_audio)
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=300)
        return temp_audio
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # If ffmpeg fails, return original file
        return video_path


def _segments_from_words(words) -> List[Dict[str, Any]]:
    """
    Group word-level timestamps into smaller segments with timings.
    We split when:
    - er zit een duidelijke stilte tussen woorden (gap),
    - of de tekst te lang wordt,
    - of de duur van het segment te lang wordt.
    """
    # Wat ruimer instellen zodat volledige zinnen vaker in één segment blijven.
    GAP_SECONDS = 0.4        # nieuwe zin/segment bij >0.4s stilte
    MAX_CHARS = 200          # max. tekens per segment
    MAX_DURATION = 10.0      # max. duur (seconden) per segment

    segments: List[Dict[str, Any]] = []
    current_start: float | None = None
    last_end: float | None = None
    current_words: List[str] = []

    for w in words:
        text = getattr(w, "text", None) or getattr(w, "word", "") or ""
        w_type = getattr(w, "type", "word")
        start = getattr(w, "start", None) or getattr(w, "start_time", None)
        end = getattr(w, "end", None) or getattr(w, "end_time", None)

        # Sla spaties / audio_events zonder tijd over
        if start is None or end is None or not text.strip():
            continue

        if current_start is None:
            # eerste woord van een segment
            current_start = float(start)
            last_end = float(end)
            current_words = [text]
            continue

        gap = float(start) - float(last_end or start)
        candidate_text = (" ".join(current_words + [text])).strip()
        duration = float(end) - float(current_start)

        should_split = (
            gap > GAP_SECONDS
            or len(candidate_text) > MAX_CHARS
            or duration > MAX_DURATION
        )

        if should_split:
            # sluit huidig segment af
            if current_words and last_end is not None:
                segments.append(
                    {
                        "start": current_start,
                        "end": float(last_end),
                        "text": " ".join(current_words).strip(),
                    }
                )
            # begin nieuw segment
            current_start = float(start)
            last_end = float(end)
            current_words = [text]
        else:
            current_words.append(text)
            last_end = float(end)

    if current_words and current_start is not None and last_end is not None:
        segments.append(
            {
                "start": current_start,
                "end": float(last_end),
                "text": " ".join(current_words).strip(),
            }
        )

    return segments


def _looks_like_continuation(prev_text: str, next_text: str) -> bool:
    """
    Heuristiek: bepaalt of next_text waarschijnlijk een voortzetting is
    van dezelfde zin als prev_text (en dus samengevoegd mag worden).
    """
    prev = (prev_text or "").strip()
    nxt = (next_text or "").lstrip()
    if not prev or not nxt:
        return False

    # Als vorige eindigt met een sterke zinseinde, niet mergen.
    if prev[-1] in ".?!;:":
        return False

    # Als volgende met hoofdletter begint, is het vaak een nieuwe zin.
    first = nxt[0]
    if first.isalpha() and first == first.upper():
        return False

    # Anders: hoogstwaarschijnlijk een voortzetting.
    return True


def _merge_short_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge neighbouring segments zodat we zoveel mogelijk volledige zinnen
    krijgen in één tijdsinterval. Dit helpt de vertaling (die per segment
    gebeurt) om de volledige zin te zien.
    """
    if not segments:
        return segments

    TOTAL_MAX_CHARS = 260       # totale lengte na merge
    MERGE_MAX_DURATION = 18.0   # totale duur na merge
    MERGE_MAX_GAP = 1.2         # maximaal gat tussen segmenten om te mergen

    merged: List[Dict[str, Any]] = []
    buffer = segments[0].copy()

    for seg in segments[1:]:
        gap = float(seg["start"]) - float(buffer["end"])
        combined_text = (buffer["text"] + " " + seg["text"]).strip()
        combined_duration = float(seg["end"]) - float(buffer["start"])

        should_merge = (
            gap >= 0.0
            and gap <= MERGE_MAX_GAP
            and combined_duration <= MERGE_MAX_DURATION
            and len(combined_text) <= TOTAL_MAX_CHARS
            and _looks_like_continuation(buffer["text"], seg["text"])
        )

        if should_merge:
            buffer["end"] = float(seg["end"])
            buffer["text"] = combined_text
        else:
            merged.append(buffer)
            buffer = seg.copy()

    merged.append(buffer)
    return merged


def _first_punctuation_index(text: str, punct: set) -> int:
    """Index of first character that is in punct, or -1 if none."""
    for idx, c in enumerate(text):
        if c in punct:
            return idx
    return -1


def _merge_by_punctuation(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Als een segment niet eindigt op . , ; : ? !
    neem dan alleen het EERSTE STUKJE van de volgende ondertitel erbij
    dat eindigt op zo'n leesteken. Zo blijft elke cue kort genoeg en
    eindigt wel op leesteken.
    """
    if not segments:
        return segments

    PUNCT = {".", ",", ";", ":", "?", "!"}
    MERGE_MAX_GAP = 2.0
    TOTAL_MAX_CHARS = 280  # redelijke bovengrens per cue

    merged: List[Dict[str, Any]] = []
    i = 0
    n = len(segments)
    # Werk op een kopie zodat we segmenten kunnen "splitsen" (rest terugzetten)
    segs = [s.copy() for s in segments]

    while i < n:
        cur = segs[i]
        text = (cur.get("text") or "").rstrip()

        # Al goed: eindigt op leesteken of dit is het laatste segment
        if (text and text[-1] in PUNCT) or i == n - 1:
            merged.append(cur)
            i += 1
            continue

        # Geen volgend segment
        if i + 1 >= n:
            merged.append(cur)
            i += 1
            continue

        nxt = segs[i + 1]
        nxt_text = (nxt.get("text") or "").lstrip()
        gap = float(nxt["start"]) - float(cur["end"])

        if gap < 0 or gap > MERGE_MAX_GAP:
            merged.append(cur)
            i += 1
            continue

        # Zoek eerste leesteken in de VOLGENDE ondertitel
        idx = _first_punctuation_index(nxt_text, PUNCT)

        if idx >= 0:
            # Alleen dit stukje erbij: tot en met het leesteken
            piece = nxt_text[: idx + 1].rstrip()
            new_text = (text + " " + piece).strip()
            if len(new_text) <= TOTAL_MAX_CHARS:
                cur = cur.copy()
                cur["text"] = new_text
                cur["end"] = float(nxt["end"])  # cue iets langer zichtbaar
                merged.append(cur)
                rest = nxt_text[idx + 1 :].strip()
                if rest:
                    segs[i + 1] = {
                        "start": nxt["start"],
                        "end": nxt["end"],
                        "text": rest,
                    }
                    # Volgende iteratie verwerkt de rest als nieuw segment
                i += 1
                if not rest:
                    i += 1  # volgend segment helemaal verbruikt, skip
            else:
                merged.append(cur)
                i += 1
        else:
            # Volgende segment bevat geen leesteken: hele segment erbij (binnen limiet)
            combined = (text + " " + nxt_text).strip()
            if len(combined) <= TOTAL_MAX_CHARS:
                cur = cur.copy()
                cur["text"] = combined
                cur["end"] = float(nxt["end"])
                merged.append(cur)
                i += 2
            else:
                merged.append(cur)
                i += 1

    return merged


def transcribe_audio_chunk(
    file_path: Path,
    openai_api_key: str,
    *,
    language: str | None = None,
    prompt: str | None = None,
) -> str:
    """
    Fast STT for short live-audio chunks via OpenAI Whisper.
    Returns plain text (no timestamps) for low latency.
    """
    if not (openai_api_key or "").strip():
        raise ValueError("OPENAI_API_KEY is not set for live transcription.")

    client = OpenAI(api_key=openai_api_key.strip())
    kwargs: dict[str, Any] = {
        "model": "whisper-1",
        "response_format": "text",
    }
    lang = (language or "").strip().lower()
    if lang and lang != "auto":
        # Whisper expects ISO-639-1 (fr, nl, en, …)
        kwargs["language"] = lang
    if prompt and prompt.strip():
        kwargs["prompt"] = prompt.strip()[:800]

    with open(file_path, "rb") as f:
        resp = client.audio.transcriptions.create(file=f, **kwargs)

    if isinstance(resp, str):
        return resp.strip()
    text = getattr(resp, "text", None)
    if text:
        return str(text).strip()
    return str(resp or "").strip()


def _openai_transcribe_file(file_path: Path, openai_api_key: str) -> list[dict[str, Any]]:
    """
    Fallback transcription via OpenAI STT (Whisper) returning timestamped segments.
    Uses response_format=verbose_json so we can convert segments to our internal format.
    """
    if not (openai_api_key or '').strip():
        raise ValueError('OPENAI_API_KEY is not set for fallback transcription.')

    client = OpenAI(api_key=openai_api_key.strip())
    with open(file_path, 'rb') as f:
        # whisper-1 supports verbose_json with segments + timestamps
        resp = client.audio.transcriptions.create(
            model='whisper-1',
            file=f,
            response_format='verbose_json',
        )

    segments: list[dict[str, Any]] = []
    # openai-python returns pydantic-like objects; handle dict fallback too
    segs = getattr(resp, 'segments', None)
    if segs is None and isinstance(resp, dict):
        segs = resp.get('segments')

    if segs:
        for s in segs:
            start = getattr(s, 'start', None) if not isinstance(s, dict) else s.get('start')
            end = getattr(s, 'end', None) if not isinstance(s, dict) else s.get('end')
            text = getattr(s, 'text', '') if not isinstance(s, dict) else (s.get('text') or '')
            try:
                segments.append({
                    'start': float(start or 0.0),
                    'end': float(end or 0.0),
                    'text': (text or '').strip(),
                })
            except Exception:
                continue

    if not segments:
        txt = getattr(resp, 'text', None) if not isinstance(resp, dict) else resp.get('text')
        if txt:
            segments.append({'start': 0.0, 'end': 0.0, 'text': str(txt).strip()})

    return segments


def _looks_low_quality_transcript(segments: list[dict[str, Any]]) -> bool:
    """Detect obviously bad STT output (e.g., same line repeated many times)."""
    if not segments:
        return True

    texts = [((s.get("text") or "").strip().lower()) for s in segments if (s.get("text") or "").strip()]
    if not texts:
        return True

    total = len(texts)
    uniq = len(set(texts))

    # Very low diversity in many segments usually means broken transcript quality.
    if total >= 8 and (uniq / max(total, 1)) < 0.2:
        return True

    # Dominant repeated text threshold.
    counts = {}
    for txt in texts:
        counts[txt] = counts.get(txt, 0) + 1
    top = max(counts.values()) if counts else 0
    if total >= 6 and (top / total) >= 0.6:
        return True

    # Extremely short repeated captions are often artifacts.
    avg_len = sum(len(x) for x in texts) / max(total, 1)
    if total >= 8 and avg_len < 24 and uniq <= 2:
        return True

    return False


def _elevenlabs_transcribe_file(
    file_path: Path,
    api_key: str,
    model_id: str = "scribe_v2",
) -> list[dict[str, Any]]:
    """Transcribe via ElevenLabs Scribe; return timestamped segments."""
    if not (api_key or "").strip():
        raise ValueError("ELEVENLABS_API_KEY is not set.")

    client = ElevenLabs(api_key=api_key.strip())
    with open(file_path, "rb") as f:
        try:
            result = client.speech_to_text.convert(
                file=f,
                model_id=model_id,
                timestamps_granularity="word",
            )
        except TypeError:
            result = client.speech_to_text.convert(file=f, model_id=model_id)

    segments: list[dict[str, Any]] = []

    if hasattr(result, "words") and result.words:
        segments = _segments_from_words(result.words)
        segments = _merge_short_segments(segments)
        segments = _merge_by_punctuation(segments)

    if not segments and hasattr(result, "segments"):
        for seg in result.segments:
            segments.append(
                {
                    "start": float(getattr(seg, "start", 0.0) or 0.0),
                    "end": float(getattr(seg, "end", 0.0) or 0.0),
                    "text": (getattr(seg, "text", "") or "").strip(),
                }
            )

    if not segments and hasattr(result, "text") and result.text:
        segments.append({"start": 0.0, "end": 0.0, "text": (result.text or "").strip()})

    return segments


def transcribe_file(
    file_path: Path,
    api_key: str,
    model_id: str = "scribe_v2",
    voice_isolation: bool = False,
    voice_isolation_api_key: str = "",
    openai_api_key: str = "",
) -> list[dict[str, Any]]:
    """
    Transcribe audio/video and return segments with start/end times.

    Order:
      1) Local faster-whisper (if LOCAL_INFERENCE)
      2) OpenAI Whisper
      3) ElevenLabs Scribe (fallback)
    Optional voice isolation still uses ElevenLabs when requested.
    """
    from backend import config

    has_openai = bool((openai_api_key or "").strip())
    has_eleven = bool((api_key or "").strip())
    use_local = bool(getattr(config, "LOCAL_INFERENCE", False))

    if not use_local and not has_openai and not has_eleven:
        raise ValueError(
            "No transcription API key configured. Set OPENAI_API_KEY or ELEVENLABS_API_KEY "
            "(or LOCAL_INFERENCE=true with faster-whisper)."
        )

    actual_file = file_path
    temp_audio = None
    temp_isolated = None
    try:
        if file_path.suffix.lower() == ".mp4":
            temp_audio = _extract_audio(file_path)
            if temp_audio != file_path:
                actual_file = temp_audio

        if voice_isolation and has_eleven:
            try:
                isolation_key = (voice_isolation_api_key or api_key or "").strip()
                isolation_client = ElevenLabs(api_key=isolation_key)
                temp_isolated = _voice_isolate(actual_file, isolation_client)
                actual_file = temp_isolated
            except Exception:
                temp_isolated = None

        errors: list[str] = []

        # 0) Local faster-whisper
        if use_local:
            try:
                from backend.local_asr import local_asr_available, local_transcribe_file

                if local_asr_available():
                    segments = local_transcribe_file(
                        actual_file,
                        model_size=config.LOCAL_WHISPER_MODEL,
                        device=config.LOCAL_WHISPER_DEVICE,
                        compute_type=config.LOCAL_WHISPER_COMPUTE,
                        language=None,
                        with_timestamps=True,
                    )
                    if isinstance(segments, list) and segments and not _looks_low_quality_transcript(segments):
                        return segments
                    if isinstance(segments, list) and segments and not has_openai and not has_eleven:
                        return segments
                    if not segments:
                        errors.append("Local Whisper returned no segments.")
                    else:
                        errors.append("Local Whisper output looked low-quality.")
            except Exception as e:
                errors.append(f"Local Whisper: {e}")

        # 1) Primary cloud: OpenAI Whisper
        if has_openai:
            try:
                segments = _openai_transcribe_file(actual_file, openai_api_key)
                if segments and not _looks_low_quality_transcript(segments):
                    return segments
                if segments and not has_eleven:
                    return segments
                if not segments:
                    errors.append("OpenAI Whisper returned no segments.")
                else:
                    errors.append("OpenAI Whisper output looked low-quality.")
            except Exception as e:
                errors.append(f"OpenAI Whisper: {e}")

        # 2) Fallback: ElevenLabs Scribe
        if has_eleven:
            try:
                segments = _elevenlabs_transcribe_file(actual_file, api_key, model_id=model_id)
                if segments:
                    return segments
                errors.append("ElevenLabs returned no segments.")
            except Exception as e:
                errors.append(f"ElevenLabs: {e}")

        raise RuntimeError(
            "Transcription failed. " + " | ".join(errors) if errors else "Transcription failed."
        )
    finally:
        if temp_audio and temp_audio != file_path and temp_audio.exists():
            try:
                temp_audio.unlink()
            except Exception:
                pass
        if temp_isolated and temp_isolated.exists():
            try:
                temp_isolated.unlink()
            except Exception:
                pass
