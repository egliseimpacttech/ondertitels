# Ondertitels — Web (React + TypeScript)

Modern SPA for transcription, translation, library, and cinema.

## Develop

```bash
# Terminal 1 — API
cd .. && uvicorn backend.main:app --reload --port 8000

# Terminal 2 — Vite
npm install
npm run dev
```

Open http://127.0.0.1:5173 — `/api` and `/brand-logo.png` are proxied to the backend.

## Production build

```bash
npm run build
```

Output: `dist/`. FastAPI serves this automatically when `web/dist/index.html` exists.
