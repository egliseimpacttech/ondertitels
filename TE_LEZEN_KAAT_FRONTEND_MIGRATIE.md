# TE LEZEN — Ondertitels (voor Kaat)

Hallo Kaat 👋  

Kort: wat er **nieuw** is t.o.v. de oude repo, hoe je de app **start**, en wat je mag **weggooien**.

**UI-taal:** Frans. **Dit document:** Nederlands.

**Login (lokaal):** `kaat@ondertitels.app` / `Ondertitels2026!`

---

## Wat is er toegevoegd? (kort)

T.o.v. wat op de repo stond (oude HTML-frontend + cloud-API):

### Frontend
- Nieuwe UI in map **`web/`** (React + TypeScript + Vite)
- **Accueil** = hub met kaarten → 5 aparte studio-pagina’s
- Drawer: Accueil + **sublinks** (2e niveau)
- Nieuwe tab **Traduction live** (`/traduction-live`)
- Oude map **`frontend/`** is niet meer nodig → **mag je verwijderen** (zie hieronder)

### Backend
- Live-endpoint: `POST /api/live/translate-chunk`
- Lokale spraak→tekst: **faster-whisper** (`backend/local_asr.py`)
- Live-vertaling via **Ollama** op de VPS (`backend/local_translate.py`) — **alleen voor live**, niet voor Accueil → Traduire
- Optioneel: Hugging Face ASR als fallback
- ElevenLabs is vooral **fallback** (niet meer primary)
- Docker bouwt nu `web/` mee

### Providers (nu)
| Functie | Volgorde |
|---------|----------|
| Live ASR | Whisper lokaal → HF → OpenAI → ElevenLabs |
| Live vertaling | Ollama (Dit staat op mijn VPS) → NLLB → DeepL/OpenAI |
| Batch transcriptie | Whisper lokaal → OpenAI → ElevenLabs |
| Batch Traduire | DeepL / OpenAI (**geen** Ollama) |
| TTS (Voix) | OpenAI → ElevenLabs |

---

## Map `frontend/` mag weg

De UI draait volledig vanuit **`web/`**.

De oude map **`frontend/`** (HTML/JS) is een restant.  
**Je mag die folder verwijderen** — de app gebruikt die niet meer zolang `web/dist` bestaat (na `npm run build`).

```bash
# Optioneel, als je wilt opruimen:
rm -rf frontend
```

Werk verder alleen in **`web/src/`**.

---

## Hoe start je de applicatie?

### Eenmalig (eerste keer)

```bash
cd /Users/mukadash/Desktop/ondertitels

# Python-venv
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend-packages
cd web && npm install && cd ..

# Secrets (als .env nog niet bestaat)
cp .env.example .env
# Vul daarna .env in (Ollama-token, e-mails, optionele API-keys)
```

Zorg dat in `.env` o.a. staat:

```env
ENV=local
LOCAL_INFERENCE=true
OLLAMA_BASE_URL=https://zikolama12.mukadash.net
OLLAMA_TRANSLATE_MODEL=llama3.2:3b
OLLAMA_API_TOKEN=jouw-token
ADMIN_EMAILS=kaat@ondertitels.app
ALLOWED_EMAILS=kaat@ondertitels.app
```

### Elke keer starten — Optie A (eenvoudigst)

Hele app op **één adres**: http://127.0.0.1:8000

```bash
cd /Users/mukadash/Desktop/ondertitels
source .venv/bin/activate

cd web && npm run build && cd ..

uvicorn backend.main:app --reload --reload-exclude '.venv' --reload-exclude 'web/node_modules' --port 8000
```

Browser: **http://127.0.0.1:8000**  
Na een nieuwe build: hard refresh (`Cmd + Shift + R`).

### Elke keer starten — Optie B (handig als jij aan de UI werkt)

**Terminal 1 — backend**

```bash
cd /Users/mukadash/Desktop/ondertitels
source .venv/bin/activate
uvicorn backend.main:app --reload --reload-exclude '.venv' --reload-exclude 'web/node_modules' --port 8000
```

**Terminal 2 — frontend (hot reload)**

```bash
cd /Users/mukadash/Desktop/ondertitels/web
npm run dev
```

Browser: **http://127.0.0.1:5173**  
Vite stuurt `/api` automatisch door naar poort 8000.

---

## Check: werkt het?

1. Login met het testaccount  
2. Accueil = hub met 5 kaarten  
3. Drawer: Accueil-sublinks + **Traduction live**  
4. Live: microfoon → Frans spreken → vertaling verschijnt  

Health:

```bash
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
```

Kijk o.a. naar `apis.local_whisper`, `apis.ollama`, `live_asr.ollama_auth`.

---

## Pagina’s (routes)

| URL | Scherm |
|-----|--------|
| `/accueil` | Accueil (hub) |
| `/accueil/envoyer` | Upload naar bibliotheek |
| `/accueil/transcription` | Transcription |
| `/accueil/traduire` | Traduire (batch, DeepL/OpenAI) |
| `/accueil/voix` | Voix / TTS |
| `/accueil/incrustation` | Ondertitels in video |
| `/traduction-live` | Live microfoon → vertaling |
| `/cinema` | Cinéma |
| `/workspace` | Espace de travail |
| `/bibliotheque` | Bibliothèque |
| `/administration` | Admin |

---

## Waar werk jij?

| Map / bestand | Rol |
|---------------|-----|
| `web/src/pages/` | Schermen |
| `web/src/pages/studio/` | De 5 Accueil-tools |
| `web/src/pages/LiveTranslatePage.tsx` | Traduction live |
| `web/src/pages/HomePage.tsx` | Accueil-hub |
| `web/src/components/layout/AppShell.tsx` | Header + drawer |
| `web/src/lib/studio.ts` | Labels/paden van studio-tools |
| `backend/` | API (Mukadash) — alleen aanpassen als afgesproken |

**Afspraken**

1. Nooit `.env` committen  
2. UI-teksten in het **Frans**  
3. Na UI-werk met Optie A: opnieuw `npm run build`  

---

## Problemen

| Probleem | Oplossing |
|----------|-----------|
| `uvicorn` niet gevonden | `source .venv/bin/activate` |
| Oude UI / oude Accueil | `cd web && npm run build` + hard refresh |
| `401` | Opnieuw inloggen; check `ALLOWED_EMAILS` in `.env` |
| Live faalt | Check Ollama-token + `/api/health` |
| Microfoon geweigerd | Browser-toestemming geven |
| Server herstart non-stop | Start met `--reload-exclude '.venv'` |

---

## Checklist starten

1. [ ] `source .venv/bin/activate`  
2. [ ] `.env` aanwezig (token + e-mails)  
3. [ ] Optie A: `cd web && npm run build` **of** Optie B: `npm run dev`  
4. [ ] `uvicorn … --port 8000`  
5. [ ] Open http://127.0.0.1:8000 (of :5173)  
6. [ ] Login → Accueil + Traduction live checken  

Optioneel: map **`frontend/`** verwijderen — die is vervangen door **`web/`**.

---

*Update: 28 juli 2026 — React-UI (`web/`), Accueil-hub, Traduction live, Whisper lokaal + Ollama alleen voor live; oude `frontend/` mag weg.*
