"""Patch backend/main.py: get_cinema_videos + cinema POST/GET/cover only."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

old1 = '''@app.get("/api/cinema/videos")
async def get_cinema_videos():
    """
    Get all public videos available in Cinema.
    Returns videos with their linked subtitle options.
    """
    try:
        all_items = library.list_folder("")["files"]
        videos = []

        for item in all_items:
            if item["name"].lower().endswith((".mp4", ".webm", ".mkv")):
                # Only include videos that were explicitly published to Cinema.
                if not item.get("cinema_public"):
                    continue
                # Check if this video has linked VTT files
                video_base = item["name"].rsplit(".", 1)[0]  # Remove extension
                linked_vtts = []

                # Look for VTT files with matching base name
                for vtt_item in all_items:
                    if vtt_item["name"].lower().endswith(".vtt"):
                        vtt_base = vtt_item["name"].rsplit(".", 1)[0]
                        # Check if VTT filename contains video base name
                        if video_base in vtt_base:
                            # Try to extract language from filename (e.g., "video_nl.vtt" -> "nl")
                            lang_part = vtt_base.replace(video_base, "").strip("_")
                            if lang_part and len(lang_part) <= 3:  # Likely a language code
                                lang_name = config.TARGET_LANGUAGES.get(lang_part, lang_part.upper())
                                linked_vtts.append({
                                    "id": vtt_item["id"],
                                    "language": lang_part,
                                    "language_name": lang_name
                                })

                videos.append({
                    "id": item["id"],
                    "name": item["name"],
                    "size": item["size"],
                    "languages": [
                        {"code": vtt["language"], "name": vtt["language_name"]}
                        for vtt in linked_vtts
                    ]
                })

        return {"videos": videos}
    except Exception as e:
        logger.error(f"Failed to get cinema videos: {e}")
        raise HTTPException(500, "Failed to load cinema videos")'''

new1 = '''@app.get("/api/cinema/videos")
async def get_cinema_videos():
    """
    Get all public videos available in Cinema (metadata from library index).
    """
    try:
        index = library._load_index()
        videos = []
        for file_id, finfo in index.get("files", {}).items():
            if finfo.get("type") != "video":
                continue
            if not finfo.get("cinema_public"):
                continue
            name = finfo.get("name", "")
            if not name.lower().endswith((".mp4", ".webm", ".mkv")):
                continue
            title = (finfo.get("cinema_title") or "").strip() or name
            desc = (finfo.get("cinema_description") or "").strip()
            subs = finfo.get("cinema_subtitles") or {}
            languages = []
            for lang, vtt_id in subs.items():
                languages.append({
                    "code": lang,
                    "name": config.TARGET_LANGUAGES.get(lang, lang.upper()),
                    "vtt_id": vtt_id,
                })
            cover_path = _cinema_cover_jpg_path(file_id)
            has_cover = cover_path.exists()
            videos.append({
                "id": file_id,
                "name": name,
                "title": title,
                "description": desc,
                "size": finfo.get("size", 0),
                "cover_url": f"/api/cinema/cover/{file_id}" if has_cover else None,
                "languages": languages,
            })
        videos.sort(key=lambda x: (x.get("title") or x.get("name") or "").lower())
        return {"videos": videos}
    except Exception as e:
        logger.error(f"Failed to get cinema videos: {e}")
        raise HTTPException(500, "Failed to load cinema videos")'''

if old1 not in t:
    raise SystemExit("get_cinema_videos block not found")
t = t.replace(old1, new1)

old3 = '''@app.post("/api/library/file/{file_id}/cinema")
async def set_library_file_cinema_visibility(
    request: Request,
    file_id: str,
    public: str = Form("true"),
):
    """
    Mark a library file as visible in Cinema.
    Only admins (ADMIN_EMAILS / ALLOWED_EMAILS) can publish/unpublish.
    """
    _require_admin(request)
    is_public = str(public).lower() in ("1", "true", "yes", "on")
    if library.set_cinema_public(file_id, is_public):
        return {"success": True, "cinema_public": is_public}
    raise HTTPException(404, "File not found")'''

new3 = '''@app.get("/api/library/file/{file_id}/cinema")
async def get_library_file_cinema_meta(request: Request, file_id: str):
    """Get Cinema publish metadata for a video (library users)."""
    _require_cinema_publisher(request)
    entry = library.get_file_entry(file_id)
    if not entry or entry.get("type") != "video":
        raise HTTPException(404, "Video not found")
    return {
        "cinema_public": bool(entry.get("cinema_public", False)),
        "cinema_title": entry.get("cinema_title") or "",
        "cinema_description": entry.get("cinema_description") or "",
        "cinema_cover_type": entry.get("cinema_cover_type") or "frame",
        "cinema_cover_second": float(entry.get("cinema_cover_second") or 0),
        "cinema_subtitles": entry.get("cinema_subtitles") or {},
    }


@app.get("/api/cinema/cover/{video_id}")
async def get_cinema_cover(video_id: str):
    """Serve Cinema cover image (requires Authorization like other /api routes)."""
    path = _cinema_cover_jpg_path(video_id)
    if not path.exists():
        raise HTTPException(404, "Cover not found")
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/library/file/{file_id}/cinema")
async def set_library_file_cinema(
    request: Request,
    file_id: str,
    public: str = Form("true"),
    title: str = Form(""),
    description: str = Form(""),
    cover_type: str = Form("frame"),
    cover_second: str = Form("0"),
    subtitles_json: str = Form("{}"),
    cover_file: UploadFile | None = File(None),
):
    """
    Publish or update a video in Cinema. Full library users only (not cinema-only).
    cover_type: frame | upload
    subtitles_json: JSON object mapping language code -> library VTT file id
    """
    _require_cinema_publisher(request)
    entry = library.get_file_entry(file_id)
    if not entry or entry.get("type") != "video":
        raise HTTPException(404, "Video not found")
    video_path, video_name = library.get_file_path(file_id)
    if not video_path:
        raise HTTPException(404, "Video file missing on disk")

    is_public = str(public).lower() in ("1", "true", "yes", "on")
    try:
        subs = json.loads(subtitles_json or "{}")
        if not isinstance(subs, dict):
            raise ValueError("subtitles must be object")
    except Exception as e:
        raise HTTPException(400, f"Invalid subtitles_json: {e}")

    cleaned: dict[str, str] = {}
    for lang, vtt_id in subs.items():
        if not lang or not vtt_id:
            continue
        vtt_entry = library.get_file_entry(str(vtt_id))
        if not vtt_entry or vtt_entry.get("type") != "vtt":
            raise HTTPException(400, f"Invalid VTT for language {lang}")
        cleaned[str(lang).lower().strip()] = str(vtt_id)

    ct = (cover_type or "frame").strip().lower()
    if ct not in ("frame", "upload"):
        ct = "frame"
    try:
        sec = float(cover_second or 0)
    except ValueError:
        sec = 0.0

    title_f = (title or "").strip() or video_name

    if is_public:
        if ct == "frame":
            _extract_cinema_cover_from_video(video_path, file_id, sec)
        else:
            if cover_file and cover_file.filename:
                raw = await cover_file.read()
                if len(raw) > 5 * 1024 * 1024:
                    raise HTTPException(400, "Cover image too large (max 5MB)")
                out = _cinema_cover_jpg_path(file_id)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
            else:
                raise HTTPException(400, "Upload a cover image or choose frame mode.")

    if not library.set_cinema_metadata(
        file_id,
        public=is_public,
        title=title_f,
        description=description or "",
        cover_type=ct,
        cover_second=sec,
        subtitles=cleaned,
    ):
        raise HTTPException(404, "Could not save")

    return {"success": True, "cinema_public": is_public}'''

if old3 not in t:
    raise SystemExit("POST cinema block not found")
t = t.replace(old3, new3)

p.write_text(t, encoding="utf-8")
print("ok patch_cinema_api")
