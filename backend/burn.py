#ondertitels in videos branden met FFmpeg
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Callable

from . import config
from .vtt_parser import parse_vtt


def _format_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h = total_ms // 3_600_000
    total_ms %= 3_600_000
    m = total_ms // 60_000
    total_ms %= 60_000
    s = total_ms // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


#srt is hetgene wat in de video gabrand wordt per miliseconde
def vtt_to_srt(vtt_path: Path, srt_path: Path | None = None) -> Path:
    segments: List[Dict[str, Any]] = parse_vtt(vtt_path)
    if srt_path is None:
        srt_path = vtt_path.with_suffix(".srt")
    lines: List[str] = []
    for i, seg in enumerate(segments, 1):
        start = float(seg.get("start", 0) or 0)
        end = float(seg.get("end", start + 2) or start + 2)
        text = (seg.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
        lines.append(text)
        lines.append("")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return srt_path


def burn_subtitles_into_video(
    video_path: Path,
    vtt_path: Path,
    output_path: Path,
    timeout: int = 3600,
    progress_callback: Callable[[float], None] | None = None,
    video_preset: str = "veryfast",
) -> None:
    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    srt_name = "burn_subs.srt"
    srt_path = out_dir / srt_name
    vtt_to_srt(vtt_path, srt_path)

    # hier moet je het relatieve pad gebruiken dus geen C: of backslashes in filter (vermijdt Windows escape problemen)
    filter_arg = f"subtitles={srt_name}"

    duration_seconds = None
    #hier ben ik helemaal vergeten hoe ik dit heb gedaan en waarom but it works (:
    try:
        probe_cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path.resolve()),
        ]
        probe_result = subprocess.run(
            probe_cmd,
            capture_output=True,
            timeout=min(timeout, 30),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if probe_result.returncode == 0:
            parsed = (probe_result.stdout or "").strip()
            if parsed:
                duration_seconds = float(parsed)
    except Exception:
        duration_seconds = None

    preset = (video_preset or "veryfast").strip().lower()
    if preset not in {"veryfast", "ultrafast"}:
        preset = "veryfast"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        "-vf", filter_arg,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:2",
        "-nostats",
        str(output_path.resolve()),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(out_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stderr_lines: list[str] = []
    try:
        if proc.stderr is not None:
            for line in proc.stderr:
                ln = (line or "").strip()
                if not ln:
                    continue
                stderr_lines.append(ln)
                if progress_callback and duration_seconds and ln.startswith("out_time_ms="):
                    try:
                        out_ms = int(ln.split("=", 1)[1])
                        progress_callback(max(0.0, min(1.0, (out_ms / 1_000_000.0) / duration_seconds)))
                    except Exception:
                        pass
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("FFmpeg timed out while burning subtitles.")

    if proc.returncode != 0:
        # Show last lines of stderr (real error), not the version banner
        err = "\n".join(stderr_lines).strip()
        if err:
            lines = err.split("\n")
            err = "\n".join(lines[-8:])  # last 8 lines
        raise RuntimeError(err or f"FFmpeg exited with code {proc.returncode}")

    try:
        srt_path.unlink(missing_ok=True)
    except OSError:
        pass

#je kan dit ook optioneel maken , het is gewoon omdat het anders veel te lang zou duren 
#het probleem is dat ik niet weet of de volgorde het nuttig maakt
def convert_video_to_720p(
    video_path: Path,
    output_path: Path,
    timeout: int = 7200,
) -> None:
    """
    Convert video to 720p MP4 (H.264 + AAC). Writes result to output_path.
    Raises on failure.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        "-vf", "scale=-2:720",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_path.resolve()),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        if err:
            lines = err.split("\n")
            err = "\n".join(lines[-8:])
        raise RuntimeError(err or f"FFmpeg exited with code {result.returncode}")

#This one doesn't work en ik weet niet goed waarom (zou handig zijn voor pds)
def convert_youtube_url_to_mp4(
    youtube_url: str,
    output_path: Path,
    timeout: int = 7200,
) -> Path:
    
    url = (youtube_url or "").strip()
    if not url:
        raise ValueError("youtube_url is required.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    out_suffix = output_path.suffix.lower()
    if out_suffix not in {".mp4", ".mp3"}:
        raise ValueError("Output file must end with .mp4 or .mp3.")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--retries", "3",
        "--sleep-requests", "1",
        "--output", str(output_path.resolve()),
    ]
    if out_suffix == ".mp3":
        cmd.extend([
            "--format", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
        ])
    else:
        cmd.extend([
            "--format", "bv*+ba/b",
            "--merge-output-format", "mp4",
        ])
    if config.YTDLP_EXTRACTOR_ARGS:
        cmd.extend(["--extractor-args", config.YTDLP_EXTRACTOR_ARGS])
    cookie_file = (config.YTDLP_COOKIES_FILE or "").strip()
    if cookie_file and Path(cookie_file).exists():
        cmd.extend(["--cookies", cookie_file])
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "yt-dlp is not installed on the server. Install yt-dlp to enable YouTube conversion."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("YouTube download/conversion timed out.") from e

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        low = err.lower()
        if "sign in to confirm you’re not a bot" in low or "sign in to confirm you're not a bot" in low:
            raise RuntimeError(
                "YouTube blocked this Cloud Run request (anti-bot). "
                "Configure YTDLP_COOKIES_FILE with a valid exported YouTube cookies.txt secret on Cloud Run."
            )
        if err:
            lines = err.split("\n")
            err = "\n".join(lines[-10:])
        raise RuntimeError(err or f"yt-dlp exited with code {result.returncode}")

    if not output_path.exists():
        raise RuntimeError(f"YouTube conversion finished but no {out_suffix} file was created.")

    return output_path
