from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

old = """    video_src = f"/api/cinema/video/{video_id}"
    if token:
        video_src += "?token=" + quote(token, safe="")

    vtt_url = ""
"""

new = """    video_src = f"/api/cinema/video/{video_id}"
    if token:
        video_src += "?token=" + quote(token, safe="")

    video_mime = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(Path(video_name).suffix.lower(), "video/mp4")

    vtt_url = ""
"""

if old not in t:
    raise SystemExit("pattern not found")

p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("ok")
