import { initializeApp } from "https://www.gstatic.com/firebasejs/12.11.0/firebase-app.js";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/12.11.0/firebase-auth.js";

    const firebaseConfig = {
      apiKey: "AIzaSyCqd17ac8mHZkRUDi0G85P6zjuzSG3ktd8",
      authDomain: "itech-workspace-8da4f.firebaseapp.com",
      projectId: "itech-workspace-8da4f",
      storageBucket: "itech-workspace-8da4f.firebasestorage.app",
      messagingSenderId: "512996235945",
      appId: "1:512996235945:web:792379ec240fbed8e427b8",
      measurementId: "G-N3B77WJGMH"
    };

    const firebaseApp = initializeApp(firebaseConfig);
    const fbAuth = getAuth(firebaseApp);
    /** Wait for first auth snapshot (persistence loaded). CDN build may not export authStateReady. */
    const firebaseAuthReady = new Promise((resolve) => {
      const unsub = onAuthStateChanged(fbAuth, () => {
        unsub();
        resolve();
      });
    });

    const apiBase = '';
    let currentLibPath = '';

    const authGate = document.getElementById('authGate');
    const appWrap = document.getElementById('appWrap');
    const authLoginEmail = document.getElementById('authLoginEmail');
    const authLoginPassword = document.getElementById('authLoginPassword');
    const authRegisterEmail = document.getElementById('authRegisterEmail');
    const authRegisterPassword = document.getElementById('authRegisterPassword');
    const authPasswordSignInBtn = document.getElementById('authPasswordSignInBtn');
    const authPasswordSignUpBtn = document.getElementById('authPasswordSignUpBtn');
    const authMsg = document.getElementById('authMsg');

    let idToken = null;

    const menuBtn = document.getElementById('menuBtn');
    const menuDropdown = document.getElementById('menuDropdown');
    const menuItems = document.querySelectorAll('.menu-item');
    const views = document.querySelectorAll('.view');
    const startupPreload = document.getElementById('startupPreload');
    let startupPreloadHidden = false;

    function hideStartupPreload() {
      if (startupPreloadHidden || !startupPreload) return;
      startupPreloadHidden = true;
      startupPreload.classList.add('hidden');
      window.setTimeout(() => {
        if (startupPreload && startupPreload.parentNode) startupPreload.parentNode.removeChild(startupPreload);
      }, 220);
    }
    // Safety timeout: never leave user behind a stuck splash screen.
    window.setTimeout(hideStartupPreload, 8000);

    async function ensureIdToken(forceRefresh = false) {
      await firebaseAuthReady;
      const user = fbAuth.currentUser;
      if (!user) return null;
      // Always ask Firebase for a current token (it refreshes automatically when needed).
      // Keeping a cached token forever causes 401 after ~1 hour when it expires.
      idToken = await user.getIdToken(!!forceRefresh);
      return idToken || null;
    }

    async function apiFetch(url, options) {
      options = options || {};
      options.headers = options.headers || {};
      const tok = await ensureIdToken();
      if (tok) options.headers['Authorization'] = 'Bearer ' + tok;
      let res = await fetch(url, options);
      if (res.status === 401 && fbAuth.currentUser) {
        // Token can become stale during session restore; refresh once and retry.
        const refreshed = await ensureIdToken(true);
        if (refreshed) {
          options.headers['Authorization'] = 'Bearer ' + refreshed;
          res = await fetch(url, options);
        }
      }
      return res;
    }

    /** Fetch a library file by id; throws with server detail on 4xx/5xx (same as downloadViaApi). */
    async function fetchLibraryFileBlob(fileId) {
      const res = await apiFetch(apiBase + '/api/library/file/' + encodeURIComponent(fileId));
      if (!res.ok) {
        let detail = res.statusText || String(res.status);
        try {
          const body = await res.json();
          if (body && body.detail) detail = (typeof body.detail === 'string') ? body.detail : JSON.stringify(body.detail);
        } catch (_) {}
        throw new Error(detail);
      }
      return res.blob();
    }

    async function downloadViaApi(url, filename) {
      const res = await apiFetch(url);
      if (!res.ok) {
        let detail = res.statusText || String(res.status);
        try {
          const body = await res.json();
          if (body && body.detail) detail = (typeof body.detail === 'string') ? body.detail : JSON.stringify(body.detail);
        } catch (_) {}
        throw new Error(detail);
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = filename || '';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objectUrl);
    }

    function sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    async function createResumableSession(filename, contentType) {
      const form = new FormData();
      form.append('filename', filename || 'upload.bin');
      form.append('content_type', contentType || 'application/octet-stream');
      const res = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || ('Échec d’initialisation de l’envoi : ' + res.status));
      if (!data.session_url || !data.object_name) throw new Error('Réponse d’initialisation invalide.');
      return data;
    }

    async function probeResumableOffset(sessionUrl, totalSize) {
      const res = await fetch(sessionUrl, {
        method: 'PUT',
        headers: {
          'Content-Length': '0',
          'Content-Range': 'bytes */' + totalSize,
        },
      });
      if (res.status === 308) {
        const range = res.headers.get('Range') || res.headers.get('range') || '';
        const m = /bytes=0-(\d+)/i.exec(range);
        if (m) return Number(m[1]) + 1;
        return 0;
      }
      if (res.ok) return totalSize;
      throw new Error('Vérification de reprise échouée : ' + res.status);
    }

    async function uploadResumableWithRetry(sessionUrl, body, contentType, onProgress, onState) {
      const total = (body && typeof body.size === 'number') ? body.size : 0;
      if (!total) throw new Error('La taille du fichier est 0');
      const chunkSize = 8 * 1024 * 1024; // 8 MB
      const maxRetries = 8;
      let offset = 0;
      let retries = 0;
      while (offset < total) {
        const end = Math.min(offset + chunkSize, total);
        const chunk = body.slice(offset, end);
        try {
          const res = await fetch(sessionUrl, {
            method: 'PUT',
            headers: {
              'Content-Type': contentType || 'application/octet-stream',
              'Content-Range': 'bytes ' + offset + '-' + (end - 1) + '/' + total,
            },
            body: chunk,
          });
          if (res.status === 308) {
            const range = res.headers.get('Range') || res.headers.get('range') || '';
            const m = /bytes=0-(\d+)/i.exec(range);
            offset = m ? (Number(m[1]) + 1) : end;
            retries = 0;
            if (onProgress) onProgress(offset, total);
            continue;
          }
          if (res.ok) {
            offset = total;
            if (onProgress) onProgress(total, total);
            return;
          }
          throw new Error('Échec du transfert d’un bloc : ' + res.status);
        } catch (_) {
          retries += 1;
          if (retries > maxRetries) throw new Error('Téléversement en pause trop longtemps. Vérifiez Internet et réessayez.');
          if (onState) onState('paused', retries);
          await sleep(Math.min(30000, 1000 * (2 ** retries)));
          try {
            offset = await probeResumableOffset(sessionUrl, total);
            if (onProgress) onProgress(offset, total);
          } catch (_) {
            // Keep retrying; next loop retries current/next chunk.
          }
          if (onState) onState('resuming', retries);
        }
      }
    }

    async function uploadToSignedUrl(uploadUrl, contentType, body, onProgress, onState) {
      // Keep old API shape for callers; first arg is now resumable session URL.
      return uploadResumableWithRetry(uploadUrl, body, contentType, onProgress, onState);
    }

    async function uploadMultipartWithProgress(url, formData, onProgress) {
      const tok = await ensureIdToken();
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);
        if (tok) xhr.setRequestHeader('Authorization', 'Bearer ' + tok);
        xhr.upload.onprogress = (evt) => {
          if (onProgress && evt.lengthComputable) onProgress(evt.loaded, evt.total);
        };
        xhr.onerror = () => reject(new Error('Échec du téléversement (erreur réseau).'));
        xhr.onload = () => {
          let data = null;
          try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
          if (xhr.status >= 200 && xhr.status < 300) resolve(data || {});
          else reject(new Error((data && data.detail) ? data.detail : ('Échec du téléversement : ' + xhr.status)));
        };
        xhr.send(formData);
      });
    }

    async function handlePasswordSignIn() {
      const email = (authLoginEmail && authLoginEmail.value ? authLoginEmail.value : '').trim();
      const pass = (authLoginPassword && authLoginPassword.value) ? authLoginPassword.value : '';
      if (!email || !pass) {
        authMsg.innerHTML = '<div class="message error">Saisissez l’e-mail et le mot de passe.</div>';
        return;
      }
      try {
        const cred = await signInWithEmailAndPassword(fbAuth, email, pass);
        idToken = await cred.user.getIdToken();
        authMsg.innerHTML = '';
      } catch (e) {
        const code = e && (e.code || e.name) ? String(e.code || e.name) : '';
        const msg = e && e.message ? String(e.message) : '';
        authMsg.innerHTML =
          '<div class="message error">Échec de la connexion par mot de passe.'
          + (code ? '<br><b>Code d’erreur :</b> ' + code : '')
          + (msg ? '<br><b>Message :</b> ' + msg : '')
          + '</div>';
      }
    }

    async function handlePasswordSignUp() {
      const email = (authRegisterEmail && authRegisterEmail.value ? authRegisterEmail.value : '').trim();
      const pass = (authRegisterPassword && authRegisterPassword.value) ? authRegisterPassword.value : '';
      if (!email || !pass) {
        authMsg.innerHTML = '<div class="message error">Saisissez l’e-mail et le mot de passe.</div>';
        return;
      }
      try {
        const cred = await createUserWithEmailAndPassword(fbAuth, email, pass);
        // Ensure token is immediately available for API calls (prevents 401 right after signup)
        idToken = await cred.user.getIdToken();
        authMsg.innerHTML = '<div class="message">Compte créé. Vous êtes connecté.</div>';
      } catch (e) {
        const code = e && (e.code || e.name) ? String(e.code || e.name) : '';
        const msg = e && e.message ? String(e.message) : '';
        authMsg.innerHTML =
          '<div class="message error">Échec de l’inscription.'
          + (code ? '<br><b>Code d’erreur :</b> ' + code : '')
          + (msg ? '<br><b>Message :</b> ' + msg : '')
          + '</div>';
      }
    }

    authPasswordSignInBtn.addEventListener('click', handlePasswordSignIn);
    authPasswordSignUpBtn.addEventListener('click', handlePasswordSignUp);

    let cinemaOnlyMode = false;
    let isAdmin = false;

    const VIEW_PATH_SEGMENTS = {
      home: '/accueil',
      cinema: '/cinema',
      workspace: '/workspace',
      library: '/bibliotheque',
      admin: '/administration',
    };

    function syncShellLayoutClass(view) {
      document.body.classList.remove('cinema-active', 'library-active');
      if (view === 'cinema') document.body.classList.add('cinema-active');
      else if (view === 'library') document.body.classList.add('library-active');
    }

    function applyRouteForView(view, useReplace) {
      const path = VIEW_PATH_SEGMENTS[view] || VIEW_PATH_SEGMENTS.home;
      try {
        if (useReplace) history.replaceState({ view }, '', path);
        else history.pushState({ view }, '', path);
      } catch (_) {}
    }

    function initialViewFromLocation() {
      const params = new URLSearchParams(window.location.search || '');
      const q = (params.get('view') || '').toLowerCase();
      if (q === 'cinema') return 'cinema';
      if (q === 'library' || q === 'bibliotheque') return 'library';
      if (q === 'home' || q === 'accueil') return 'home';
      if (q === 'workspace') return 'workspace';
      if (q === 'admin' || q === 'administration') return 'admin';
      const raw = (window.location.pathname || '').toLowerCase();
      const trimmed = raw.replace(/\/+$/, '');
      const seg = trimmed.split('/').filter(Boolean).pop() || '';
      if (seg === 'cinema') return 'cinema';
      if (seg === 'bibliotheque') return 'library';
      if (seg === 'workspace') return 'workspace';
      if (seg === 'administration') return 'admin';
      if (seg === 'accueil') return 'home';
      return 'home';
    }

    async function showView(view, opts) {
      opts = opts || {};
      if (cinemaOnlyMode && view !== 'cinema') return;
      const viewId = view + 'View';
      views.forEach((v) => v.classList.remove('active'));
      const el = document.getElementById(viewId);
      if (el) el.classList.add('active');
      menuItems.forEach((i) => {
        if (i.dataset && i.dataset.view) i.classList.toggle('active', i.dataset.view === view);
      });
      syncShellLayoutClass(view);
      const sync = opts.syncUrl;
      if (sync === 'push') applyRouteForView(view, false);
      else if (sync === 'replace') applyRouteForView(view, true);
      if (view === 'library') await loadLibrary();
      if (view === 'workspace') await loadWorkspaceFolders();
      if (view === 'cinema') loadCinema().catch(() => {});
    }

    function setCinemaOnlyUi(enabled) {
      cinemaOnlyMode = !!enabled;
      const restrictedViews = ['home', 'workspace', 'library', 'admin'];
      restrictedViews.forEach((v) => {
        const item = document.querySelector('.menu-item[data-view="' + v + '"]');
        if (item) item.style.display = cinemaOnlyMode ? 'none' : '';
      });
      if (cinemaOnlyMode) void showView('cinema', { syncUrl: 'replace' });
    }

    async function detectCinemaOnlyMode() {
      try {
        const res = await apiFetch(apiBase + '/api/library?path=' + encodeURIComponent(''));
        if (res.status === 403) {
          setCinemaOnlyUi(true);
          isAdmin = false;
          return;
        }
        setCinemaOnlyUi(false);
        // Check admin status
        try {
          const adminRes = await apiFetch(apiBase + '/api/admin/status');
          const adminData = await adminRes.json().catch(() => ({}));
          isAdmin = !!adminData.is_admin;
        } catch (_) {
          isAdmin = false;
        }
      } catch (_) {
        // leave UI as-is on transient network errors
      }
    }

    onAuthStateChanged(fbAuth, async (user) => {
      if (!user) {
        idToken = null;
        currentLibPath = '';
        document.body.classList.remove('cinema-active', 'library-active');
        if (authGate) authGate.style.display = 'block';
        if (appWrap) appWrap.style.display = 'none';
        hideStartupPreload();
        return;
      }
      idToken = await user.getIdToken();
      if (authGate) authGate.style.display = 'none';
      if (appWrap) appWrap.style.display = 'block';
      await detectCinemaOnlyMode();
      if (!cinemaOnlyMode) {
        currentLibPath = '';
        const iv = initialViewFromLocation();
        await showView(iv, { syncUrl: null });
        if (iv !== 'library') {
          try {
            await loadLibrary();
          } catch (_) {}
        }
      }
      hideStartupPreload();
    });
    
    // Selected files for forms (can be File object or {libraryId, name})
    let transcribeSelectedFile = null;
    let translateSelectedFile = null;
    let ttsSelectedFile = null;
    let burnVideoSelected = null;
    let burnVttSelected = null;
    let homeUploadSelectedFile = null;
    
    // Library picker state
    let libPickerPath = '';
    let libPickerTarget = null; // 'transcribe', 'translate', ...
    let libPickerFilter = []; // ['audio', 'video'] or ['vtt']
    let libPickerSelectedFile = null;
    let libraryDragFileId = null;

    // ========== MENU ==========
    menuBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      menuDropdown.classList.toggle('show');
    });
    document.addEventListener('click', () => menuDropdown.classList.remove('show'));

    menuItems.forEach((item) => {
      item.addEventListener('click', async (e) => {
        const action = item.dataset.action;
        const view = item.dataset.view;
        if (action === 'signout') {
          try {
            await signOut(fbAuth);
          } catch (_) {}
          menuDropdown.classList.remove('show');
          return;
        }
        if (view) {
          if (item.tagName === 'A' && item.getAttribute('href')) e.preventDefault();
          if (cinemaOnlyMode && view !== 'cinema') {
            alert('Ce compte n’a accès qu’au Cinéma.');
            menuDropdown.classList.remove('show');
            return;
          }
          await showView(view, { syncUrl: 'push' });
          menuDropdown.classList.remove('show');
        }
      });
    });

    window.addEventListener('popstate', () => {
      const v = initialViewFromLocation();
      void showView(v, { syncUrl: null });
    });

    // ========== ADMIN ==========
    const adminInviteEmail = document.getElementById('adminInviteEmail');
    const adminInviteBtn = document.getElementById('adminInviteBtn');
    const adminInviteResult = document.getElementById('adminInviteResult');

    adminInviteBtn.addEventListener('click', async () => {
      const email = (adminInviteEmail.value || '').trim();
      if (!email) {
        adminInviteResult.innerHTML = '<div class="message error">Saisissez une adresse e-mail.</div>';
        return;
      }
      adminInviteBtn.disabled = true;
      adminInviteResult.innerHTML = '<div class="message">Génération du lien…</div>';
      try {
        const fd = new FormData();
        fd.append('email', email);
        const res = await apiFetch(apiBase + '/api/admin/invite', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || res.statusText || 'Invitation échouée');
        const link = data.password_reset_link || '';
        adminInviteResult.innerHTML =
          '<div class="message">'
          + '<div><b>Utilisateur :</b> ' + (data.email || email) + '</div>'
          + '<div style="margin-top:8px;"><b>Lien de réinitialisation du mot de passe :</b></div>'
          + '<textarea rows="3" readonly style="margin-top:6px;">' + link + '</textarea>'
          + '<div class="file-source-info">Copiez ce lien et envoyez-le à l’utilisateur. Il définit son mot de passe puis se connecte avec e-mail et mot de passe.</div>'
          + '</div>';
      } catch (e) {
        const msg = e && e.message ? String(e.message) : 'Invitation échouée';
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
    function closeCinemaDetailModal() {
      resetCinemaDetailInlinePlayer();
      document.getElementById('cinemaDetailModal').classList.remove('show');
    }
    document.getElementById('cinemaDetailCloseBtn').addEventListener('click', () => closeCinemaDetailModal());
    document.getElementById('cinemaDetailPlayHit').addEventListener('click', () => void startCinemaDetailInlinePlay());
    document.getElementById('cinemaDetailLang').addEventListener('change', () => void syncCinemaDetailTrack());
    document.getElementById('cinemaDetailModal').addEventListener('click', (e) => {
      if (e.target.id === 'cinemaDetailModal') closeCinemaDetailModal();
    });
    document.getElementById('cinemaPublishModal').addEventListener('click', (e) => {
      if (e.target.id === 'cinemaPublishModal') {
        document.getElementById('cinemaPublishModal').classList.remove('show');
      }
    });

    document.getElementById('libraryVideoModalClose').addEventListener('click', () => closeLibraryVideoModal());
    document.getElementById('libraryVideoModal').addEventListener('click', (e) => {
      if (e.target.id === 'libraryVideoModal') closeLibraryVideoModal();
    });

    // ========== HOME: Transcribe & Translate ==========
    /** Lets the browser paint loading UI before heavy async work (fetch / upload). */
    function yieldForPaint() {
      return new Promise(function (resolve) {
        requestAnimationFrame(function () {
          requestAnimationFrame(resolve);
        });
      });
    }

    function restoreJobButton(submitBtn) {
      const lab = submitBtn.dataset.jobOrigLabel;
      submitBtn.disabled = false;
      if (lab !== undefined) submitBtn.textContent = lab;
      delete submitBtn.dataset.jobOrigLabel;
      submitBtn.classList.remove('job-running');
      submitBtn.removeAttribute('aria-busy');
    }

    /**
     * Immediate feedback: knop + blok met "Signaal ontvangen" en detailtekst.
     * jobOrigLabel wordt maar één keer gezet (bij tweede aanroep, o.a. na voorbereiding GCS, behouden we het label).
     */
    function beginJobUI(resultEl, submitBtn, detailMsg) {
      if (submitBtn.dataset.jobOrigLabel === undefined) {
        submitBtn.dataset.jobOrigLabel = submitBtn.textContent;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = 'En cours…';
      submitBtn.classList.add('job-running');
      submitBtn.setAttribute('aria-busy', 'true');
      const line = detailMsg || 'Chargement…';
      resultEl.innerHTML =
        '<div class="progress-wrap progress-wrap--active progress-wrap--flash" role="status" aria-live="polite" aria-atomic="true">'
        + '<div class="progress-ack">Demande reçue</div>'
        + '<div class="progress-live-title"><span class="progress-spinner" aria-hidden="true"></span> '
        + '<span>En cours…</span></div>'
        + '<div class="progress-bar progress-bar--waiting"><div class="progress-fill" style="width:0%"></div></div>'
        + '<div class="progress-msg"></div></div>';
      const msgEl0 = resultEl.querySelector('.progress-msg');
      if (msgEl0) msgEl0.textContent = line;
      try {
        resultEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (_) {}
      void resultEl.offsetHeight;
      return {
        fillEl: resultEl.querySelector('.progress-fill'),
        msgEl: resultEl.querySelector('.progress-msg'),
        barEl: resultEl.querySelector('.progress-bar'),
      };
    }

    /** Stem of basename (no path), safe for use in library filenames. */
    function libraryNameStemFromInput(inputFileName) {
      if (!inputFileName || typeof inputFileName !== 'string') return '';
      const base = inputFileName.replace(/^[\\/]+/, '').split(/[/\\]/).pop() || '';
      const dot = base.lastIndexOf('.');
      const stem = dot > 0 ? base.slice(0, dot) : base;
      return stem.replace(/[<>:"/\\|?*\x00-\x1f]+/g, '_').replace(/\s+/g, ' ').trim() || '';
    }

    /** Library / download name: {input stem}_{suffix}.{ext} — unique and recognizable. */
    function buildProcessedOutputFilename(inputFileName, librarySuffix, extWithDot) {
      const stem = libraryNameStemFromInput(inputFileName);
      const suf = String(librarySuffix || 'output').replace(/[<>:"/\\|?*\x00-\x1f\s]+/g, '_');
      const e = (extWithDot || '.vtt').startsWith('.') ? extWithDot : ('.' + extWithDot);
      return (stem || 'file') + '_' + suf + e;
    }

    function escAttr(s) {
      return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    }

    function escJs(s) {
      return String(s)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, '\\\'')
        .replace(/\r/g, '\\r')
        .replace(/\n/g, '\\n');
    }

    function escHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function closeAllLibMenus() {
      document.querySelectorAll('#libFileList .lib-menu-dropdown.open').forEach((d) => {
        d.classList.remove('open');
        d.hidden = true;
      });
    }

    function libModifierCinema(isFolder, mediaType, fileId) {
      closeAllLibMenus();
      if (isFolder) {
        alert('Non disponible pour les dossiers.');
        return;
      }
      if (!mediaType || !['video', 'text', 'audio'].includes(mediaType)) {
        alert('Le Cinéma accepte seulement des vidéos, fichiers texte (.txt) et audio (.mp3, .wav).');
        return;
      }
      openCinemaPublishModal(fileId);
    }

    function libMenuTelecharger(isFolder, fileId) {
      closeAllLibMenus();
      if (isFolder) {
        alert('Non disponible pour les dossiers.');
        return;
      }
      downloadLibFile(fileId);
    }

    async function duplicateLibFile(id) {
      closeAllLibMenus();
      try {
        const res = await apiFetch(apiBase + '/api/library/file/' + id + '/duplicate', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || ('Échec : ' + res.status));
        await loadLibrary();
      } catch (err) {
        alert('Duplication impossible : ' + (err.message || err));
      }
    }

    async function duplicateLibFolder(id) {
      closeAllLibMenus();
      try {
        const res = await apiFetch(apiBase + '/api/library/folder/' + id + '/duplicate', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || ('Échec : ' + res.status));
        await loadLibrary();
      } catch (err) {
        alert('Duplication impossible : ' + (err.message || err));
      }
    }

    async function renameLibFolder(id, currentName) {
      closeAllLibMenus();
      const name = prompt('Nouveau nom du dossier', currentName || '');
      if (!name) return;
      try {
        const fd = new FormData();
        fd.append('name', name);
        const res = await apiFetch(apiBase + '/api/library/folder/' + id + '/rename', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || ('Échec : ' + res.status));
        await loadLibrary();
      } catch (err) {
        alert('Renommage impossible : ' + (err.message || err));
      }
    }

    async function editFolderPermissions(id, currentEmailsJson) {
      closeAllLibMenus();
      const currentEmails = JSON.parse(currentEmailsJson || '[]');
      const emailsStr = prompt('Adresses e-mail autorisées (séparées par des virgules)', currentEmails.join(', '));
      if (emailsStr === null) return; // cancelled
      const emails = emailsStr.split(',').map(e => e.trim()).filter(e => e);
      try {
        const fd = new FormData();
        fd.append('allowed_emails', emails.join(','));
        const res = await apiFetch(apiBase + '/api/library/folder/' + id + '/permissions', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || ('Échec : ' + res.status));
        await loadLibrary();
      } catch (err) {
        alert('Modification des permissions impossible : ' + (err.message || err));
      }
    }

    (function bindLibFileListMenus() {
      const list = document.getElementById('libFileList');
      if (!list || list.dataset.libMenuBound === '1') return;
      list.dataset.libMenuBound = '1';
      list.addEventListener('click', (e) => {
        const btn = e.target.closest('.lib-menu-btn');
        if (!btn) return;
        e.stopPropagation();
        const wrap = btn.closest('.lib-actions-wrap');
        const drop = wrap && wrap.querySelector('.lib-menu-dropdown');
        if (!drop) return;
        const willOpen = !drop.classList.contains('open');
        document.querySelectorAll('#libFileList .lib-menu-dropdown.open').forEach((d) => {
          d.classList.remove('open');
          d.hidden = true;
        });
        if (willOpen) {
          drop.classList.add('open');
          drop.hidden = false;
        }
      });
    })();

    document.addEventListener('click', (e) => {
      if (e.target.closest('.lib-actions-wrap')) return;
      closeAllLibMenus();
    });

    /**
     * saveMeta (optional): { inputFileName, librarySuffix } — if set, download + Save to Library use
     * "{inputStem}_{librarySuffix}.ext" instead of a generic name (transcription, translated, …).
     */
    async function runJob(endpoint, formData, resultEl, submitBtn, downloadName, resultUrlSuffix, saveMeta) {
      resultUrlSuffix = resultUrlSuffix || '.vtt';
      let extForName = '.vtt';
      if (resultUrlSuffix === '.txt') extForName = '.txt';
      else if (resultUrlSuffix === '_burned.mp4') extForName = '.mp4';
      else if (resultUrlSuffix === '_tts.zip') extForName = '.zip';
      const finalDownloadName =
        saveMeta && saveMeta.inputFileName && saveMeta.librarySuffix
          ? buildProcessedOutputFilename(saveMeta.inputFileName, saveMeta.librarySuffix, extForName)
          : downloadName;
      function restoreSubmitBtn() {
        restoreJobButton(submitBtn);
      }
      const ui = beginJobUI(
        resultEl,
        submitBtn,
        'Connexion et envoi du fichier… (les gros fichiers peuvent prendre du temps)',
      );
      const fillEl = ui.fillEl;
      const msgEl = ui.msgEl;
      const barEl = ui.barEl;
      try {
        await yieldForPaint();
        const res = await apiFetch(apiBase + endpoint, { method: 'POST', body: formData });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || res.statusText || 'Échec du téléversement');
        const jobId = data.job_id;
        const statusUrl = apiBase + '/api/status/' + jobId;
        function formatEta(seconds) {
          if (seconds == null || seconds <= 0) return '';
          if (seconds >= 60) return ' (~' + Math.ceil(seconds / 60) + ' min)';
          return ' (~' + seconds + ' s)';
        }
        let statusPollErrors = 0;
        let intervalId = null;
        async function checkStatus() {
          try {
            const res = await apiFetch(statusUrl);
            if (!res.ok) {
              clearInterval(intervalId);
              restoreSubmitBtn();
              resultEl.innerHTML = '<div class="message error">Tâche introuvable. Le serveur a peut-être redémarré. Veuillez réessayer.</div>';
              return;
            }
            statusPollErrors = 0;
            const s = await res.json();
            if (barEl) {
              if ((s.progress || 0) > 0) barEl.classList.remove('progress-bar--waiting');
              else if (!s.done) barEl.classList.add('progress-bar--waiting');
            }
            if (fillEl) fillEl.style.width = (s.progress || 0) + '%';
            const etaStr = formatEta(s.eta_seconds);
            if (msgEl) msgEl.textContent = (s.progress || 0) + '% — ' + (s.message || '') + etaStr;
            if (s.done) {
              clearInterval(intervalId);
              restoreSubmitBtn();
              if (s.error) {
                resultEl.innerHTML = '<div class="message error">' + (s.error || s.message) + '</div>';
              } else {
                const downloadUrl = apiBase + '/api/result/' + jobId + resultUrlSuffix;
                const isBurn = resultUrlSuffix === '_burned.mp4';
                const isTxt = resultUrlSuffix === '.txt';
                const isTtsZip = resultUrlSuffix === '_tts.zip';
                const linkText = isBurn
                  ? 'Télécharger la vidéo'
                  : (isTtsZip ? 'Télécharger les audios (ZIP)' : (isTxt ? 'Télécharger le fichier TXT' : 'Télécharger le fichier VTT'));
                const warnEsc = (s.warning || '')
                  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                const warnBlock = s.warning
                  ? ('<div class="message error">' + warnEsc + '</div>')
                  : '';
                let html = warnBlock + '<div class="message">Terminé.';
                if (isTtsZip) {
                  html += ' <button type="button" class="small secondary save-tts-to-lib-btn" data-job-id="' + jobId + '">Enregistrer MP3 dans la bibliothèque</button>';
                } else {
                  html += ' <button type="button" class="small secondary download-result-btn" data-url="' + downloadUrl + '" data-filename="' + escAttr(finalDownloadName) + '">' + linkText + '</button>';
                }
                if (!isBurn && !isTtsZip) {
                  const suffix = resultUrlSuffix === '.txt' ? '.txt' : '.vtt';
                  html += ' <button type="button" class="small secondary save-to-lib-btn" data-job-id="' + jobId + '" data-filename="' + escAttr(finalDownloadName) + '" data-suffix="' + suffix + '">Enregistrer dans la bibliothèque</button>';
                }
                html += '</div>';
                resultEl.innerHTML = html;
              }
            }
          } catch (err) {
            statusPollErrors++;
            if (statusPollErrors >= 5) {
              clearInterval(intervalId);
              restoreSubmitBtn();
              resultEl.innerHTML = '<div class="message error">Connexion perdue pendant le suivi. ' + (err && err.message ? err.message : 'Veuillez réessayer.') + '</div>';
            }
          }
        }
        checkStatus();
        intervalId = setInterval(checkStatus, 1000);
      } catch (err) {
        resultEl.innerHTML = '<div class="message error">' + (err.message || 'Erreur') + '</div>';
        restoreSubmitBtn();
      }
    }

    // Handle file selection from computer
    document.getElementById('transcribeFileInput').addEventListener('change', function() {
      if (this.files.length) {
        transcribeSelectedFile = this.files[0];
        document.getElementById('transcribeFileInfo').textContent = transcribeSelectedFile.name;
        document.getElementById('transcribeFileInfo').classList.add('selected');
      }
    });

    document.getElementById('translateFileInput').addEventListener('change', function() {
      if (this.files.length) {
        translateSelectedFile = this.files[0];
        document.getElementById('translateFileInfo').textContent = translateSelectedFile.name;
        document.getElementById('translateFileInfo').classList.add('selected');
      }
    });

    document.getElementById('ttsFileInput').addEventListener('change', function() {
      if (this.files.length) {
        ttsSelectedFile = this.files[0];
        document.getElementById('ttsFileInfo').textContent = ttsSelectedFile.name;
        document.getElementById('ttsFileInfo').classList.add('selected');
      }
    });

    // Home quick upload (choose + upload are separate buttons)
    const homeUploadInput = document.getElementById('homeUploadInput');
    const homeChooseFileBtn = document.getElementById('homeChooseFileBtn');
    const homeUploadBtn = document.getElementById('homeUploadBtn');
    const homeUploadInfo = document.getElementById('homeUploadInfo');
    const homeUploadResult = document.getElementById('homeUploadResult');
    const homeUploadFilename = document.getElementById('homeUploadFilename');

    if (homeChooseFileBtn && homeUploadInput) {
      homeChooseFileBtn.addEventListener('click', () => homeUploadInput.click());
      homeUploadInput.addEventListener('change', function() {
        if (!this.files || !this.files.length) return;
        homeUploadSelectedFile = this.files[0];
        homeUploadInfo.textContent = homeUploadSelectedFile.name;
        homeUploadInfo.classList.add('selected');
      });
    }

    if (homeUploadBtn) {
      homeUploadBtn.addEventListener('click', async () => {
        if (!homeUploadSelectedFile) {
          homeUploadResult.innerHTML = '<div class="message error">Veuillez d’abord choisir un fichier.</div>';
          return;
        }
        beginJobUI(homeUploadResult, homeUploadBtn, 'Démarrage de l’envoi vers la bibliothèque…');
        const fillEl = homeUploadResult.querySelector('.progress-fill');
        const msgEl = homeUploadResult.querySelector('.progress-msg');
        const homeBarEl = homeUploadResult.querySelector('.progress-bar');
        try {
          await yieldForPaint();
          const desiredName = (homeUploadFilename && homeUploadFilename.value ? homeUploadFilename.value : '').trim();
          const host = (window.location.hostname || '').toLowerCase();
          const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
          const MAX_DIRECT_UPLOAD_MB = 25;
          const isLarge = !isLocalHost && (homeUploadSelectedFile.size || 0) > MAX_DIRECT_UPLOAD_MB * 1024 * 1024;

          let data = null;
          if (isLarge) {
            if (msgEl) msgEl.textContent = 'Demande d’URL de stockage…';
            const contentType = homeUploadSelectedFile.type || 'application/octet-stream';
            const urlForm = new FormData();
            urlForm.append('filename', homeUploadSelectedFile.name);
            urlForm.append('content_type', contentType);
            const initData = await createResumableSession(homeUploadSelectedFile.name, contentType);

            await uploadToSignedUrl(initData.session_url, contentType, homeUploadSelectedFile, (loaded, total) => {
              const pct = total ? Math.max(1, Math.min(95, Math.round((loaded / total) * 95))) : 1;
              if (fillEl) fillEl.style.width = pct + '%';
              if (msgEl) msgEl.textContent = 'Téléversement de la vidéo… ' + pct + '%';
            }, (state) => {
              if (!msgEl) return;
              if (state === 'paused') msgEl.textContent = 'Connexion perdue. Téléversement en pause, nouvelle tentative…';
              if (state === 'resuming') msgEl.textContent = 'Connexion rétablie. Téléversement repris…';
            });

            if (fillEl) fillEl.style.width = '97%';
            if (msgEl) msgEl.textContent = 'Import vers la bibliothèque…';
            const importForm = new FormData();
            importForm.append('object_name', initData.object_name);
            importForm.append('folder', '');
            if (desiredName) importForm.append('filename', desiredName);
            const importRes = await apiFetch(apiBase + '/api/library/import-gcs', { method: 'POST', body: importForm });
            data = await importRes.json().catch(() => ({}));
            if (!importRes.ok) throw new Error(data.detail || ('Import échoué : ' + importRes.status));
          } else {
            const formData = new FormData();
            formData.append('file', homeUploadSelectedFile);
            formData.append('folder', '');
            if (desiredName) formData.append('filename', desiredName);
            data = await uploadMultipartWithProgress(apiBase + '/api/library/upload', formData, (loaded, total) => {
              const pct = total ? Math.max(1, Math.min(99, Math.round((loaded / total) * 99))) : 1;
              if (fillEl) fillEl.style.width = pct + '%';
              if (msgEl) msgEl.textContent = 'Téléversement vers la bibliothèque… ' + pct + '%';
            });
          }

          if (fillEl) fillEl.style.width = '100%';
          homeUploadResult.innerHTML = '<div class="message">Enregistré dans la bibliothèque sous <b>' + (data.name || homeUploadSelectedFile.name) + '</b>.</div>';
          homeUploadSelectedFile = null;
          homeUploadInput.value = '';
          homeUploadInfo.textContent = 'Aucun fichier sélectionné';
          homeUploadInfo.classList.remove('selected');
          if (homeUploadFilename) homeUploadFilename.value = '';
          try { await loadLibrary(); } catch (_) {}
        } catch (err) {
          const msg = (err && err.message) ? err.message : 'Échec du téléversement';
          homeUploadResult.innerHTML = '<div class="message error">' + msg + '</div>';
        } finally {
          restoreJobButton(homeUploadBtn);
        }
      });
    }

    document.getElementById('transcribeForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const resultEl = document.getElementById('transcribeResult');
      const submitBtn = document.getElementById('transcribeBtn');
      if (!transcribeSelectedFile) {
        resultEl.innerHTML = '<div class="message error">Veuillez sélectionner un fichier.</div>';
        return;
      }
      const outRadio = document.querySelector('input[name="transcribeOutput"]:checked');
      const wantTxt = outRadio && outRadio.value === 'txt';
      const isolate = document.getElementById('transcribeIsolateVoice').checked ? 'true' : 'false';
      const f = transcribeSelectedFile;

      if (wantTxt) {
        if (f instanceof File) {
          const MAX_DIRECT_UPLOAD_MB = 25;
          const host = (window.location.hostname || '').toLowerCase();
          const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
          const isLarge = !isLocalHost && (f.size || 0) > MAX_DIRECT_UPLOAD_MB * 1024 * 1024;
          if (isLarge) {
            try {
              beginJobUI(resultEl, submitBtn, 'Préparation du téléversement…');
              await yieldForPaint();
              const contentType = f.type || 'application/octet-stream';
              const urlForm = new FormData();
              urlForm.append('filename', f.name);
              urlForm.append('content_type', contentType);
              const initRes = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: urlForm });
              if (!initRes.ok) {
                let detail = initRes.statusText || String(initRes.status);
                try {
                  const errBody = await initRes.json();
                  if (errBody.detail) detail = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
                } catch (_) {}
                throw new Error('URL signée échouée (' + initRes.status + ') : ' + detail);
              }
              const initData = await initRes.json();
              await uploadToSignedUrl(initData.session_url, contentType, f);
              const gcsForm = new FormData();
              gcsForm.append('object_name', initData.object_name);
              gcsForm.append('isolate_voice', isolate);
              await runJob('/api/transcribe-text-gcs', gcsForm, resultEl, submitBtn, 'transcript.txt', '.txt', {
                inputFileName: f.name,
                librarySuffix: 'transcript',
              });
              return;
            } catch (err) {
              resultEl.innerHTML = '<div class="message error">Téléversement via le stockage échoué : ' + (err.message || err) + '</div>';
              restoreJobButton(submitBtn);
              return;
            }
          }
          const formDataTxt = new FormData();
          formDataTxt.append('file', f);
          formDataTxt.append('isolate_voice', isolate);
          await runJob('/api/transcribe-text', formDataTxt, resultEl, submitBtn, 'transcript.txt', '.txt', {
            inputFileName: f.name,
            librarySuffix: 'transcript',
          });
          return;
        }
        try {
          const fdTxt = new FormData();
          fdTxt.append('file_id', f.libraryId);
          fdTxt.append('isolate_voice', isolate);
          await runJob('/api/transcribe-text-library', fdTxt, resultEl, submitBtn, 'transcript.txt', '.txt', {
            inputFileName: f.name,
            librarySuffix: 'transcript',
          });
        } catch (err) {
          resultEl.innerHTML = '<div class="message error">' + (err.message || 'Transcription échouée') + '</div>';
          restoreJobButton(submitBtn);
        }
        return;
      }

      // Sous-titres VTT
      const formData = new FormData();
      formData.append('isolate_voice', isolate);
      if (f instanceof File) {
        const MAX_DIRECT_UPLOAD_MB = 25;
        const host = (window.location.hostname || '').toLowerCase();
        const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
        const isLarge = !isLocalHost && (f.size || 0) > MAX_DIRECT_UPLOAD_MB * 1024 * 1024;
        if (isLarge) {
          try {
            beginJobUI(resultEl, submitBtn, 'Préparation du téléversement…');
            await yieldForPaint();
            const contentType = f.type || 'application/octet-stream';
            const urlForm = new FormData();
            urlForm.append('filename', f.name);
            urlForm.append('content_type', contentType);
            const initRes = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: urlForm });
            if (!initRes.ok) {
              let detail = initRes.statusText || String(initRes.status);
              try {
                const errBody = await initRes.json();
                if (errBody.detail) detail = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
              } catch (_) {}
              throw new Error('URL signée échouée (' + initRes.status + ') : ' + detail);
            }
            const initData = await initRes.json();
            await uploadToSignedUrl(initData.session_url, contentType, f);
            const gcsForm = new FormData();
            gcsForm.append('object_name', initData.object_name);
            gcsForm.append('isolate_voice', isolate);
            await runJob('/api/transcribe-gcs', gcsForm, resultEl, submitBtn, 'transcription.vtt', '.vtt', {
              inputFileName: f.name,
              librarySuffix: 'transcription',
            });
            return;
          } catch (err) {
            resultEl.innerHTML = '<div class="message error">Téléversement via le stockage échoué : ' + (err.message || err) + '</div>';
            restoreJobButton(submitBtn);
            return;
          }
        }
        formData.append('file', f);
      } else {
        const fd = new FormData();
        fd.append('file_id', f.libraryId);
        fd.append('isolate_voice', isolate);
        await runJob('/api/transcribe-library', fd, resultEl, submitBtn, 'transcription.vtt', '.vtt', {
          inputFileName: f.name,
          librarySuffix: 'transcription',
        });
        return;
      }
      await runJob('/api/transcribe', formData, resultEl, submitBtn, 'transcription.vtt', '.vtt', {
        inputFileName: f.name,
        librarySuffix: 'transcription',
      });
    });

    document.getElementById('translateForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const langs = Array.from(e.target.querySelectorAll('input[name="lang"]:checked')).map(c => c.value);
      if (!translateSelectedFile) {
        document.getElementById('translateResult').innerHTML = '<div class="message error">Veuillez sélectionner un fichier VTT ou TXT.</div>';
        return;
      }
      const selName = (translateSelectedFile.name || '').toLowerCase();
      if (!selName.endsWith('.vtt') && !selName.endsWith('.txt')) {
        document.getElementById('translateResult').innerHTML = '<div class="message error">Seuls les fichiers .vtt et .txt sont acceptés.</div>';
        return;
      }
      if (!langs.length) {
        document.getElementById('translateResult').innerHTML = '<div class="message error">Sélectionnez au moins une langue.</div>';
        return;
      }
      const formData = new FormData();
      if (translateSelectedFile instanceof File) {
        formData.append('file', translateSelectedFile);
      } else {
        try {
          beginJobUI(
            document.getElementById('translateResult'),
            document.getElementById('translateBtn'),
            'Récupération du fichier depuis la bibliothèque…',
          );
          await yieldForPaint();
          const blob = await fetchLibraryFileBlob(translateSelectedFile.libraryId);
          formData.append('file', blob, translateSelectedFile.name);
        } catch (err) {
          restoreJobButton(document.getElementById('translateBtn'));
          const wrap = document.getElementById('translateResult');
          wrap.innerHTML = '';
          const div = document.createElement('div');
          div.className = 'message error';
          div.textContent = 'Impossible de charger le fichier depuis la bibliothèque : ' + (err && err.message ? err.message : String(err));
          wrap.appendChild(div);
          return;
        }
      }
      formData.append('languages', langs.join(','));
      const isTxt = selName.endsWith('.txt');
      const resultSuffix = isTxt ? '.txt' : '.vtt';
      const defaultDownload = isTxt ? 'translated.txt' : 'subtitles.vtt';
      await runJob('/api/translate', formData, document.getElementById('translateResult'), document.getElementById('translateBtn'), defaultDownload, resultSuffix, {
        inputFileName: translateSelectedFile.name,
        librarySuffix: 'translated',
      });
    });

    document.getElementById('ttsForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const selectedLang = (e.target.querySelector('input[name="ttsLang"]:checked') || {}).value || '';
      const resultEl = document.getElementById('ttsResult');
      const submitBtn = document.getElementById('ttsBtn');
      if (!ttsSelectedFile) {
        resultEl.innerHTML = '<div class="message error">Veuillez sélectionner un fichier TXT ou VTT.</div>';
        return;
      }
      const selName = (ttsSelectedFile.name || '').toLowerCase();
      if (!selName.endsWith('.vtt') && !selName.endsWith('.txt')) {
        resultEl.innerHTML = '<div class="message error">Seuls les fichiers .vtt et .txt sont acceptés.</div>';
        return;
      }
      if (!selectedLang) {
        resultEl.innerHTML = '<div class="message error">Sélectionnez une langue.</div>';
        return;
      }
      const formData = new FormData();
      if (ttsSelectedFile instanceof File) {
        formData.append('file', ttsSelectedFile);
        formData.append('languages', selectedLang);
        await runJob('/api/tts-generate', formData, resultEl, submitBtn, 'tts_audio.zip', '_tts.zip', {
          inputFileName: ttsSelectedFile.name,
          librarySuffix: 'tts_audio',
        });
      } else {
        formData.append('file_id', ttsSelectedFile.libraryId);
        formData.append('languages', selectedLang);
        await runJob('/api/tts-generate-library', formData, resultEl, submitBtn, 'tts_audio.zip', '_tts.zip', {
          inputFileName: ttsSelectedFile.name,
          librarySuffix: 'tts_audio',
        });
      }
    });

    // Burn into video
    document.getElementById('burnVideoInput').addEventListener('change', function() {
      if (this.files.length) {
        burnVideoSelected = this.files[0];
        document.getElementById('burnVideoInfo').textContent = burnVideoSelected.name;
        document.getElementById('burnVideoInfo').classList.add('selected');
      }
    });
    document.getElementById('burnVttInput').addEventListener('change', function() {
      if (this.files.length) {
        burnVttSelected = this.files[0];
        document.getElementById('burnVttInfo').textContent = burnVttSelected.name;
        document.getElementById('burnVttInfo').classList.add('selected');
      }
    });
    document.getElementById('burnForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!burnVideoSelected || !burnVttSelected) {
        document.getElementById('burnResult').innerHTML = '<div class="message error">Veuillez sélectionner une vidéo et un fichier VTT.</div>';
        return;
      }

      const burnResultEl = document.getElementById('burnResult');
      const burnBtn = document.getElementById('burnBtn');
      const host = (window.location.hostname || '').toLowerCase();
      const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
      const MAX_DIRECT_UPLOAD_MB = 25;
      const isLargeVideo = (burnVideoSelected instanceof File) && !isLocalHost && (burnVideoSelected.size || 0) > MAX_DIRECT_UPLOAD_MB * 1024 * 1024;

      if (isLargeVideo) {
        // Cloud Run request size limits: upload video+vtt to GCS first, then burn from GCS.
        try {
          if (burnBtn) {
            burnBtn.disabled = true;
            burnBtn.classList.add('job-running');
            burnBtn.setAttribute('aria-busy', 'true');
          }
          if (burnResultEl) {
            burnResultEl.innerHTML =
              '<div class="progress-wrap progress-wrap--active" role="status" aria-live="polite" aria-atomic="true">'
              + '<div class="progress-live-title"><span class="progress-spinner" aria-hidden="true"></span> '
              + '<span>Traitement…</span></div>'
              + '<div class="progress-bar progress-bar--waiting"><div class="progress-fill" style="width:0%"></div></div>'
              + '<div class="progress-msg">Téléversement vers le stockage… (cela peut prendre du temps pour les grosses vidéos)</div></div>';
            try {
              burnResultEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } catch (_) {}
          }
          const uploadFillEl = burnResultEl ? burnResultEl.querySelector('.progress-fill') : null;
          const uploadMsgEl = burnResultEl ? burnResultEl.querySelector('.progress-msg') : null;
          const videoType = burnVideoSelected.type || 'application/octet-stream';
          const vttType = (burnVttSelected instanceof File ? (burnVttSelected.type || 'text/vtt') : 'text/vtt');

          const vUrlForm = new FormData();
          vUrlForm.append('filename', burnVideoSelected.name);
          vUrlForm.append('content_type', videoType);
          const vInitRes = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: vUrlForm });
          const vInitData = await vInitRes.json().catch(() => ({}));
          if (!vInitRes.ok) throw new Error(vInitData.detail || ('URL signée échouée (' + vInitRes.status + ')'));

          const sUrlForm = new FormData();
          const vttName = (burnVttSelected instanceof File) ? burnVttSelected.name : burnVttSelected.name;
          sUrlForm.append('filename', vttName);
          sUrlForm.append('content_type', vttType);
          const sInitRes = await apiFetch(apiBase + '/api/gcs/resumable-session', { method: 'POST', body: sUrlForm });
          const sInitData = await sInitRes.json().catch(() => ({}));
          if (!sInitRes.ok) throw new Error(sInitData.detail || ('URL signée échouée (' + sInitRes.status + ')'));

          // Upload video to GCS
          await uploadToSignedUrl(vInitData.session_url, videoType, burnVideoSelected, (loaded, total) => {
            const pct = total ? Math.max(1, Math.min(90, Math.round((loaded / total) * 90))) : 1;
            if (uploadFillEl) uploadFillEl.style.width = pct + '%';
            if (uploadMsgEl) uploadMsgEl.textContent = 'Téléversement de la vidéo… ' + pct + '%';
          });

          // Upload VTT (from computer or library)
          let vttBlob = null;
          if (burnVttSelected instanceof File) vttBlob = burnVttSelected;
          else {
            vttBlob = await fetchLibraryFileBlob(burnVttSelected.libraryId);
          }
          await uploadToSignedUrl(sInitData.session_url, vttType, vttBlob, (loaded, total) => {
            const frac = total ? (loaded / total) : 1;
            const pct = Math.max(91, Math.min(99, 91 + Math.round(frac * 8)));
            if (uploadFillEl) uploadFillEl.style.width = pct + '%';
            if (uploadMsgEl) uploadMsgEl.textContent = 'Téléversement des sous-titres… ' + pct + '%';
          });

          const gcsForm = new FormData();
          gcsForm.append('video_object_name', vInitData.object_name);
          gcsForm.append('vtt_object_name', sInitData.object_name);
          await runJob('/api/burn-gcs', gcsForm, burnResultEl, burnBtn, 'video_with_subtitles.mp4', '_burned.mp4', {
            inputFileName: burnVideoSelected.name,
            librarySuffix: 'burned',
          });
          return;
        } catch (err) {
          if (burnResultEl) burnResultEl.innerHTML = '<div class="message error">Incrustation via le stockage échouée : ' + (err.message || err) + '</div>';
          if (burnBtn) {
            burnBtn.disabled = false;
            burnBtn.classList.remove('job-running');
            burnBtn.removeAttribute('aria-busy');
          }
          return;
        }
      }

      // Normal multipart upload (small enough)
      const formData = new FormData();
      if (burnVideoSelected instanceof File) {
        formData.append('video', burnVideoSelected);
      } else {
        try {
          const blob = await fetchLibraryFileBlob(burnVideoSelected.libraryId);
          formData.append('video', blob, burnVideoSelected.name);
        } catch (err) {
          const wrap = document.getElementById('burnResult');
          wrap.innerHTML = '';
          const div = document.createElement('div');
          div.className = 'message error';
          div.textContent = 'Impossible de charger la vidéo depuis la bibliothèque : ' + (err && err.message ? err.message : String(err));
          wrap.appendChild(div);
          return;
        }
      }
      if (burnVttSelected instanceof File) {
        formData.append('vtt', burnVttSelected);
      } else {
        try {
          const blob = await fetchLibraryFileBlob(burnVttSelected.libraryId);
          formData.append('vtt', blob, burnVttSelected.name);
        } catch (err) {
          const wrap = document.getElementById('burnResult');
          wrap.innerHTML = '';
          const div = document.createElement('div');
          div.className = 'message error';
          div.textContent = 'Impossible de charger le VTT depuis la bibliothèque : ' + (err && err.message ? err.message : String(err));
          wrap.appendChild(div);
          return;
        }
      }
      await runJob('/api/burn', formData, document.getElementById('burnResult'), document.getElementById('burnBtn'), 'video_with_subtitles.mp4', '_burned.mp4', {
        inputFileName: burnVideoSelected.name,
        librarySuffix: 'burned',
      });
    });

    // (Convert 720p + standalone player removed; Workspace provides video+VTT preview.)

    // ========== WORKSPACE ==========
    const wsEditor = document.getElementById('workspaceEditor');
    const wsFilename = document.getElementById('workspaceFilename');
    const wsTargetFolder = document.getElementById('workspaceTargetFolder');
    const wsVideoInput = document.getElementById('workspaceVideoInput');
    const wsVideoEl = document.getElementById('workspaceVideo');
    const wsVideoInfo = document.getElementById('workspaceVideoInfo');
    let wsVttBlobUrl = null;
    let wsVideoObjectUrl = null;
    let workspaceVttDebounceTimer = null;

    function setWorkspaceSubtitlesFromText(vttText) {
      if (!wsVideoEl) return;
      const text = (vttText == null ? '' : String(vttText));
      const blob = new Blob([text], { type: 'text/vtt' });

      if (wsVttBlobUrl) URL.revokeObjectURL(wsVttBlobUrl);
      wsVttBlobUrl = URL.createObjectURL(blob);

      // Don't reload the video; keep playback position.
      const keepTime = wsVideoEl.currentTime || 0;
      const wasPaused = wsVideoEl.paused;

      let track = wsVideoEl.querySelector('track');
      if (!track) {
        track = document.createElement('track');
        track.kind = 'subtitles';
        track.default = true;
        track.label = 'Sous-titres';
        wsVideoEl.appendChild(track);
      }
      track.src = wsVttBlobUrl;
      track.label = 'Sous-titres';

      // Update cues without reloading the whole video element.
      // Some browsers handle this automatically; restoring time avoids visible jumps.
      try { wsVideoEl.currentTime = keepTime; } catch (_) {}
      if (!wasPaused) {
        wsVideoEl.play().catch(() => {});
      }
    }

    function clearWorkspaceVideoSubtitleTrack() {
      if (!wsVideoEl) return;
      if (wsVttBlobUrl) {
        try { URL.revokeObjectURL(wsVttBlobUrl); } catch (_) {}
        wsVttBlobUrl = null;
      }
      const track = wsVideoEl.querySelector('track');
      if (track) track.remove();
    }

    async function loadWorkspaceFolders() {
      try {
        const folders = await fetchAllFolderPaths('');
        // Keep current selection if possible
        const current = wsTargetFolder.value || '';
        let html = '<option value=\"\">Racine</option>';
        for (const p of folders) {
          html += '<option value=\"' + p + '\">' + p + '</option>';
        }
        wsTargetFolder.innerHTML = html;
        wsTargetFolder.value = folders.includes(current) ? current : '';
      } catch (_) {
        // If library not reachable, keep Root option only
        wsTargetFolder.innerHTML = '<option value=\"\">Racine</option>';
      }
    }

    async function fetchAllFolderPaths(path) {
      const res = await apiFetch(apiBase + '/api/library?path=' + encodeURIComponent(path || ''));
      if (!res.ok) return [];
      const data = await res.json();
      const out = [];
      for (const f of (data.folders || [])) {
        if (f.path) out.push(f.path);
        const sub = await fetchAllFolderPaths(f.path);
        out.push(...sub);
      }
      // Sort once at top level; recursion returns already collected
      if (!path) out.sort((a, b) => a.localeCompare(b));
      return out;
    }

    document.getElementById('workspaceFileInput').addEventListener('change', function () {
      if (!this.files.length) return;
      const file = this.files[0];
      wsFilename.value = file.name;
      const reader = new FileReader();
      reader.onload = () => {
        wsEditor.value = reader.result;
        const n = (file.name || '').toLowerCase();
        if (n.endsWith('.vtt')) {
          setWorkspaceSubtitlesFromText(reader.result);
        } else {
          clearWorkspaceVideoSubtitleTrack();
        }
      };
      reader.readAsText(file, 'utf-8');
    });

    document.getElementById('workspaceClearBtn').addEventListener('click', () => {
      wsEditor.value = '';
      wsFilename.value = 'subtitles.vtt';
      setWorkspaceSubtitlesFromText('WEBVTT\n\n');
    });

    if (wsVideoInput) {
      wsVideoInput.addEventListener('change', function () {
        if (!this.files.length) return;
        if (wsVideoObjectUrl) {
          try { URL.revokeObjectURL(wsVideoObjectUrl); } catch (_) {}
          wsVideoObjectUrl = null;
        }
        wsVideoObjectUrl = URL.createObjectURL(this.files[0]);
        wsVideoEl.src = wsVideoObjectUrl;
        if (wsVideoInfo) {
          wsVideoInfo.textContent = this.files[0].name;
          wsVideoInfo.classList.add('selected');
        }
      });
    }

    async function loadWorkspaceVideoFromLibrary(id, displayName) {
      try {
        const tok = await ensureIdToken();
        if (!tok) {
          alert('Connexion requise');
          return;
        }
        if (wsVideoObjectUrl) {
          try { URL.revokeObjectURL(wsVideoObjectUrl); } catch (_) {}
          wsVideoObjectUrl = null;
        }
        if (wsVideoInput) wsVideoInput.value = '';
        wsVideoEl.src = apiBase + '/api/library/file/' + encodeURIComponent(id) + '?token=' + encodeURIComponent(tok);
        if (wsVideoInfo) {
          wsVideoInfo.textContent = (displayName || 'Vidéo') + ' (Bibliothèque)';
          wsVideoInfo.classList.add('selected');
        }
      } catch (err) {
        alert('Impossible de charger la vidéo : ' + (err.message || err));
      }
    }

    wsEditor.addEventListener('input', () => {
      if (workspaceVttDebounceTimer) clearTimeout(workspaceVttDebounceTimer);
      workspaceVttDebounceTimer = setTimeout(() => {
        const name = (wsFilename.value || '').toLowerCase();
        if (name.endsWith('.vtt')) setWorkspaceSubtitlesFromText(wsEditor.value);
        else clearWorkspaceVideoSubtitleTrack();
      }, 500);
    });

    document.getElementById('workspaceDownloadBtn').addEventListener('click', () => {
      const content = wsEditor.value;
      const filename = wsFilename.value || 'subtitles.vtt';
      const lower = String(filename).toLowerCase();
      const type = lower.endsWith('.txt') ? 'text/plain' : 'text/vtt';
      const blob = new Blob([content], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    });

    document.getElementById('workspaceSaveToLibraryBtn').addEventListener('click', async () => {
      try {
        const content = wsEditor.value || '';
        const filename = (wsFilename.value || 'subtitles.vtt').trim() || 'subtitles.vtt';
        const folder = (wsTargetFolder.value || '').trim();
        const lower = filename.toLowerCase();
        const blobType = lower.endsWith('.txt') ? 'text/plain' : 'text/vtt';
        const blob = new Blob([content], { type: blobType });
        const formData = new FormData();
        formData.append('file', blob, filename);
        formData.append('folder', folder); // save in selected folder
        const res = await apiFetch(apiBase + '/api/library/upload', { method: 'POST', body: formData });
        if (!res.ok) throw new Error('Échec du téléversement : ' + res.status);
        const data = await res.json().catch(() => ({}));
        if (data.overwritten) alert('Enregistré. Le fichier existant dans la bibliothèque a été remplacé.');
        else alert('Enregistré comme nouveau fichier dans la bibliothèque.');
      } catch (err) {
        alert('Impossible d’enregistrer dans la bibliothèque : ' + (err.message || err));
      }
    });

    // ========== LIBRARY ==========
    async function loadLibrary() {
      try {
        const res = await apiFetch(apiBase + '/api/library?path=' + encodeURIComponent(currentLibPath));
        if (!res.ok) throw new Error('Le serveur a répondu ' + res.status);
        const data = await res.json();
        renderLibrary(data);
      } catch (err) {
        document.getElementById('libFileList').innerHTML = '<div class="message error">Erreur de chargement de la bibliothèque : ' + err.message + '</div>';
      }
    }

    function renderLibrary(data) {
      // Breadcrumb (segments are drop targets: data-lib-path = folder path after drop)
      const bc = document.getElementById('libBreadcrumb');
      const parts = data.path ? data.path.split('/') : [];
      let bcHtml = '<span class="lib-bc-drop-target" data-lib-path="" title="Déposer ici → Racine"><a href="#" onclick="navigateLib(\'\'); return false;">Racine</a></span>';
      let pathSoFar = '';
      for (const p of parts) {
        pathSoFar += (pathSoFar ? '/' : '') + p;
        bcHtml += ' / <span class="lib-bc-drop-target" data-lib-path="' + escAttr(pathSoFar) + '" title="Déposer ici → ' + escAttr(pathSoFar) + '"><a href="#" onclick="navigateLib(\'' + pathSoFar + '\'); return false;">' + p + '</a></span>';
      }
      bc.innerHTML = bcHtml;

      // File list
      const list = document.getElementById('libFileList');
      if (!data.folders.length && !data.files.length) {
        list.innerHTML = '<div class="empty-msg">Ce dossier est vide.</div>';
        return;
      }
      let html = '';
      for (const folder of data.folders) {
        const fp = escJs(folder.path);
        const fn = escJs(folder.name);
        html += '<div class="file-item lib-folder-row lib-drop-target" data-lib-path="' + escAttr(folder.path) + '" title="Déposer un fichier ici">';
        html += '<div class="file-icon">📁</div>';
        html += '<div class="file-name" onclick="navigateLib(\'' + fp + '\')">' + escHtml(folder.name) + '</div>';
        html += '<div class="lib-actions-wrap file-actions">';
        html += '<button type="button" draggable="false" class="lib-menu-btn secondary" aria-label="Actions" title="Actions">⋮</button>';
        html += '<div class="lib-menu-dropdown" role="menu" hidden>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); deleteFolder(\'' + folder.id + '\')">Supprimer</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); navigateLib(\'' + fp + '\')">Ouvrir / modifier</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="libModifierCinema(true, \'\', \'\')">Modifier Cinéma</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); renameLibFolder(\'' + folder.id + '\', \'' + fn + '\')">Renommer</button>';
        if (isAdmin) {
          html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); editFolderPermissions(\'' + folder.id + '\', \'' + escJs(JSON.stringify(folder.allowed_emails || [])) + '\')">Permissions</button>';
        }
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); duplicateLibFolder(\'' + folder.id + '\')">Dupliquer</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="libMenuTelecharger(true, \'\')">Télécharger</button>';
        html += '</div></div></div>';
      }
      for (const file of data.files) {
        const icon = file.type === 'vtt' ? '📄' : (file.type === 'text' ? '📝' : (file.type === 'audio' ? '🎵' : '🎬'));
        let openFn = 'downloadLibFile(\'' + file.id + '\')';
        if (file.type === 'vtt') openFn = 'editInWorkspace(\'' + file.id + '\')';
        else if (file.type === 'text') openFn = 'openTextInWorkspace(\'' + file.id + '\')';
        else if (file.type === 'video') openFn = 'openVideoInWorkspace(\'' + file.id + '\', \'' + escJs(file.name || '') + '\')';
        html += '<div class="file-item lib-file-row" draggable="true" data-file-id="' + escAttr(file.id) + '" title="Maintenir et glisser vers un dossier">';
        html += '<div class="file-icon">' + icon + '</div>';
        html += '<div class="file-name" onclick="downloadLibFile(\'' + file.id + '\')">' + escHtml(file.name) + '</div>';
        html += '<div class="lib-actions-wrap file-actions">';
        html += '<button type="button" draggable="false" class="lib-menu-btn secondary" aria-label="Actions" title="Actions">⋮</button>';
        html += '<div class="lib-menu-dropdown" role="menu" hidden>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); deleteLibFile(\'' + file.id + '\')">Supprimer</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); ' + openFn + '">Ouvrir / modifier</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="libModifierCinema(false, \'' + file.type + '\', \'' + file.id + '\')">Modifier Cinéma</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); renameLibFile(\'' + file.id + '\', \'' + escJs(file.name || '') + '\')">Renommer</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="closeAllLibMenus(); duplicateLibFile(\'' + file.id + '\')">Dupliquer</button>';
        html += '<button type="button" class="lib-menu-item" role="menuitem" onclick="libMenuTelecharger(false, \'' + file.id + '\')">Télécharger</button>';
        html += '</div></div></div>';
      }
      list.innerHTML = html;
    }

    const CINEMA_LANG_ROWS = [
      ['nl', 'Néerlandais'], ['en', 'Anglais'], ['es', 'Espagnol'], ['fr', 'Français'],
      ['mg', 'Malgache'], ['kg', 'Kikongo'], ['ts', 'Tshiluba'], ['ln', 'Lingala'],
      ['pt', 'Portugais'], ['zh', 'Chinois'], ['sw', 'Swahili'],
    ];
    let lastCinemaCatalog = null;
    let lastCinemaAllItems = [];
    let selectedCinemaFeaturedId = '';
    let cinemaDetailItem = null;
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
      const covSel = document.getElementById('cinemaCoverType');
      const subsec = document.getElementById('cinemaSubtitleSection');
      covSel.innerHTML =
        '<option value="frame">Image extraite de la vidéo à la seconde…</option>' +
        '<option value="upload">Téléverser une image (JPEG/PNG)</option>';
      subsec.style.display = '';
      try {
        const metaRes = await apiFetch(apiBase + '/api/library/file/' + fileId + '/cinema');
        const metaData = await metaRes.json().catch(() => ({}));
        if (!metaRes.ok) throw new Error(metaData.detail || ('Erreur HTTP ' + metaRes.status));
        const fileType = metaData.file_type || 'video';
        document.getElementById('cinemaPublishFileType').value = fileType;
        document.getElementById('cinemaPublishTitle').value = metaData.cinema_title || '';
        document.getElementById('cinemaPublishDesc').value = metaData.cinema_description || '';
        const rows = document.getElementById('cinemaSubtitleRows');
        rows.innerHTML = '';
        if (fileType === 'video') {
          const vttRes = await apiFetch(apiBase + '/api/library/vtt-list');
          const vttData = await vttRes.json().catch(() => ({}));
          if (!vttRes.ok) throw new Error(vttData.detail || 'Impossible de charger la liste des VTT');
          document.getElementById('cinemaCoverType').value = metaData.cinema_cover_type === 'upload' ? 'upload' : 'frame';
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
              opt.textContent = '(fichier manquant) ' + subs[code];
              opt.selected = true;
              sel.appendChild(opt);
            }
            rows.appendChild(row);
          }
        } else {
          subsec.style.display = 'none';
          covSel.innerHTML = '<option value="upload">Téléverser une image (JPEG/PNG)</option>';
          document.getElementById('cinemaCoverType').value = 'upload';
        }
        document.getElementById('cinemaCoverSecond').value = String(metaData.cinema_cover_second ?? 0);
        syncCinemaCoverUi();
        document.getElementById('cinemaPublishModal').classList.add('show');
      } catch (err) {
        alert('Impossible d’ouvrir le Cinéma : ' + (err.message || err));
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
        alert('Publication échouée : ' + (err.message || err));
      }
    }

    async function unpublishCinemaFromModal() {
      const fileId = document.getElementById('cinemaPublishFileId').value;
      if (!confirm('Retirer ce contenu du Cinéma ?')) return;
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
        alert('Retrait échoué : ' + (err.message || err));
      }
    }

    function openCinemaDetailById(itemId) {
      const item = lastCinemaAllItems.find((v) => v.id === itemId);
      if (item) void openCinemaDetail(item);
    }

    function getCinemaDetailVttId(langCode) {
      if (!cinemaDetailItem || !cinemaDetailItem.languages) return null;
      const L = cinemaDetailItem.languages.find((x) => x.code === langCode);
      return (L && L.vtt_id) ? L.vtt_id : null;
    }

    function resetCinemaDetailInlinePlayer() {
      const v = document.getElementById('cinemaDetailInlinePlayer');
      const a = document.getElementById('cinemaDetailAudioPlayer');
      const posterLayer = document.getElementById('cinemaDetailPosterLayer');
      if (v) {
        try { v.pause(); } catch (_) {}
        while (v.firstChild) v.removeChild(v.firstChild);
        v.removeAttribute('src');
        v.classList.add('cinema-detail-video-hidden');
        try { v.load(); } catch (_) {}
      }
      if (a) {
        try { a.pause(); } catch (_) {}
        a.removeAttribute('src');
        a.classList.add('cinema-detail-audio-hidden');
        try { a.load(); } catch (_) {}
      }
      if (posterLayer) posterLayer.style.display = '';
    }

    async function startCinemaDetailInlinePlay() {
      if (!cinemaDetailItem) return;
      const tok = await ensureIdToken();
      if (!tok) {
        alert('Connexion requise');
        return;
      }
      const kind = cinemaDetailItem.kind || 'video';
      const posterLayer = document.getElementById('cinemaDetailPosterLayer');
      if (kind === 'ebook') {
        window.open(
          apiBase + '/api/cinema/read/' + encodeURIComponent(cinemaDetailItem.id) + '?token=' + encodeURIComponent(tok),
          '_blank',
        );
        return;
      }
      if (kind === 'audio') {
        const a = document.getElementById('cinemaDetailAudioPlayer');
        const v = document.getElementById('cinemaDetailInlinePlayer');
        if (v) {
          try { v.pause(); } catch (_) {}
          v.classList.add('cinema-detail-video-hidden');
        }
        if (!a || !posterLayer) return;
        a.src = apiBase + '/api/cinema/audio/' + encodeURIComponent(cinemaDetailItem.id) + '?token=' + encodeURIComponent(tok);
        a.classList.remove('cinema-detail-audio-hidden');
        posterLayer.style.display = 'none';
        try { await a.play(); } catch (_) {}
        return;
      }
      const lang = document.getElementById('cinemaDetailLang').value || 'none';
      const v = document.getElementById('cinemaDetailInlinePlayer');
      const a = document.getElementById('cinemaDetailAudioPlayer');
      if (a) {
        try { a.pause(); } catch (_) {}
        a.classList.add('cinema-detail-audio-hidden');
        a.removeAttribute('src');
      }
      if (!v || !posterLayer) return;
      while (v.firstChild) v.removeChild(v.firstChild);
      if (lang !== 'none') {
        const vttId = getCinemaDetailVttId(lang);
        if (vttId) {
          const track = document.createElement('track');
          track.kind = 'captions';
          track.label = 'Sous-titres';
          track.default = true;
          track.src = apiBase + '/api/cinema/vtt/' + encodeURIComponent(vttId) + '?token=' + encodeURIComponent(tok);
          v.appendChild(track);
        }
      }
      v.src = apiBase + '/api/cinema/video/' + encodeURIComponent(cinemaDetailItem.id) + '?token=' + encodeURIComponent(tok);
      v.classList.remove('cinema-detail-video-hidden');
      posterLayer.style.display = 'none';
      try { await v.play(); } catch (_) {}
    }

    async function syncCinemaDetailTrack() {
      if (!cinemaDetailItem || cinemaDetailItem.kind !== 'video') return;
      const v = document.getElementById('cinemaDetailInlinePlayer');
      if (!v || v.classList.contains('cinema-detail-video-hidden') || !v.src) return;
      const tok = await ensureIdToken();
      if (!tok) return;
      const lang = document.getElementById('cinemaDetailLang').value;
      while (v.firstChild) v.removeChild(v.firstChild);
      if (lang !== 'none') {
        const vttId = getCinemaDetailVttId(lang);
        if (vttId) {
          const track = document.createElement('track');
          track.kind = 'captions';
          track.label = 'Sous-titres';
          track.default = true;
          track.src = apiBase + '/api/cinema/vtt/' + encodeURIComponent(vttId) + '?token=' + encodeURIComponent(tok);
          v.appendChild(track);
        }
      }
      try {
        v.load();
        v.play().catch(() => {});
      } catch (_) {}
    }

    async function openCinemaDetail(item) {
      cinemaDetailItem = item;
      resetCinemaDetailInlinePlayer();
      if (cinemaDetailBlobUrl) {
        try { URL.revokeObjectURL(cinemaDetailBlobUrl); } catch (_) {}
        cinemaDetailBlobUrl = null;
      }
      const kind = item.kind || 'video';
      const langWrap = document.getElementById('cinemaDetailLangWrap');
      const playHit = document.getElementById('cinemaDetailPlayHit');
      if (langWrap) langWrap.style.display = kind === 'video' ? '' : 'none';
      if (playHit) {
        playHit.style.display = '';
        const labels = { video: 'Lire la vidéo', audio: 'Lire l’audio', ebook: 'Lire le texte' };
        playHit.setAttribute('aria-label', labels[kind] || 'Lire');
      }
      document.getElementById('cinemaDetailTitle').textContent = item.title || item.name;
      document.getElementById('cinemaDetailDesc').textContent = item.description || '';
      const sel = document.getElementById('cinemaDetailLang');
      sel.innerHTML = '';
      const langs = item.languages || [];
      if (!langs.length) {
        const opt = document.createElement('option');
        opt.value = 'none';
        opt.textContent = 'Aucun sous-titre';
        sel.appendChild(opt);
      } else {
        for (const L of langs) {
          const opt = document.createElement('option');
          opt.value = L.code;
          opt.textContent = L.name;
          sel.appendChild(opt);
        }
      }
      const imgEl = document.getElementById('cinemaDetailPosterImg');
      const emptyEl = document.getElementById('cinemaDetailPosterEmpty');
      imgEl.style.display = 'none';
      emptyEl.style.display = 'none';
      imgEl.removeAttribute('src');
      if (item.cover_url) {
        try {
          const res = await apiFetch(apiBase + item.cover_url);
          if (res.ok) {
            const blob = await res.blob();
            cinemaDetailBlobUrl = URL.createObjectURL(blob);
            imgEl.src = cinemaDetailBlobUrl;
            imgEl.alt = '';
            imgEl.style.display = 'block';
          } else {
            emptyEl.style.display = 'block';
          }
        } catch (_) {
          emptyEl.style.display = 'block';
        }
      } else {
        emptyEl.style.display = 'block';
      }
      document.getElementById('cinemaDetailModal').classList.add('show');
    }

    async function renameLibFile(id, currentName) {
      const name = prompt('Nouveau nom de fichier', currentName || '');
      if (!name) return;
      try {
        const fd = new FormData();
        fd.append('name', name);
        const res = await apiFetch(apiBase + '/api/library/file/' + id + '/rename', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || ('Renommage échoué : ' + res.status));
        loadLibrary();
      } catch (err) {
        alert('Renommage échoué : ' + (err.message || err));
      }
    }

    function closeLibraryVideoModal() {
      const modal = document.getElementById('libraryVideoModal');
      const player = document.getElementById('libraryVideoPlayer');
      if (player) {
        try { player.pause(); } catch (_) {}
        player.removeAttribute('src');
        player.load();
      }
      if (modal) modal.classList.remove('show');
    }

    async function openVideoInWorkspace(id, name) {
      try {
        const tok = await ensureIdToken();
        if (!tok) {
          alert('Connexion requise');
          return;
        }
        const modal = document.getElementById('libraryVideoModal');
        const player = document.getElementById('libraryVideoPlayer');
        const titleEl = document.getElementById('libraryVideoModalTitle');
        if (!modal || !player) return;
        if (titleEl) titleEl.textContent = name || 'Vidéo';
        player.src = apiBase + '/api/library/file/' + encodeURIComponent(id) + '?token=' + encodeURIComponent(tok);
        modal.classList.add('show');
        try { await player.play(); } catch (_) {}
      } catch (err) {
        alert('Impossible d’ouvrir la vidéo : ' + (err.message || err));
      }
    }

    async function loadCinema() {
      try {
        const res = await apiFetch(apiBase + '/api/cinema/catalog');
        if (!res.ok) throw new Error('Le serveur a répondu ' + res.status);
        const data = await res.json();
        lastCinemaCatalog = data;
        lastCinemaAllItems = [];
        if (data.featured) lastCinemaAllItems.push(data.featured);
        for (const x of data.videos || []) lastCinemaAllItems.push(x);
        for (const x of data.ebooks || []) lastCinemaAllItems.push(x);
        for (const x of data.audios || []) lastCinemaAllItems.push(x);
        if (!selectedCinemaFeaturedId || !lastCinemaAllItems.some((x) => x.id === selectedCinemaFeaturedId)) {
          selectedCinemaFeaturedId = data.featured && data.featured.id ? data.featured.id : (lastCinemaAllItems[0] && lastCinemaAllItems[0].id) || '';
        }
        await renderCinema(data);
      } catch (err) {
        document.getElementById('cinemaContent').innerHTML = '<div class="message error cinema-err">Erreur de chargement du Cinéma : ' + err.message + '</div>';
      }
    }

    function cinemaPlaceholderIcon(kind) {
      if (kind === 'ebook') return '📖';
      if (kind === 'audio') return '🎵';
      return '▶';
    }

    async function fillCinemaThumb(el, item) {
      if (!el) return;
      if (item.cover_url) {
        try {
          const res = await apiFetch(apiBase + item.cover_url);
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
      if (!el.firstChild) {
        el.innerHTML = '<span class="cinema-thumb-fallback">' + cinemaPlaceholderIcon(item.kind) + '</span>';
      }
    }

    function cinemaRecentValue(item) {
      return Number(item && item.updated_at ? item.updated_at : 0);
    }

    function withFeaturedIncludedAndSorted(items, featured, expectedKind) {
      const byId = new Map();
      for (const it of items || []) {
        if (it && it.id) byId.set(it.id, it);
      }
      if (featured && featured.id && (featured.kind || 'video') === expectedKind) {
        byId.set(featured.id, featured);
      }
      return Array.from(byId.values()).sort((a, b) => {
        const delta = cinemaRecentValue(b) - cinemaRecentValue(a);
        if (delta !== 0) return delta;
        return String(a.id || '').localeCompare(String(b.id || ''));
      });
    }

    function selectCinemaFeaturedById(itemId) {
      if (!itemId) return;
      selectedCinemaFeaturedId = itemId;
      if (lastCinemaCatalog) void renderCinema(lastCinemaCatalog);
    }

    async function watchCinemaItem(item, langCode) {
      if (!item) return;
      const tok = await ensureIdToken();
      if (!tok) {
        alert('Connexion requise');
        return;
      }
      const kind = item.kind || 'video';
      if (kind === 'ebook') {
        window.open(
          apiBase + '/api/cinema/read/' + encodeURIComponent(item.id) + '?token=' + encodeURIComponent(tok),
          '_blank',
        );
        return;
      }
      if (kind === 'audio') {
        window.open(
          apiBase + '/api/cinema/listen/' + encodeURIComponent(item.id) + '?token=' + encodeURIComponent(tok),
          '_blank',
        );
        return;
      }
      const q = new URLSearchParams();
      if (langCode === 'none') q.set('lang', 'none');
      else q.set('lang', langCode || 'nl');
      q.set('token', tok);
      window.location.href = apiBase + '/api/cinema/watch/' + encodeURIComponent(item.id) + '?' + q.toString();
    }

    async function renderCinema(data) {
      const content = document.getElementById('cinemaContent');
      revokeCinemaCardBlobs();
      const videos = withFeaturedIncludedAndSorted((data.videos || []).map((x) => ({ ...x, kind: x.kind || 'video' })), data.featured, 'video');
      const ebooks = withFeaturedIncludedAndSorted((data.ebooks || []).map((x) => ({ ...x, kind: x.kind || 'ebook' })), data.featured, 'ebook');
      const audios = withFeaturedIncludedAndSorted((data.audios || []).map((x) => ({ ...x, kind: x.kind || 'audio' })), data.featured, 'audio');
      const merged = [...videos, ...ebooks, ...audios];
      const featured = merged.find((x) => x.id === selectedCinemaFeaturedId)
        || data.featured
        || merged[0]
        || null;
      if (!featured && !videos.length && !ebooks.length && !audios.length) {
        content.innerHTML = '<div class="cinema-empty">Aucun contenu publié dans le Cinéma pour le moment.</div>';
        return;
      }
      const escH = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
      const escA = (s) => String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      function rowMarkup(title, items, prefix, kindClass) {
        if (!items.length) return '';
        let h = '<section class="cinema-row-section"><h3 class="cinema-row-title">' + escH(title) + '</h3>';
        h += '<div class="cinema-row-scroller">';
        for (const it of items) {
          h += '<div tabindex="0" role="button" class="cinema-tile" onclick="selectCinemaFeaturedById(\'' + it.id + '\')" aria-label="' + escA(it.title || it.name) + '">';
          h += '<div class="cinema-tile-thumb ' + kindClass + '" id="' + prefix + it.id + '"></div>';
          h += '</div>';
        }
        h += '</div></section>';
        return h;
      }
      let html = '<div class="cinema-netflix">';
      if (featured) {
        const langs = featured.languages || [];
        html += '<section class="cinema-hero">';
        html += '<div class="cinema-hero-inner">';
        html += '<div class="cinema-hero-text">';
        html += '<p class="cinema-hero-kicker">À la une</p>';
        html += '<h2 class="cinema-hero-title">' + escH(featured.title || featured.name) + '</h2>';
        html += '<p class="cinema-hero-desc">' + escH(featured.description || '') + '</p>';
        if ((featured.kind || 'video') === 'video') {
          html += '<div class="cinema-hero-actions">';
          html += '<label class="cinema-hero-lang-label">Langue des sous-titres';
          html += '<select id="cinemaHeroLang" class="cinema-hero-lang-select">';
          if (!langs.length) {
            html += '<option value="none">Aucun sous-titre</option>';
          } else {
            for (const L of langs) html += '<option value="' + escA(L.code) + '">' + escH(L.name) + '</option>';
          }
          html += '</select></label>';
          html += '<button type="button" class="cinema-hero-btn" onclick="watchCinemaSelectedHero()">Lire</button>';
          html += '</div>';
        } else if ((featured.kind || '') === 'audio') {
          html += '<button type="button" class="cinema-hero-btn" onclick="watchCinemaSelectedHero()">Lire l’audio</button>';
        } else {
          html += '<button type="button" class="cinema-hero-btn" onclick="watchCinemaSelectedHero()">Lire le texte</button>';
        }
        html += '</div>';
        html += '<div class="cinema-hero-visual"><div class="cinema-hero-thumb" id="cinema-hero-thumb"></div></div>';
        html += '</div></section>';
      }
      html += rowMarkup('Vidéos', videos, 'cinema-v-', 'cinema-tile-thumb--video');
      html += rowMarkup('E-books', ebooks, 'cinema-e-', 'cinema-tile-thumb--ebook');
      html += rowMarkup('Audios', audios, 'cinema-a-', 'cinema-tile-thumb--audio');
      html += '</div>';
      content.innerHTML = html;
      if (featured) await fillCinemaThumb(document.getElementById('cinema-hero-thumb'), featured);
      for (const it of videos) await fillCinemaThumb(document.getElementById('cinema-v-' + it.id), it);
      for (const it of ebooks) await fillCinemaThumb(document.getElementById('cinema-e-' + it.id), it);
      for (const it of audios) await fillCinemaThumb(document.getElementById('cinema-a-' + it.id), it);
    }

    async function watchCinemaSelectedHero() {
      const item = lastCinemaAllItems.find((x) => x.id === selectedCinemaFeaturedId);
      if (!item) return;
      const langSel = document.getElementById('cinemaHeroLang');
      const lang = langSel ? (langSel.value || 'none') : 'none';
      await watchCinemaItem(item, lang);
    }

    async function watchVideo(videoId, langCode) {
      const tok = await ensureIdToken();
      if (!tok) {
        alert('Connexion requise');
        return;
      }
      const q = new URLSearchParams();
      if (langCode === 'none') q.set('lang', 'none');
      else q.set('lang', langCode || 'nl');
      q.set('token', tok);
      window.location.href = apiBase + '/api/cinema/watch/' + videoId + '?' + q.toString();
    }

    function navigateLib(path) {
      currentLibPath = path;
      loadLibrary();
    }

    async function moveLibraryFileRequest(fileId, targetFolder) {
      try {
        const fd = new FormData();
        fd.append('folder', targetFolder == null ? '' : String(targetFolder));
        const res = await apiFetch(apiBase + '/api/library/file/' + encodeURIComponent(fileId) + '/move', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = (data && data.detail) ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : (res.statusText || String(res.status));
          throw new Error(detail);
        }
        await loadLibrary();
      } catch (err) {
        alert('Déplacement impossible : ' + (err.message || err));
      }
    }

    function initLibraryDragDrop() {
      const root = document.getElementById('libraryView');
      if (!root || root.dataset.libDndBound === '1') return;
      root.dataset.libDndBound = '1';

      function clearLibDragOver() {
        root.querySelectorAll('.lib-drag-over').forEach((el) => el.classList.remove('lib-drag-over'));
      }

      root.addEventListener('dragstart', (e) => {
        const row = e.target.closest('.lib-file-row');
        if (!row) return;
        if (e.target.closest('button, a')) {
          e.preventDefault();
          return;
        }
        const id = row.getAttribute('data-file-id');
        if (!id) return;
        e.dataTransfer.setData('text/plain', id);
        e.dataTransfer.effectAllowed = 'move';
        row.classList.add('lib-dragging');
        libraryDragFileId = id;
      });

      root.addEventListener('dragend', (e) => {
        const row = e.target.closest('.lib-file-row');
        if (row) row.classList.remove('lib-dragging');
        clearLibDragOver();
        libraryDragFileId = null;
      });

      root.addEventListener('dragover', (e) => {
        const t = e.target.closest('.lib-drop-target, .lib-bc-drop-target');
        clearLibDragOver();
        if (t) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          t.classList.add('lib-drag-over');
        }
      });

      root.addEventListener('dragleave', (e) => {
        const t = e.target.closest('.lib-drop-target, .lib-bc-drop-target');
        if (t && (!e.relatedTarget || !t.contains(e.relatedTarget))) {
          t.classList.remove('lib-drag-over');
        }
      });

      root.addEventListener('drop', (e) => {
        const t = e.target.closest('.lib-drop-target, .lib-bc-drop-target');
        if (!t) return;
        e.preventDefault();
        clearLibDragOver();
        const fileId = (e.dataTransfer.getData('text/plain') || libraryDragFileId || '').trim();
        if (!fileId) return;
        const targetPath = t.getAttribute('data-lib-path');
        const folder = targetPath == null ? '' : targetPath;
        void moveLibraryFileRequest(fileId, folder);
      });
    }

    initLibraryDragDrop();

    async function deleteFolder(id) {
      if (!confirm('Supprimer ce dossier et tout son contenu ?')) return;
      await apiFetch(apiBase + '/api/library/folder/' + id, { method: 'DELETE' });
      loadLibrary();
    }

    async function deleteLibFile(id) {
      if (!confirm('Supprimer ce fichier ?')) return;
      await apiFetch(apiBase + '/api/library/file/' + id, { method: 'DELETE' });
      loadLibrary();
    }

    function downloadLibFile(id) {
      // Must go through apiFetch so Authorization header is included.
      downloadViaApi(apiBase + '/api/library/file/' + id, '').catch(err => alert('Téléchargement échoué : ' + (err.message || err)));
    }

    async function saveVttToLibrary(jobId, filename) {
      try {
        const res = await apiFetch(apiBase + '/api/result/' + jobId + '.vtt');
        if (!res.ok) throw new Error('Téléchargement échoué : ' + res.status);
        const blob = await res.blob();
        const formData = new FormData();
        formData.append('file', blob, filename || ('subtitles_' + jobId + '.vtt'));
        formData.append('folder', ''); // save in library root
        const up = await apiFetch(apiBase + '/api/library/upload', { method: 'POST', body: formData });
        if (!up.ok) throw new Error('Échec du téléversement : ' + up.status);
        alert('Fichier VTT enregistré dans la bibliothèque.');
      } catch (err) {
        alert('Impossible d’enregistrer dans la bibliothèque : ' + err.message);
      }
    }

    // Delegate click for dynamically created buttons
    document.addEventListener('click', (e) => {
      const openTxt = e.target.closest('.open-text-btn');
      if (openTxt) {
        const id = openTxt.getAttribute('data-file-id');
        if (id) openTextInWorkspace(id);
        return;
      }
      const dl = e.target.closest('.download-result-btn');
      if (dl) {
        const url = dl.getAttribute('data-url');
        const filename = dl.getAttribute('data-filename') || '';
        downloadViaApi(url, filename).catch(err => alert('Téléchargement échoué : ' + (err.message || err)));
        return;
      }
      const ttsBtn = e.target.closest('.save-tts-to-lib-btn');
      if (ttsBtn) {
        const jobId = ttsBtn.getAttribute('data-job-id');
        if (jobId) saveTtsToLibrary(jobId);
        return;
      }
      const btn = e.target.closest('.save-to-lib-btn');
      if (!btn) return;
      const jobId = btn.getAttribute('data-job-id');
      const filename = btn.getAttribute('data-filename');
      const suffix = btn.getAttribute('data-suffix') || '.vtt';
      if (jobId) {
        if (suffix === '.txt') saveTxtToLibrary(jobId, filename);
        else saveVttToLibrary(jobId, filename);
      }
    });

    async function saveTxtToLibrary(jobId, filename) {
      try {
        const res = await apiFetch(apiBase + '/api/result/' + jobId + '.txt');
        if (!res.ok) throw new Error('Téléchargement échoué : ' + res.status);
        const blob = await res.blob();
        const formData = new FormData();
        formData.append('file', blob, filename || ('transcript_' + jobId + '.txt'));
        formData.append('folder', ''); // save in library root
        const up = await apiFetch(apiBase + '/api/library/upload', { method: 'POST', body: formData });
        if (!up.ok) throw new Error('Échec du téléversement : ' + up.status);
        alert('Transcription TXT enregistrée dans la bibliothèque.');
      } catch (err) {
        alert('Impossible d’enregistrer dans la bibliothèque : ' + err.message);
      }
    }

    async function saveTtsToLibrary(jobId) {
      try {
        const fd = new FormData();
        fd.append('job_id', jobId);
        fd.append('folder', '');
        const res = await apiFetch(apiBase + '/api/tts-save-to-library', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || ('Échec de l’enregistrement : ' + res.status));
        const count = Number(data.count || 0);
        alert('Audio enregistré dans la bibliothèque (' + count + ' fichier(s)).');
      } catch (err) {
        alert('Impossible d’enregistrer l’audio : ' + (err.message || err));
      }
    }

    async function loadWorkspaceLibraryText(id) {
      const res = await apiFetch(apiBase + '/api/library/file/' + id + '/content');
      let data = null;
      try { data = await res.json(); } catch (_) {}
      if (!res.ok) {
        const detail = (data && data.detail) ? data.detail : ('Le serveur a répondu ' + res.status);
        throw new Error(detail);
      }
      wsFilename.value = data.filename || 'transcript.txt';
      wsEditor.value = data.content || '';
      const wsFileInput = document.getElementById('workspaceFileInput');
      if (wsFileInput) wsFileInput.value = '';
      const lower = (wsFilename.value || '').toLowerCase();
      if (lower.endsWith('.vtt')) {
        setWorkspaceSubtitlesFromText(wsEditor.value);
      } else {
        clearWorkspaceVideoSubtitleTrack();
      }
    }

    async function openTextInWorkspace(id) {
      try {
        await loadWorkspaceLibraryText(id);
        await showView('workspace', { syncUrl: 'push' });
      } catch (err) {
        alert('Impossible d’ouvrir le fichier : ' + (err.message || err));
      }
    }

    async function editInWorkspace(id) {
      try {
        await loadWorkspaceLibraryText(id);
        await showView('workspace', { syncUrl: 'push' });
      } catch (err) {
        alert('Impossible d’ouvrir le fichier : ' + (err.message || err));
      }
    }

    // Upload files
    document.getElementById('libUploadInput').addEventListener('change', async function () {
      try {
        const customNameInput = document.getElementById('libUploadFilename');
        const customNameRaw = (customNameInput && customNameInput.value ? customNameInput.value : '').trim();
        if (customNameRaw && this.files.length !== 1) {
          alert('Un nom de fichier personnalisé n’est possible que pour un seul fichier à la fois.');
          this.value = '';
          return;
        }

        for (const file of this.files) {
          const formData = new FormData();
          formData.append('file', file);
          formData.append('folder', currentLibPath);
          if (customNameRaw) formData.append('filename', customNameRaw);
          const res = await apiFetch(apiBase + '/api/library/upload', { method: 'POST', body: formData });
          if (!res.ok) throw new Error('Échec du téléversement : ' + res.status);
        }
        this.value = '';
        if (customNameInput) customNameInput.value = '';
        loadLibrary();
      } catch (err) {
        alert('Erreur lors du téléversement : ' + err.message);
        this.value = '';
      }
    });

    // New folder modal
    const folderModal = document.getElementById('folderModal');
    document.getElementById('libNewFolderBtn').addEventListener('click', () => {
      document.getElementById('folderNameInput').value = '';
      document.getElementById('folderEmailsInput').value = '';
      document.getElementById('folderEmailsLabel').style.display = isAdmin ? 'block' : 'none';
      folderModal.classList.add('show');
    });
    document.getElementById('folderCancelBtn').addEventListener('click', () => folderModal.classList.remove('show'));
    document.getElementById('folderCreateBtn').addEventListener('click', async () => {
      const name = document.getElementById('folderNameInput').value.trim();
      if (!name) return;
      try {
        const formData = new FormData();
        formData.append('name', name);
        formData.append('parent', currentLibPath);
        if (isAdmin) {
          const emails = document.getElementById('folderEmailsInput').value.trim();
          if (emails) {
            formData.append('allowed_emails', emails);
          }
        }
        const res = await apiFetch(apiBase + '/api/library/folder', { method: 'POST', body: formData });
        if (!res.ok) throw new Error('Échec de la création du dossier : ' + res.status);
        folderModal.classList.remove('show');
        loadLibrary();
      } catch (err) {
        alert('Erreur lors de la création du dossier : ' + err.message);
      }
    });

    // ========== LIBRARY PICKER ==========
    const libPickerModal = document.getElementById('libPickerModal');
    const libPickerSelectBtn = document.getElementById('libPickerSelectBtn');

    function openLibPicker(target, filterTypes) {
      libPickerTarget = target;
      libPickerFilter = filterTypes.split(',');
      libPickerPath = '';
      libPickerSelectedFile = null;
      libPickerSelectBtn.disabled = true;
      libPickerModal.classList.add('show');
      loadLibPicker();
    }

    async function loadLibPicker() {
      try {
        const res = await apiFetch(apiBase + '/api/library?path=' + encodeURIComponent(libPickerPath));
        if (!res.ok) throw new Error('Le serveur a répondu ' + res.status);
        const data = await res.json();
        renderLibPicker(data);
      } catch (err) {
        document.getElementById('libPickerList').innerHTML = '<div class="lib-picker-empty">Erreur : ' + err.message + '</div>';
      }
    }

    function renderLibPicker(data) {
      // Breadcrumb
      const bc = document.getElementById('libPickerBreadcrumb');
      const parts = data.path ? data.path.split('/') : [];
      let bcHtml = '<a href="#" onclick="navigateLibPicker(\'\'); return false;">Racine</a>';
      let pathSoFar = '';
      for (const p of parts) {
        pathSoFar += (pathSoFar ? '/' : '') + p;
        bcHtml += ' / <a href="#" onclick="navigateLibPicker(\'' + pathSoFar + '\'); return false;">' + p + '</a>';
      }
      bc.innerHTML = bcHtml;

      // File list
      const list = document.getElementById('libPickerList');
      const filteredFiles = data.files.filter(f => libPickerFilter.includes(f.type));
      
      if (!data.folders.length && !filteredFiles.length) {
        list.innerHTML = '<div class="lib-picker-empty">Aucun fichier correspondant dans ce dossier.</div>';
        return;
      }

      let html = '';
      for (const folder of data.folders) {
        html += '<div class="lib-picker-item" onclick="navigateLibPicker(\'' + folder.path + '\')">';
        html += '<span class="lib-picker-icon">📁</span>';
        html += '<span class="lib-picker-name">' + folder.name + '</span>';
        html += '</div>';
      }
      for (const file of filteredFiles) {
        const icon = file.type === 'vtt' ? '📄' : (file.type === 'text' ? '📝' : (file.type === 'audio' ? '🎵' : '🎬'));
        html += '<div class="lib-picker-item" data-file-id="' + file.id + '" data-file-name="' + file.name + '" onclick="selectLibPickerFile(this)">';
        html += '<span class="lib-picker-icon">' + icon + '</span>';
        html += '<span class="lib-picker-name">' + file.name + '</span>';
        html += '</div>';
      }
      list.innerHTML = html;
    }

    function navigateLibPicker(path) {
      libPickerPath = path;
      libPickerSelectedFile = null;
      libPickerSelectBtn.disabled = true;
      loadLibPicker();
    }

    function selectLibPickerFile(el) {
      // Remove previous selection
      document.querySelectorAll('#libPickerList .lib-picker-item').forEach(item => item.classList.remove('selected'));
      // Select this one
      el.classList.add('selected');
      libPickerSelectedFile = {
        libraryId: el.dataset.fileId,
        name: el.dataset.fileName
      };
      libPickerSelectBtn.disabled = false;
    }

    document.getElementById('libPickerCancelBtn').addEventListener('click', () => {
      libPickerModal.classList.remove('show');
    });

    document.getElementById('libPickerSelectBtn').addEventListener('click', async () => {
      if (!libPickerSelectedFile) return;
      
      if (libPickerTarget === 'transcribe') {
        transcribeSelectedFile = libPickerSelectedFile;
        document.getElementById('transcribeFileInfo').textContent = libPickerSelectedFile.name + ' (Bibliothèque)';
        document.getElementById('transcribeFileInfo').classList.add('selected');
      } else if (libPickerTarget === 'translate') {
        translateSelectedFile = libPickerSelectedFile;
        document.getElementById('translateFileInfo').textContent = libPickerSelectedFile.name + ' (Bibliothèque)';
        document.getElementById('translateFileInfo').classList.add('selected');
      } else if (libPickerTarget === 'tts') {
        ttsSelectedFile = libPickerSelectedFile;
        document.getElementById('ttsFileInfo').textContent = libPickerSelectedFile.name + ' (Bibliothèque)';
        document.getElementById('ttsFileInfo').classList.add('selected');
      } else if (libPickerTarget === 'burnVideo') {
        burnVideoSelected = libPickerSelectedFile;
        document.getElementById('burnVideoInfo').textContent = libPickerSelectedFile.name + ' (Bibliothèque)';
        document.getElementById('burnVideoInfo').classList.add('selected');
      } else if (libPickerTarget === 'burnVtt') {
        burnVttSelected = libPickerSelectedFile;
        document.getElementById('burnVttInfo').textContent = libPickerSelectedFile.name + ' (Bibliothèque)';
        document.getElementById('burnVttInfo').classList.add('selected');
      } else if (libPickerTarget === 'workspaceVideo') {
        await loadWorkspaceVideoFromLibrary(libPickerSelectedFile.libraryId, libPickerSelectedFile.name);
      } else if (libPickerTarget === 'workspaceText') {
        try {
          await loadWorkspaceLibraryText(libPickerSelectedFile.libraryId);
        } catch (err) {
          alert('Impossible de charger le fichier : ' + (err.message || err));
        }
      }

      libPickerModal.classList.remove('show');
    });

    // Expose functions used by inline onclick handlers.
    // Because this script runs as type="module", functions are not global by default.
    Object.assign(window, {
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
      closeLibraryVideoModal,
      openCinemaPublishModal,
      openCinemaDetailById,
      watchVideo,
      selectCinemaFeaturedById,
      watchCinemaSelectedHero,
      closeAllLibMenus,
      libModifierCinema,
      libMenuTelecharger,
      duplicateLibFile,
      duplicateLibFolder,
      renameLibFolder,
    });


