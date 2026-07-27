"""One-off patch for backend/main.py cinema endpoints."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

# 1) Replace get_cinema_videos
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

# 2) Replace watch endpoint - from @app.get("/api/cinema/watch to return HTMLResponse
old2_start = t.find('@app.get("/api/cinema/watch/{video_id}")')
if old2_start < 0:
    raise SystemExit("watch start not found")
old2_end = t.find("return HTMLResponse(content=html_content)", old2_start)
if old2_end < 0:
    raise SystemExit("watch end not found")
old2_end = t.find("\n", old2_end) + 1

# Find full function - read until next @app
next_app = t.find("\n@app.", old2_start + 1)
block = t[old2_start:next_app]

new_watch = '''@app.get("/api/cinema/watch/{video_id}")
async def watch_video_with_subtitles(video_id: str, lang: str = "nl"):
    """
    Stream a video with optional subtitles for Cinema.
    Returns HTML page with video player.
    """
    video_result = library.get_file(video_id)
    if not video_result:
        raise HTTPException(404, "Video not found")

    video_data, video_name = video_result
    finfo = library.get_file_entry(video_id) or {}
    display_title = (finfo.get("cinema_title") or "").strip() or video_name

    subs = finfo.get("cinema_subtitles") or {}
    vtt_url = None
    if lang and lang != "none" and lang in subs:
        vtt_url = f"/api/library/file/{subs[lang]}"

    # Fallback: filename pattern matching (legacy)
    if not vtt_url:
        all_items = library.list_folder("")["files"]
        video_base = video_name.rsplit(".", 1)[0]
        for item in all_items:
            if item["name"].lower().endswith(".vtt"):
                vtt_base = item["name"].rsplit(".", 1)[0]
                if video_base in vtt_base and f"_{lang}" in vtt_base:
                    vtt_url = f"/api/library/file/{item['id']}"
                    break

    lang_options = sorted(subs.keys()) if subs else ["nl", "en", "pt", "es", "zh"]
    sel_html = ""
    for code in lang_options:
        if not code:
            continue
        nm = config.TARGET_LANGUAGES.get(code, code.upper())
        sel = " selected" if code == lang and vtt_url else ""
        sel_html += f'<option value="{code}"{sel}>{nm}</option>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cinema - {display_title}</title>
        <style>
            body {{
                margin: 0;
                padding: 20px;
                background: #000;
                color: #fff;
                font-family: Arial, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .container {{
                max-width: 1200px;
                width: 100%;
            }}
            h1 {{
                text-align: center;
                margin-bottom: 20px;
                font-size: 1.5rem;
            }}
            video {{
                width: 100%;
                max-height: 70vh;
                background: #000;
            }}
            .controls {{
                margin-top: 20px;
                display: flex;
                gap: 20px;
                align-items: center;
                justify-content: center;
                flex-wrap: wrap;
            }}
            .lang-selector {{
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            select {{
                padding: 8px 12px;
                background: #333;
                color: #fff;
                border: 1px solid #666;
                border-radius: 4px;
            }}
            .back-btn {{
                padding: 10px 20px;
                background: #666;
                color: #fff;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                text-decoration: none;
            }}
            .back-btn:hover {{
                background: #777;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{display_title}</h1>
            <video id="videoPlayer" controls>
                <source src="/api/library/file/{video_id}" type="video/mp4">
                {"<track src='" + vtt_url + "' kind='subtitles' srclang='" + lang + "' label='" + config.TARGET_LANGUAGES.get(lang, lang.upper()) + "' default>" if vtt_url else ""}
                Your browser does not support the video tag.
            </video>
            <div class="controls">
                <div class="lang-selector">
                    <label>Subtitles:</label>
                    <select id="langSelect" onchange="changeLanguage()">
                        <option value="none" {"selected" if not vtt_url else ""}>None</option>
                        {sel_html}
                    </select>
                </div>
                <a href="/cinema" class="back-btn">← Back to Cinema</a>
            </div>
        </div>
        <script>
            function changeLanguage() {{
                const lang = document.getElementById('langSelect').value;
                if (lang === 'none') {{
                    window.location.href = `/api/cinema/watch/{video_id}`;
                }} else {{
                    window.location.href = `/api/cinema/watch/{video_id}?lang=${{lang}}`;
                }}
            }}
        </script>
    </body>
    </html>
    """

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)

'''

if old2_start < 0:
    raise SystemExit("bad")
t = t[:old2_start] + new_watch + t[next_app:]

# 3) Replace POST cinema + add GET before LIBRARY API section
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
    """Serve generated/uploaded Cinema cover image (requires auth like other /api)."""
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

    # Validate VTT ids
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
print("patched main.py")
