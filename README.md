# Automatic Subtitles — Church Sermons

Web app to generate **WebVTT subtitles** from sermon audio/video, translate to multiple languages, and play video with stacked subtitles.

## Target languages

| Language   | Region              | Translation API (primary → fallback) |
|-----------|---------------------|---------------------------------------|
| Nederlands | Belgium             | DeepL                                 |
| English   | Canada              | DeepL → ChatGPT (fallback)            |
| Malgasy   | Madagascar          | ChatGPT                               |
| Kikongo   | Congo (Brazzaville) | ChatGPT                               |
| Tshiluba  | Congo (Kinshasa)    | ChatGPT                               |
| Lingala   | All countries       | ChatGPT                               |
| Portuguese| Angola              | DeepL                                 |

| Functie | Volgorde |
|---------|----------|
| Live ASR | Whisper lokaal → HF → OpenAI → ElevenLabs |
| Live vertaling | Ollama (Dit staat op mijn VPS) → NLLB → DeepL/OpenAI |
| Batch transcriptie | Whisper lokaal → OpenAI → ElevenLabs |
| Batch Traduire | DeepL / OpenAI (**geen** Ollama) |
| TTS (Voix) | OpenAI → ElevenLabs |

## Features

1. **Two-step workflow**:
   - **Step 1: Transcribe** — Upload audio/video → get a VTT file with timestamped transcription (original language).
   - **Download & edit** — Correct any transcription errors in the VTT before translating.
   - **Step 2: Translate** — Upload the (edited) VTT → choose target languages → get translated VTT.
2. **All-in-one option** — Transcribe and translate in one step (legacy mode).
3. **Multi-language** — One VTT file with all languages as separate lines (stacked within each cue).
4. **Video player** — In-app player with VTT support in the browser.
5. **Church workspaces** — Separate church libraries, invited email access, Stripe subscriptions, and storage quotas.
6. **Desktop installation** — Installable Progressive Web App (PWA) on supported desktop browsers.

## Church subscriptions and storage

- Each church registers its workspace; its first account is the church administrator.
- A paid church subscription costs **€20/month, VAT included**, through Stripe Checkout and has a **100 GB** library quota.
- The administrator can invite authorized email addresses and manage billing from Administration.
- New accounts must verify their email before they can access a church workspace.
- `kaat.dbolle@gmail.com` receives the free **Ministère Apostolique Impact** workspace with unlimited storage.
- Church memberships, roles, and subscription state are stored in Firestore. The designated ministry administrator is mapped directly from the verified `kaat.dbolle@gmail.com` account. Files and library indexes use separate church-specific storage prefixes. The previous shared library remains available to the ministry workspace; its index is merged into the ministry's church-specific index once, which is then the canonical index. The legacy index is retained as a backup.
- If a configured Google Cloud Storage bucket is unavailable, the backend switches to tenant-scoped local disk storage for the current process and reports this in Administration. This is a fallback, not a second backup: cloud-only files may be unavailable, and local disk on Cloud Run is ephemeral.
- The backend requires a valid Firebase membership and active subscription for paid church features; hiding screens in the frontend is not used as the access control.

### Configure billing

1. Enable Firestore in the Firebase/GCP project and grant the Cloud Run service account Firestore access (`roles/datastore.user`).
2. Configure `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `APP_BASE_URL` in the server environment. Do not put Stripe secrets in frontend code or commit them.
3. Enable Stripe Tax and configure the business/tax registrations. The checkout uses a recurring €20 EUR price with tax included and Stripe automatic tax enabled.
4. Add a Stripe webhook pointing to `https://YOUR_APP_HOST/api/billing/webhook` for:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Deploy the site over HTTPS. On supported desktop browsers, use the browser's **Install app** action to install Ondertitels as a desktop PWA. It is not a separate `.exe`/native installer.

## UI

- Interface in **French**.
- Modern **React + TypeScript** frontend (`web/`) with Vite.
- Design system: Syne + Figtree, forest-green accents, responsive shell.
- Views: Accueil (studio), Cinéma, Espace de travail, Bibliothèque, Administration.

## Subtitle styling

