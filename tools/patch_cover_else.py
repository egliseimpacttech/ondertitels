from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")
old = """            else:
                raise HTTPException(400, "Upload a cover image or choose frame mode.")"""
new = """            elif _cinema_cover_jpg_path(file_id).exists():
                pass
            else:
                raise HTTPException(400, "Upload a cover image or choose frame mode.")"""
if old not in t:
    raise SystemExit("pattern not found")
# only replace first occurrence in cinema block
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("ok")
