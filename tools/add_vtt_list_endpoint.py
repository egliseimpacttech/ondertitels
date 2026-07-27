from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")
needle = """        "cinema_subtitles": entry.get("cinema_subtitles") or {},
    }


@app.get("/api/cinema/cover/{video_id}")"""
insert = """        "cinema_subtitles": entry.get("cinema_subtitles") or {},
    }


@app.get("/api/library/vtt-list")
async def list_library_vtt_for_cinema(request: Request):
    \"\"\"All VTT files for Cinema publish dropdowns.\"\"\"
    _require_cinema_publisher(request)
    return {\"items\": library.list_all_vtt_files()}


@app.get("/api/cinema/cover/{video_id}")"""
if needle not in t:
    raise SystemExit("needle not found")
p.write_text(t.replace(needle, insert, 1), encoding="utf-8")
print("ok")
