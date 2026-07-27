from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

t = t.replace(
    'object_name = f"uploads/{uuid.uuid4()}{suffix}"',
    'object_name = f"library/files/upload_{uuid.uuid4()}{suffix}"',
)

p.write_text(t, encoding="utf-8")
print("ok")
