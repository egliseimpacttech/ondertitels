from pathlib import Path

p = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
t = p.read_text(encoding="utf-8")

t = t.replace(
    "    async function ensureIdToken() {\n"
    "      // Wait for initial auth state to be known\n"
    "      await authReady;\n"
    "      const user = fbAuth.currentUser;\n"
    "      if (!user) return null;\n"
    "      // Always ask Firebase for a current token (it refreshes automatically when needed).\n"
    "      // Keeping a cached token forever causes 401 after ~1 hour when it expires.\n"
    "      idToken = await user.getIdToken();\n"
    "      return idToken || null;\n"
    "    }\n",
    "    async function ensureIdToken(forceRefresh = false) {\n"
    "      // Wait for initial auth state to be known\n"
    "      await authReady;\n"
    "      const user = fbAuth.currentUser;\n"
    "      if (!user) return null;\n"
    "      // Always ask Firebase for a current token (it refreshes automatically when needed).\n"
    "      // Keeping a cached token forever causes 401 after ~1 hour when it expires.\n"
    "      idToken = await user.getIdToken(!!forceRefresh);\n"
    "      return idToken || null;\n"
    "    }\n",
    1,
)

t = t.replace(
    "    async function apiFetch(url, options) {\n"
    "      options = options || {};\n"
    "      options.headers = options.headers || {};\n"
    "      const tok = await ensureIdToken();\n"
    "      if (tok) options.headers['Authorization'] = 'Bearer ' + tok;\n"
    "      return fetch(url, options);\n"
    "    }\n",
    "    async function apiFetch(url, options) {\n"
    "      options = options || {};\n"
    "      options.headers = options.headers || {};\n"
    "      const tok = await ensureIdToken();\n"
    "      if (tok) options.headers['Authorization'] = 'Bearer ' + tok;\n"
    "      let res = await fetch(url, options);\n"
    "      if (res.status === 401 && fbAuth.currentUser) {\n"
    "        // Token can become stale during session restore; refresh once and retry.\n"
    "        const refreshed = await ensureIdToken(true);\n"
    "        if (refreshed) {\n"
    "          options.headers['Authorization'] = 'Bearer ' + refreshed;\n"
    "          res = await fetch(url, options);\n"
    "        }\n"
    "      }\n"
    "      return res;\n"
    "    }\n",
    1,
)

t = t.replace(
    "      if (!user) {\n"
    "        idToken = null;\n"
    "        if (authGate) authGate.style.display = 'block';\n",
    "      if (!user) {\n"
    "        idToken = null;\n"
    "        currentLibPath = '';\n"
    "        if (authGate) authGate.style.display = 'block';\n",
    1,
)

t = t.replace(
    "      await detectCinemaOnlyMode();\n"
    "      if (shouldOpenCinemaFromLocation()) activateCinemaView();\n"
    "      if (authReadyResolve) { authReadyResolve(); authReadyResolve = null; }\n",
    "      await detectCinemaOnlyMode();\n"
    "      if (shouldOpenCinemaFromLocation()) activateCinemaView();\n"
    "      if (!cinemaOnlyMode) {\n"
    "        currentLibPath = '';\n"
    "        try { await loadLibrary(); } catch (_) {}\n"
    "      }\n"
    "      if (authReadyResolve) { authReadyResolve(); authReadyResolve = null; }\n",
    1,
)

p.write_text(t, encoding="utf-8")
print("ok")
