"""Replace watch_video_with_subtitles in backend/main.py."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

start = '@app.get("/api/cinema/watch/{video_id}")'
end = '\n@app.post("/api/admin/invite")'
if start not in t or end not in t.split(start, 1)[1]:
    raise SystemExit("markers not found")

head, tail = t.split(start, 1)
_, tail = tail.split(end, 1)

new_fn = r'''@app.get("/api/cinema/watch/{video_id}")
async def watch_video_with_subtitles(request: Request, video_id: str, lang: str = "nl"):
    """
    Cinema HTML player. Pass ?token=<Firebase idToken> so <video>/<track> can load (?token= on media URLs).
    """
    video_result = library.get_file(video_id)
    if not video_result:
        raise HTTPException(404, "Video not found")

    video_data, video_name = video_result
    entry = library.get_file_entry(video_id) or {}
    if not entry.get("cinema_public"):
        raise HTTPException(404, "Video not found")

    subs = entry.get("cinema_subtitles") or {}
    token = (request.query_params.get("token") or "").strip()
    token_q = "&token=" + quote(token, safe="") if token else ""

    vtt_id = None
    eff_lang = lang
    if lang == "none":
        vtt_id = None
    elif subs:
        vtt_id = subs.get(lang)
        if vtt_id is None:
            eff_lang = next(iter(subs.keys()))
            vtt_id = subs.get(eff_lang)

    video_src = f"/api/cinema/video/{video_id}"
    if token:
        video_src += "?token=" + quote(token, safe="")

    vtt_url = ""
    if vtt_id and token and lang != "none":
        vtt_url = f"/api/cinema/vtt/{vtt_id}?token=" + quote(token, safe="")

    title_display = html.escape((entry.get("cinema_title") or "").strip() or video_name)

    if subs:
        opt_none_sel = " selected" if (lang == "none" or not vtt_id) else ""
        parts = [f'<option value="none"{opt_none_sel}>None</option>']
        for code in subs.keys():
            sel = " selected" if (code == eff_lang and lang != "none" and vtt_id) else ""
            label = html.escape(config.TARGET_LANGUAGES.get(code, code.upper()))
            parts.append(f'<option value="{html.escape(code)}"{sel}>{label}</option>')
        options_html = "".join(parts)
    else:
        options_html = '<option value="none" selected>No subtitles linked</option>'

    track_html = ""
    if vtt_url and eff_lang and lang != "none":
        lbl = html.escape(config.TARGET_LANGUAGES.get(eff_lang, eff_lang.upper()))
        track_html = (
            f"<track src='{vtt_url}' kind='subtitles' srclang='{html.escape(eff_lang)}' "
            f"label='{lbl}' default>"
        )

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cinema - {title_display}</title>
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
            <h1>{title_display}</h1>
            <video id="videoPlayer" controls>
                <source src="{video_src}" type="video/mp4">
                {track_html}
                Your browser does not support the video tag.
            </video>
            <div class="controls">
                <div class="lang-selector">
                    <label>Subtitles:</label>
                    <select id="langSelect" onchange="changeLanguage()">
                        {options_html}
                    </select>
                </div>
                <a href="/cinema" class="back-btn">← Back to Cinema</a>
            </div>
        </div>
        <script>
            function changeLanguage() {{
                const lang = document.getElementById('langSelect').value;
                window.location.href = `/api/cinema/watch/{video_id}?lang=${{lang}}{token_q}`;
            }}
        </script>
    </body>
    </html>
    """

    return HTMLResponse(content=html_content)

'''

p.write_text(head + new_fn + end + tail, encoding="utf-8")
print("ok replace watch")
