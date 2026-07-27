"""Parse WebVTT files back into segments for translation."""
import re
from pathlib import Path
from typing import List, Dict, Any


def parse_vtt(vtt_path: Path) -> List[Dict[str, Any]]:
    """
    Parse a VTT file and return list of segments:
    [{"start": float, "end": float, "text": str}, ...]
    """
    content = vtt_path.read_text(encoding="utf-8")
    segments: List[Dict[str, Any]] = []

    # Split into cue blocks (separated by blank lines)
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue

        # Skip WEBVTT header
        if lines[0].startswith("WEBVTT"):
            continue

        # Find the timing line (contains "-->")
        timing_line = None
        timing_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                timing_line = line
                timing_idx = i
                break

        if not timing_line:
            continue

        # Parse timing: 00:00:01.000 --> 00:00:05.000
        match = re.match(
            r"(\d{1,2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}\.\d{3})",
            timing_line.strip(),
        )
        if not match:
            # Try without hours: 00:01.000 --> 00:05.000
            match = re.match(
                r"(\d{1,2}:\d{2}\.\d{3})\s*-->\s*(\d{1,2}:\d{2}\.\d{3})",
                timing_line.strip(),
            )
        if not match:
            continue

        start_str, end_str = match.groups()
        start = _vtt_time_to_seconds(start_str)
        end = _vtt_time_to_seconds(end_str)

        # Text is everything after the timing line
        text_lines = lines[timing_idx + 1 :]
        text = "\n".join(text_lines).strip()

        if text:
            segments.append({"start": start, "end": end, "text": text})

    return segments


def _vtt_time_to_seconds(time_str: str) -> float:
    """Convert VTT time (HH:MM:SS.mmm or MM:SS.mmm) to seconds."""
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return 0.0
