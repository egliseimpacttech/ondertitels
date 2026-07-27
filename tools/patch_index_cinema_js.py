# -*- coding: utf-8 -*-
"""Patch cinema-related JS in frontend/index.html."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

# Line 1579 (index 1578): replace toggleCinema button
idx = 1578
if "toggleCinema" not in lines[idx]:
    raise SystemExit(f"expected toggleCinema on line {idx+1}, got: {lines[idx][:80]!r}")
lines[idx] = (
    "          html += '<button class=\"small secondary\" onclick=\"openCinemaPublishModal(\\'' + file.id + '\\')\">' + "
    "(pub ? 'Edit Cinema' : 'Publish') + '</button>';\n"
)
t = "".join(lines)

old_block = """    async function toggleCinema(fileId, makePublic) {
      try {
        const fd = new FormData();
        fd.append('public', makePublic ? 'true' : 'false');
        const res = await apiFetch(apiBase + '/api/library/file/' + fileId + '/cinema', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || ('Cinema update failed: ' + res.status));
        loadLibrary();
      } catch (err) {
        alert('Cinema visibility failed: ' + (err.message || err));
      }
    }

    async function renameLibFile(id, currentName) {"""

new_block = r"""    const CINEMA_LANG_ROWS = [
      ['nl', 'Nederlands'], ['en', 'English'], ['es', 'Spanish'], ['mg', 'Malagasy'], ['kg', 'Kikongo'],
      ['ts', 'Tshiluba'], ['ln', 'Lingala'], ['pt', 'Portuguese'], ['zh', 'Chinese'],
    ];
    let lastCinemaVideos = [];
    let cinemaDetailVideo = null;
    let cinemaDetailBlobUrl = null;
    let cinemaCardBlobUrls = [];

    function revokeCinemaCardBlobs() {
      for (const u of cinemaCardBlobUrls) {
        try { URL.revokeObjectURL(u); } catch (_) {}
      }
      cinemaCardBlobUrls = [];
    }

    function syncCinemaCoverUi() {
      const typ = document.getElementById('cinemaCoverType').value;
      document.getElementById('cinemaCoverWrapSecond').style.display = typ === 'frame' ? 'block' : 'none';
      document.getElementById('cinemaCoverWrapFile').style.display = typ === 'upload' ? 'block' : 'none';
    }

    async function openCinemaPublishModal(fileId) {
      document.getElementById('cinemaPublishFileId').value = fileId;
      document.getElementById('cinemaCoverFile').value = '';
      try {
        const [metaRes, vttRes] = await Promise.all([
          apiFetch(apiBase + '/api/library/file/' + fileId + '/cinema'),
          apiFetch(apiBase + '/api/library/vtt-list'),
        ]);
        const metaData = await metaRes.json().catch(() => ({}));
        if (!metaRes.ok) throw new Error(metaData.detail || ('HTTP ' + metaRes.status));
        const vttData = await vttRes.json().catch(() => ({}));
        if (!vttRes.ok) throw new Error(vttData.detail || 'Could not load VTT list');
        document.getElementById('cinemaPublishTitle').value = metaData.cinema_title || '';
        document.getElementById('cinemaPublishDesc').value = metaData.cinema_description || '';
        document.getElementById('cinemaCoverType').value = metaData.cinema_cover_type === 'upload' ? 'upload' : 'frame';
        document.getElementById('cinemaCoverSecond').value = String(metaData.cinema_cover_second ?? 0);
        syncCinemaCoverUi();
        const rows = document.getElementById('cinemaSubtitleRows');
        rows.innerHTML = '';
        const subs = metaData.cinema_subtitles || {};
        for (const [code, label] of CINEMA_LANG_ROWS) {
          const row = document.createElement('div');
          row.className = 'sub-row';
          row.innerHTML = '<span>' + label + '</span><select data-lang="' + code + '"><option value="">—</option></select>';
          const sel = row.querySelector('select');
          for (const it of (vttData.items || [])) {
            const opt = document.createElement('option');
            opt.value = it.id;
            opt.textContent = (it.folder ? it.folder + '/' : '') + it.name;
            if (subs[code] === it.id) opt.selected = true;
            sel.appendChild(opt);
          }
          if (subs[code] && !sel.value) {
            const opt = document.createElement('option');
            opt.value = subs[code];
            opt.textContent = '(missing file) ' + subs[code];
            opt.selected = true;
            sel.appendChild(opt);
          }
          rows.appendChild(row);
        }
        document.getElementById('cinemaPublishModal').classList.add('show');
      } catch (err) {
        alert('Could not open Cinema: ' + (err.message || err));
      }
    }

    async function saveCinemaPublish() {
      const fileId = document.getElementById('cinemaPublishFileId').value;
      const fd = new FormData();
      fd.append('public', 'true');
      fd.append('title', (document.getElementById('cinemaPublishTitle').value || '').trim());
      fd.append('description', (document.getElementById('cinemaPublishDesc').value || '').trim());
      const ct = document.getElementById('cinemaCoverType').value;
      fd.append('cover_type', ct);
      fd.append('cover_second', document.getElementById('cinemaCoverSecond').value || '0');
      const subs = {};
      document.querySelectorAll('#cinemaSubtitleRows select').forEach((sel) => {
        const lang = sel.getAttribute('data-lang');
        if (sel.value) subs[lang] = sel.value;
      });
      fd.append('subtitles_json', JSON.stringify(subs));
      const cf = document.getElementById('cinemaCoverFile').files[0];
      if (ct === 'upload' && cf) fd.append('cover_file', cf);
      try {
        await uploadMultipartWithProgress(apiBase + '/api/library/file/' + fileId + '/cinema', fd, null);
        document.getElementById('cinemaPublishModal').classList.remove('show');
        loadLibrary();
      } catch (err) {
        alert('Publish failed: ' + (err.message || err));
      }
    }

    async function unpublishCinemaFromModal() {
      const fileId = document.getElementById('cinemaPublishFileId').value;
      if (!confirm('Remove this video from Cinema?')) return;
      const fd = new FormData();
      fd.append('public', 'false');
      fd.append('title', (document.getElementById('cinemaPublishTitle').value || '').trim());
      fd.append('description', (document.getElementById('cinemaPublishDesc').value || '').trim());
      fd.append('cover_type', document.getElementById('cinemaCoverType').value);
      fd.append('cover_second', document.getElementById('cinemaCoverSecond').value || '0');
      fd.append('subtitles_json', '{}');
      try {
        await uploadMultipartWithProgress(apiBase + '/api/library/file/' + fileId + '/cinema', fd, null);
        document.getElementById('cinemaPublishModal').classList.remove('show');
        loadLibrary();
      } catch (err) {
        alert('Unpublish failed: ' + (err.message || err));
      }
    }

    function openCinemaDetailById(videoId) {
      const video = lastCinemaVideos.find((v) => v.id === videoId);
      if (video) void openCinemaDetail(video);
    }

    async function openCinemaDetail(video) {
      cinemaDetailVideo = video;
      if (cinemaDetailBlobUrl) {
        try { URL.revokeObjectURL(cinemaDetailBlobUrl); } catch (_) {}
        cinemaDetailBlobUrl = null;
      }
      document.getElementById('cinemaDetailTitle').textContent = video.title || video.name;
      document.getElementById('cinemaDetailDesc').textContent = video.description || '';
      const sel = document.getElementById('cinemaDetailLang');
      sel.innerHTML = '';
      const langs = video.languages || [];
      if (!langs.length) {
        const opt = document.createElement('option');
        opt.value = 'none';
        opt.textContent = 'No subtitles';
        sel.appendChild(opt);
      } else {
        for (const L of langs) {
          const opt = document.createElement('option');
          opt.value = L.code;
          opt.textContent = L.name;
          sel.appendChild(opt);
        }
      }
      const cov = document.getElementById('cinemaDetailCover');
      cov.innerHTML = '';
      if (video.cover_url) {
        try {
          const res = await apiFetch(apiBase + video.cover_url);
          if (res.ok) {
            const blob = await res.blob();
            cinemaDetailBlobUrl = URL.createObjectURL(blob);
            const img = document.createElement('img');
            img.src = cinemaDetailBlobUrl;
            img.alt = '';
            cov.appendChild(img);
          }
        } catch (_) {}
      }
      document.getElementById('cinemaDetailModal').classList.add('show');
    }

    async function renameLibFile(id, currentName) {"""

if old_block not in t:
    raise SystemExit("toggleCinema block not found")
t = t.replace(old_block, new_block, 1)

old_lc = """    async function loadCinema() {
      try {
        const res = await apiFetch(apiBase + '/api/cinema/videos');
        if (!res.ok) throw new Error('Server returned ' + res.status);
        const data = await res.json();
        renderCinema(data);
      } catch (err) {
        document.getElementById('cinemaContent').innerHTML = '<div class="message error">Error loading cinema: ' + err.message + '</div>';
      }
    }

    function renderCinema(data) {
      const content = document.getElementById('cinemaContent');
      if (!data.videos || !data.videos.length) {
        content.innerHTML = '<div class="empty-msg">No videos available in Cinema.</div>';
        return;
      }
      let html = '<div class="cinema-grid">';
      for (const video of data.videos) {
        html += '<div class="cinema-video">';
        html += '<div class="cinema-video-title">' + video.name + '</div>';
        html += '<div class="cinema-video-languages">';
        for (const lang of video.languages) {
          html += '<button class="cinema-lang-btn" onclick="watchVideo(\\'' + video.id + '\\', \\'' + lang.code + '\\')">' + lang.name + '</button>';
        }
        html += '</div></div>';
      }
      html += '</div>';
      content.innerHTML = html;
    }

    function watchVideo(videoId, langCode) {
      window.location.href = apiBase + '/api/cinema/watch/' + videoId + '?lang=' + langCode;
    }

    function navigateLib(path) {"""

new_lc = """    async function loadCinema() {
      try {
        const res = await apiFetch(apiBase + '/api/cinema/videos');
        if (!res.ok) throw new Error('Server returned ' + res.status);
        const data = await res.json();
        lastCinemaVideos = data.videos || [];
        await renderCinema(data);
      } catch (err) {
        document.getElementById('cinemaContent').innerHTML = '<div class="message error">Error loading cinema: ' + err.message + '</div>';
      }
    }

    async function renderCinema(data) {
      const content = document.getElementById('cinemaContent');
      revokeCinemaCardBlobs();
      if (!data.videos || !data.videos.length) {
        content.innerHTML = '<div class="empty-msg">No videos available in Cinema.</div>';
        return;
      }
      const esc = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
      let html = '<div class="cinema-grid">';
      for (const video of data.videos) {
        const title = esc(video.title || video.name);
        html += '<div class="cinema-video cinema-card-click" onclick="openCinemaDetailById(\\'' + video.id + '\\')">';
        html += '<div class="cinema-thumbnail" id="cinema-thumb-' + video.id + '"></div>';
        html += '<div class="cinema-info"><div class="cinema-title">' + title + '</div></div>';
        html += '</div>';
      }
      html += '</div>';
      content.innerHTML = html;
      for (const video of data.videos) {
        const el = document.getElementById('cinema-thumb-' + video.id);
        if (!el) continue;
        if (video.cover_url) {
          try {
            const res = await apiFetch(apiBase + video.cover_url);
            if (res.ok) {
              const blob = await res.blob();
              const u = URL.createObjectURL(blob);
              cinemaCardBlobUrls.push(u);
              const img = document.createElement('img');
              img.className = 'cinema-thumb-img';
              img.alt = '';
              img.src = u;
              el.appendChild(img);
            }
          } catch (_) {}
        }
        if (!el.firstChild) el.innerHTML = '<span style="font-size:48px;">▶</span>';
      }
    }

    async function watchVideo(videoId, langCode) {
      const tok = await ensureIdToken();
      if (!tok) {
        alert('Sign in required');
        return;
      }
      const q = new URLSearchParams();
      q.set('lang', langCode && langCode !== 'none' ? langCode : 'nl');
      q.set('token', tok);
      window.location.href = apiBase + '/api/cinema/watch/' + videoId + '?' + q.toString();
    }

    function navigateLib(path) {"""

if old_lc not in t:
    raise SystemExit("loadCinema block not found")
t = t.replace(old_lc, new_lc, 1)

needle = """    adminInviteBtn.addEventListener('click', async () => {
      const email = (adminInviteEmail.value || '').trim();
      if (!email) {
        adminInviteResult.innerHTML = '<div class="message error">Enter an email.</div>';
        return;
      }
      adminInviteBtn.disabled = true;
      adminInviteResult.innerHTML = '<div class="message">Generating link…</div>';
      try {
        const fd = new FormData();
        fd.append('email', email);
        const res = await apiFetch(apiBase + '/api/admin/invite', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || res.statusText || 'Invite failed');
        const link = data.password_reset_link || '';
        adminInviteResult.innerHTML =
          '<div class="message">'
          + '<div><b>User:</b> ' + (data.email || email) + '</div>'
          + '<div style="margin-top:8px;"><b>Password reset link:</b></div>'
          + '<textarea rows="3" readonly style="margin-top:6px;">' + link + '</textarea>'
          + '<div class="file-source-info">Copy this link and send it to the user. They set their own password and then sign in with Email + Password.</div>'
          + '</div>';
      } catch (e) {
        const msg = e && e.message ? String(e.message) : 'Invite failed';
        adminInviteResult.innerHTML = '<div class="message error">' + msg + '</div>';
      } finally {
        adminInviteBtn.disabled = false;
      }
    });

    // ========== HOME: Transcribe & Translate =========="""

insert = """    adminInviteBtn.addEventListener('click', async () => {
      const email = (adminInviteEmail.value || '').trim();
      if (!email) {
        adminInviteResult.innerHTML = '<div class="message error">Enter an email.</div>';
        return;
      }
      adminInviteBtn.disabled = true;
      adminInviteResult.innerHTML = '<div class="message">Generating link…</div>';
      try {
        const fd = new FormData();
        fd.append('email', email);
        const res = await apiFetch(apiBase + '/api/admin/invite', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || res.statusText || 'Invite failed');
        const link = data.password_reset_link || '';
        adminInviteResult.innerHTML =
          '<div class="message">'
          + '<div><b>User:</b> ' + (data.email || email) + '</div>'
          + '<div style="margin-top:8px;"><b>Password reset link:</b></div>'
          + '<textarea rows="3" readonly style="margin-top:6px;">' + link + '</textarea>'
          + '<div class="file-source-info">Copy this link and send it to the user. They set their own password and then sign in with Email + Password.</div>'
          + '</div>';
      } catch (e) {
        const msg = e && e.message ? String(e.message) : 'Invite failed';
        adminInviteResult.innerHTML = '<div class="message error">' + msg + '</div>';
      } finally {
        adminInviteBtn.disabled = false;
      }
    });

    document.getElementById('cinemaCoverType').addEventListener('change', syncCinemaCoverUi);
    document.getElementById('cinemaPublishSaveBtn').addEventListener('click', () => void saveCinemaPublish());
    document.getElementById('cinemaPublishUnpublishBtn').addEventListener('click', () => void unpublishCinemaFromModal());
    document.getElementById('cinemaPublishCancelBtn').addEventListener('click', () => {
      document.getElementById('cinemaPublishModal').classList.remove('show');
    });
    document.getElementById('cinemaDetailCloseBtn').addEventListener('click', () => {
      document.getElementById('cinemaDetailModal').classList.remove('show');
    });
    document.getElementById('cinemaDetailPlayBtn').addEventListener('click', () => {
      if (!cinemaDetailVideo) return;
      const lang = document.getElementById('cinemaDetailLang').value || 'nl';
      void watchVideo(cinemaDetailVideo.id, lang);
    });
    document.getElementById('cinemaDetailModal').addEventListener('click', (e) => {
      if (e.target.id === 'cinemaDetailModal') {
        document.getElementById('cinemaDetailModal').classList.remove('show');
      }
    });
    document.getElementById('cinemaPublishModal').addEventListener('click', (e) => {
      if (e.target.id === 'cinemaPublishModal') {
        document.getElementById('cinemaPublishModal').classList.remove('show');
      }
    });

    // ========== HOME: Transcribe & Translate =========="""

if needle not in t:
    raise SystemExit("admin invite needle not found")
t = t.replace(needle, insert, 1)

old_oa = """    Object.assign(window, {
      openLibPicker,
      navigateLibPicker,
      selectLibPickerFile,
      navigateLib,
      deleteFolder,
      deleteLibFile,
      downloadLibFile,
      editInWorkspace,
      openTextInWorkspace,
      renameLibFile,
      openVideoInWorkspace,
      toggleCinema,
      watchVideo,
    });"""

new_oa = """    Object.assign(window, {
      openLibPicker,
      navigateLibPicker,
      selectLibPickerFile,
      navigateLib,
      deleteFolder,
      deleteLibFile,
      downloadLibFile,
      editInWorkspace,
      openTextInWorkspace,
      renameLibFile,
      openVideoInWorkspace,
      openCinemaPublishModal,
      openCinemaDetailById,
      watchVideo,
    });"""

if old_oa not in t:
    raise SystemExit("Object.assign block not found")
t = t.replace(old_oa, new_oa, 1)

p.write_text(t, encoding="utf-8")
print("ok patch index cinema")
