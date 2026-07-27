"""Generate WebVTT subtitle file: multi-language lines (stacked)."""
from pathlib import Path
from typing import Dict, List


def _format_vtt_time(seconds: float) -> str:
    """Convert seconds to WebVTT time: HH:MM:SS.mmm"""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h = total_ms // 3_600_000
    total_ms %= 3_600_000
    m = total_ms // 60_000
    total_ms %= 60_000
    s = total_ms // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def generate_vtt(
    segments: List[dict],
    translations: Dict[str, List[str]],
    output_path: Path,
) -> None:
    """
    Write WebVTT file with one cue per segment.
    Each cue shows all selected languages as stacked lines (one per language).
    translations: { "nl": ["line1", "line2", ...], "en": [...], ... }
    """
    lang_order = [lang for lang in translations if translations[lang]]

    lines: List[str] = ["WEBVTT", ""]

    for i, seg in enumerate(segments):
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", start + 2.0) or (start + 2.0))

        # Zorg dat de vorige cue zichtbaar blijft tot de volgende cue start,
        # zonder overlap (anders kan de player de volgende start "verschuiven").
        SAFETY_GAP = 0.02  # 20ms buffer t.o.v. volgende cue
        if i < len(segments) - 1:
            next_start = float(segments[i + 1].get("start", end) or end)
            end = max(start, next_start - SAFETY_GAP)
        else:
            # Laat de laatste cue een klein beetje langer staan
            end = end + 0.3

        start_str = _format_vtt_time(start)
        end_str = _format_vtt_time(end)

        # Build text: one line per language in lang_order
        text_lines: List[str] = []
        for lang in lang_order:
            texts = translations.get(lang, [])
            text = texts[i] if i < len(texts) else ""
            text = (text or "").strip()
            if text:
                text_lines.append(text)

        if not text_lines:
            orig = (seg.get("text") or "").strip()
            if orig:
                text_lines.append(orig)

        if not text_lines:
            continue

        lines.append(f"{start_str} --> {end_str}")
        lines.extend(text_lines)
        lines.append("")  # blank line between cues

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")

