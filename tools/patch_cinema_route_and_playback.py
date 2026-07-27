from pathlib import Path

# 1) Frontend: ensure /cinema opens cinema view
f = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
t = f.read_text(encoding="utf-8")

needle = """    function setCinemaOnlyUi(enabled) {
      cinemaOnlyMode = !!enabled;
      const allViews = document.querySelectorAll('.view');
      const allMenuItems = document.querySelectorAll('.menu-item');
      const restrictedViews = ['home', 'workspace', 'library', 'admin'];
      restrictedViews.forEach((v) => {
        const item = document.querySelector('.menu-item[data-view="' + v + '"]');
        if (item) item.style.display = cinemaOnlyMode ? 'none' : '';
      });
      if (cinemaOnlyMode) {
        allViews.forEach(v => v.classList.remove('active'));
        const cinemaView = document.getElementById('cinemaView');
        if (cinemaView) cinemaView.classList.add('active');
        allMenuItems.forEach(i => i.classList.remove('active'));
        const cinemaItem = document.querySelector('.menu-item[data-view="cinema"]');
        if (cinemaItem) cinemaItem.classList.add('active');
        loadCinema().catch(() => {});
      }
    }
"""

replacement = """    function activateCinemaView() {
      const allViews = document.querySelectorAll('.view');
      const allMenuItems = document.querySelectorAll('.menu-item');
      allViews.forEach(v => v.classList.remove('active'));
      const cinemaView = document.getElementById('cinemaView');
      if (cinemaView) cinemaView.classList.add('active');
      allMenuItems.forEach(i => i.classList.remove('active'));
      const cinemaItem = document.querySelector('.menu-item[data-view=\"cinema\"]');
      if (cinemaItem) cinemaItem.classList.add('active');
      loadCinema().catch(() => {});
    }

    function setCinemaOnlyUi(enabled) {
      cinemaOnlyMode = !!enabled;
      const restrictedViews = ['home', 'workspace', 'library', 'admin'];
      restrictedViews.forEach((v) => {
        const item = document.querySelector('.menu-item[data-view=\"' + v + '\"]');
        if (item) item.style.display = cinemaOnlyMode ? 'none' : '';
      });
      if (cinemaOnlyMode) activateCinemaView();
    }
"""

if needle in t:
    t = t.replace(needle, replacement, 1)

old_auth = """      if (authGate) authGate.style.display = 'none';
      if (appWrap) appWrap.style.display = 'block';
      await detectCinemaOnlyMode();
      if (authReadyResolve) { authReadyResolve(); authReadyResolve = null; }
"""

new_auth = """      if (authGate) authGate.style.display = 'none';
      if (appWrap) appWrap.style.display = 'block';
      await detectCinemaOnlyMode();
      const pth = (window.location.pathname || '').toLowerCase();
      if (pth.startsWith('/cinema')) activateCinemaView();
      if (authReadyResolve) { authReadyResolve(); authReadyResolve = null; }
"""
if old_auth in t:
    t = t.replace(old_auth, new_auth, 1)

f.write_text(t, encoding="utf-8")

# 2) Backend: direct signed GCS URL in watch page video src
b = Path(__file__).resolve().parent.parent / "backend" / "main.py"
tb = b.read_text(encoding="utf-8")

old = """    video_src = f"/api/cinema/video/{video_id}"
    if token:
        video_src += "?token=" + quote(token, safe="")
"""
new = """    if (config.GCS_BUCKET_NAME or "").strip():
        video_src = _signed_gcs_get_url(f"library/files/{video_id}", expires_seconds=1800)
    else:
        video_src = f"/api/cinema/video/{video_id}"
        if token:
            video_src += "?token=" + quote(token, safe="")
"""
if old in tb:
    tb = tb.replace(old, new, 1)

b.write_text(tb, encoding="utf-8")
print("ok")
