from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")
needle = """        raise HTTPException(500, "Failed to load cinema videos")


@app.post("/api/library/file/{file_id}/link-vtt")"""
insert = """        raise HTTPException(500, "Failed to load cinema videos")


@app.get("/api/cinema/video/{video_id}")
async def stream_cinema_video(video_id: str):
    \"\"\"Stream a published Cinema video (use ?token= in browser media tags).\"\"\"
    if not _cinema_video_is_public(video_id):
        raise HTTPException(404, "Video not found")
    result = library.get_file_path(video_id)
    if not result:
        raise HTTPException(404, "Video not found")
    file_path, filename = result
    suffix = Path(filename).suffix.lower()
    media_type = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(suffix, "application/octet-stream")
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/cinema/vtt/{vtt_id}")
async def stream_cinema_vtt(vtt_id: str):
    \"\"\"Serve a VTT linked to a published Cinema video.\"\"\"
    if not _cinema_vtt_allowed(vtt_id):
        raise HTTPException(404, "Subtitles not found")
    result = library.get_file_path(vtt_id)
    if not result:
        raise HTTPException(404, "Subtitles not found")
    file_path, filename = result
    if not filename.lower().endswith(".vtt"):
        raise HTTPException(400, "Not a VTT file")
    return FileResponse(
        path=file_path,
        media_type="text/vtt",
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.post("/api/library/file/{file_id}/link-vtt")"""
if needle not in t:
    raise SystemExit("needle not found")
p.write_text(t.replace(needle, insert, 1), encoding="utf-8")
print("ok")
