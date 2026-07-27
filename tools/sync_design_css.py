"""One-shot: copy frontend/design.css -> static/design.css for local dev. Docker also copies in Dockerfile."""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = root / "frontend" / "design.css"
dst = root / "static" / "design.css"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_bytes(src.read_bytes())
print("Wrote", dst, dst.stat().st_size, "bytes")
