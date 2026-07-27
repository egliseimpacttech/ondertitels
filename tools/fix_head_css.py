"""Normalize index.html <head>: remove broken empty <style>, ensure /design.css link."""
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
p = root / "frontend" / "index.html"
t = p.read_text(encoding="utf-8")

# Remove broken empty embed block (any variant)
t = re.sub(
    r"\s*<!-- Must be root-absolute[^>]*-->\s*<style>[\s\S]*?</style>\s*",
    "\n",
    t,
    count=1,
)

# Single absolute stylesheet link (not relative — breaks on /cinema etc.)
if 'href="/design.css"' not in t:
    t = re.sub(
        r'<link rel="stylesheet" href="[^"]*design\.css"[^>]*>\s*',
        '  <link rel="stylesheet" href="/design.css">\n',
        t,
        count=1,
    )
if 'href="/design.css"' not in t:
    t = t.replace(
        '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&display=swap" rel="stylesheet">',
        '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&display=swap" rel="stylesheet">\n'
        '  <link rel="stylesheet" href="/design.css">',
        1,
    )

p.write_text(t, encoding="utf-8")
print("head fixed:", p)