- In WebVTT/HTML5 the browser controls most styling.
- Multiple languages are stacked: each language on its own line inside a cue.
## APIs

### Transcription — **ElevenLabs (recommended)**

- **ElevenLabs** is the right choice for **speech** (sermons): direct speech-to-text with word-level timestamps, supports long files (e.g. 1h30), MP3/WAV/MP4.
- **Poyo** is aimed at **music** (timestamped lyrics from generated songs), not general speech.

Use **ElevenLabs Speech-to-Text** (e.g. Scribe) for transcription.

### Translation

- **DeepL:** Nederlands, English, Portuguese (primary).
- **OpenAI (ChatGPT):** Malgasy, Kikongo, Tshiluba, Lingala; **fallback for English** if DeepL fails or is not configured.

## Project structure

```
backend/          # FastAPI backend
  config.py       # Configuration with API key validation
  main.py         # API endpoints with improved error handling
  transcription.py # ElevenLabs integration with better error handling
  translation.py  # DeepL/OpenAI with caching and validation
  vtt_generator.py # WebVTT generation
  vtt_parser.py   # VTT parsing
  burn.py         # FFmpeg video processing
  library.py      # File storage system
  ass_generator.py # ASS subtitle generation

frontend/         # Legacy HTML shell (fallback if web/dist missing)
web/              # React + TypeScript + Vite SPA
  src/            # Pages, components, API client, auth
tests/            # Unit tests with pytest
```

## Development

### Setup
```bash
pip install -r requirements.txt
```

### Configuration
- Copy `.env.example` to `.env` and fill in your API keys
- Set `VITE_FIREBASE_CONFIG_API_KEY` to the Firebase Web API key for local Vite builds; provide the same variable as a build environment variable for Docker/Cloud Run builds. This is public client configuration, not a server secret.
- For local development: `ENV=local`
- For production: `ENV=production`

### Testing
```bash
pytest
```

### Frontend (React + TypeScript)
```bash
cd web
npm install
npm run dev      # http://127.0.0.1:5173 (proxies /api → :8000)
npm run build    # outputs web/dist — served by FastAPI when present
```

### Running
```bash
python backend/main.py
# or: uvicorn backend.main:app --reload
```
Open http://127.0.0.1:8000 (serves `web/dist` if built, else legacy `frontend/`).

For local subscription testing, use a Stripe test-mode secret and webhook signing secret, and set `APP_BASE_URL` to the local public URL exposed to Stripe CLI. Firestore must also be reachable by the backend service account.

## Recent Improvements

- ✅ **API Key Validation**: Automatic validation on startup
- ✅ **Better Error Handling**: Specific error messages for API failures
- ✅ **Translation Caching**: In-memory cache for repeated translations
- ✅ **Code Quality**: Type hints, docstrings, and modular functions
- ✅ **Testing**: Pytest setup with basic test coverage
- ✅ **Configuration**: Environment-specific configs (local/production)
- ✅ **Monitoring**: Health check endpoints
- ✅ **Security**: Improved file validation and rate limiting

```
ondertitels/
├── README.md
├── requirements.txt
├── .env.example
├── backend/
│   ├── main.py           # FastAPI app, upload, orchestration
│   ├── config.py         # Settings, API keys
│   ├── transcription.py  # ElevenLabs
│   ├── translation.py    # DeepL + OpenAI
│   └── ass_generator.py  # ASS with Montserrat, top, multi-line
├── frontend/
│   └── index.html        # Upload, download ASS, video player
└── static/               # Fonts, optional player assets
```

## Setup

1. Copy `.env.example` to `.env` and add your API keys.
2. From the **project root** (`ondertitels/`):
   `pip install -r requirements.txt`
3. Run from project root: `uvicorn backend.main:app --reload`
   Or: `python -m uvicorn backend.main:app --reload`
4. Open http://127.0.0.1:8000 — the app serves the frontend and API.

## API keys

- **ElevenLabs** — [elevenlabs.io](https://elevenlabs.io) (Speech-to-Text / Scribe).
- **DeepL** — [deepl.com](https://www.deepl.com/pro-api).
- **OpenAI** — For Malgasy, Kikongo, Tshiluba.
#
