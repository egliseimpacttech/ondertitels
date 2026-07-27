from pathlib import Path

idx = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
t = idx.read_text(encoding="utf-8")

# Ensure watch-page back links target explicit cinema view.
t = t.replace('href="/cinema" class="back-btn"', 'href="/?view=cinema" class="back-btn"')

needle = """    function activateCinemaView() {
      const allViews = document.querySelectorAll('.view');
      const allMenuItems = document.querySelectorAll('.menu-item');
      allViews.forEach(v => v.classList.remove('active'));
      const cinemaView = document.getElementById('cinemaView');
      if (cinemaView) cinemaView.classList.add('active');
      allMenuItems.forEach(i => i.classList.remove('active'));
      const cinemaItem = document.querySelector('.menu-item[data-view="cinema"]');
      if (cinemaItem) cinemaItem.classList.add('active');
      loadCinema().catch(() => {});
    }
"""

inject = """    function activateCinemaView() {
      const allViews = document.querySelectorAll('.view');
      const allMenuItems = document.querySelectorAll('.menu-item');
      allViews.forEach(v => v.classList.remove('active'));
      const cinemaView = document.getElementById('cinemaView');
      if (cinemaView) cinemaView.classList.add('active');
      allMenuItems.forEach(i => i.classList.remove('active'));
      const cinemaItem = document.querySelector('.menu-item[data-view="cinema"]');
      if (cinemaItem) cinemaItem.classList.add('active');
      loadCinema().catch(() => {});
    }

    function shouldOpenCinemaFromLocation() {
      const pth = (window.location.pathname || '').toLowerCase();
      const params = new URLSearchParams(window.location.search || '');
      return pth.startsWith('/cinema') || params.get('view') === 'cinema';
    }
"""
if needle in t:
    t = t.replace(needle, inject, 1)

# Force cinema immediately after app shows and after auth mode detection.
t = t.replace(
    "      await detectCinemaOnlyMode();\n      const pth = (window.location.pathname || '').toLowerCase();\n      if (pth.startsWith('/cinema')) activateCinemaView();",
    "      await detectCinemaOnlyMode();\n      if (shouldOpenCinemaFromLocation()) activateCinemaView();",
    1,
)

idx.write_text(t, encoding="utf-8")
print("ok")
