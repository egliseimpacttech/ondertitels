from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
t = p.read_text(encoding="utf-8")
old = """      const q = new URLSearchParams();
      q.set('lang', langCode && langCode !== 'none' ? langCode : 'nl');
      q.set('token', tok);"""
new = """      const q = new URLSearchParams();
      if (langCode === 'none') q.set('lang', 'none');
      else q.set('lang', langCode || 'nl');
      q.set('token', tok);"""
if old not in t:
    raise SystemExit("not found")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("ok")
