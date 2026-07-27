from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

t = t.replace(
    "from fastapi.responses import FileResponse, HTMLResponse",
    "from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse",
)

needle = """def _get_gcs_bucket():
    if not (config.GCS_BUCKET_NAME or "").strip():
        raise HTTPException(500, "GCS_BUCKET_NAME is not set on the server.")
    return storage.Client().bucket(config.GCS_BUCKET_NAME)


def _run_transcription_step(job_id: str, upload_path: Path, on_progress) -> list[dict] | None:
"""

insert = """def _get_gcs_bucket():
    if not (config.GCS_BUCKET_NAME or "").strip():
        raise HTTPException(500, "GCS_BUCKET_NAME is not set on the server.")
    return storage.Client().bucket(config.GCS_BUCKET_NAME)


def _signed_gcs_get_url(blob_name: str, expires_seconds: int = 1800) -> str:
    \"\"\"Generate temporary signed GET URL for streaming files directly from GCS.\"\"\"
    bucket = _get_gcs_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        raise HTTPException(404, "File not found")
    try:
        return blob.generate_signed_url(
            version="v4",
            expiration=expires_seconds,
            method="GET",
        )
    except Exception as e:
        msg = str(e).lower()
        if "private key" not in msg and "contains a token" not in msg and "sign" not in msg:
            raise
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(GoogleAuthRequest())
        sa_email = _metadata_service_account_email()
        if not sa_email:
            raise HTTPException(500, "Could not sign GCS URL: missing service account email.")
        return blob.generate_signed_url(
            version="v4",
            expiration=expires_seconds,
            method="GET",
            access_token=creds.token,
            service_account_email=sa_email,
        )


def _run_transcription_step(job_id: str, upload_path: Path, on_progress) -> list[dict] | None:
"""
if needle not in t:
    raise SystemExit("helper insertion point not found")
t = t.replace(needle, insert, 1)

old_video = """@app.get("/api/cinema/video/{video_id}")
async def stream_cinema_video(video_id: str):
    \"\"\"Stream a published Cinema video (works for cinema-only accounts; use ?token= in browser media tags).\"\"\"
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
"""

new_video = """@app.get("/api/cinema/video/{video_id}")
async def stream_cinema_video(video_id: str):
    \"\"\"Stream a published Cinema video. Uses direct GCS signed URL when bucket is configured.\"\"\"
    if not _cinema_video_is_public(video_id):
        raise HTTPException(404, "Video not found")
    if (config.GCS_BUCKET_NAME or "").strip():
        url = _signed_gcs_get_url(f"library/files/{video_id}", expires_seconds=1800)
        return RedirectResponse(url=url, status_code=307)
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
"""
if old_video not in t:
    raise SystemExit("cinema video block not found")
t = t.replace(old_video, new_video, 1)

old_vtt = """@app.get("/api/cinema/vtt/{vtt_id}")
async def stream_cinema_vtt(vtt_id: str):
    \"\"\"Serve a VTT that is linked to a published Cinema video.\"\"\"
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
"""
new_vtt = """@app.get("/api/cinema/vtt/{vtt_id}")
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
if old_vtt not in t:
    raise SystemExit("cinema vtt block not found")
t = t.replace(old_vtt, new_vtt, 1)

p.write_text(t, encoding="utf-8")
print("ok")
