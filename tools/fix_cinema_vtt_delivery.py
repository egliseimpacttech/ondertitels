from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

old_fn = """@app.get("/api/cinema/vtt/{vtt_id}")
async def stream_cinema_vtt(vtt_id: str):
    \"\"\"Serve a VTT linked to a published Cinema video.\"\"\"
    if not _cinema_vtt_allowed(vtt_id):
        raise HTTPException(404, "Subtitles not found")
    if (config.GCS_BUCKET_NAME or "").strip():
        url = _signed_gcs_get_url(f"library/files/{vtt_id}", expires_seconds=1800)
        return RedirectResponse(url=url, status_code=307)
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
"""

new_fn = """@app.get("/api/cinema/vtt/{vtt_id}")
async def stream_cinema_vtt(vtt_id: str):
    \"\"\"Serve a VTT linked to a published Cinema video.\"\"\"
    if not _cinema_vtt_allowed(vtt_id):
        raise HTTPException(404, "Subtitles not found")
    result = library.get_file(vtt_id)
    if not result:
        raise HTTPException(404, "Subtitles not found")
    data, filename = result
    if not filename.lower().endswith(".vtt"):
        raise HTTPException(400, "Not a VTT file")
    return PlainTextResponse(data.decode("utf-8", errors="replace"), media_type="text/vtt")
"""

if old_fn not in t:
    raise SystemExit("vtt function block not found")
t = t.replace(old_fn, new_fn, 1)

t = t.replace("kind='subtitles'", "kind='captions'")

p.write_text(t, encoding="utf-8")
print("ok")
