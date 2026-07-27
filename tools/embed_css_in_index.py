
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
css_path = root / "frontend" / "design.css"
html_path = root / "frontend" / "index.html"
css = css_path.read_text(encoding="utf-8")
html = html_path.read_text(encoding="utf-8")

# Remove previous embedded block (comment text may vary after "app-styles-embedded")
html = re.sub(
    r"<style>\s*/\* app-styles-embedded[\s\S]*?</style>\s*",
    "",
    html,
    count=1,
)

# Remove any stylesheet link to design.css (relative or absolute)
html = re.sub(
    r'<link rel="stylesheet" href="[^"]*design\.css"[^>]*>\s*',
    "",
    html,
)

marker = (
    '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&display=swap" '
    'rel="stylesheet">'
)
if marker not in html:
    raise SystemExit("Montserrat font link not found in index.html")

block = (
    "\n"
    "  <style>/* app-styles-embedded — edit frontend/design.css then run tools/embed_css_in_index.py */\n"
    + css.rstrip()
    + "\n  </style>\n"
    "  <link rel=\"stylesheet\" href=\"/design.css\">\n"
)

new_html = html.replace(marker, marker + block, 1)
html_path.write_text(new_html, encoding="utf-8")
print("Embedded CSS into", html_path, "css bytes", len(css))
