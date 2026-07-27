"""FastAPI app: upload audio/video → transcribe → translate → VTT download + video player."""
import asyncio
import html
import json
import logging
import mimetypes
import subprocess
import shutil
import threading
import urllib.request
import zipfile
import uuid
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from fastapi import File, Form, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage
import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import PlainTextResponse
from starlette.responses import JSONResponse
from starlette.responses import Response
from elevenlabs import ElevenLabs
from elevenlabs.core.api_error import ApiError
from openai import OpenAI

from backend import config
from backend.transcription import transcribe_file
from backend.translation import translate_segments
from backend.vtt_generator import generate_vtt
from backend.vtt_parser import parse_vtt
from backend import library
from backend import burn

app = FastAPI(title="Automatic Subtitles", version="0.1.0")
logger = logging.getLogger("ondertitels")

FRONTEND_DIR = config.BASE_DIR / "frontend"
STATIC_DIR = config.BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---- Firebase auth (magic link) ----
# Lazy initialization: Firebase will be initialized on first use, not at startup.
# This allows the /health endpoint to work even if Firebase setup fails.
_firebase_initialized = False
_firebase_init_failed = False
_firebase_error_msg = ""

def _init_firebase() -> bool:
    """
    Initialize Firebase Admin SDK if not already done.
    Returns True if successful, False if failed or credentials unavailable.
    Safe to call multiple times.
    """
    global _firebase_initialized, _firebase_init_failed, _firebase_error_msg
    
    if _firebase_initialized:
        return True
    if _firebase_init_failed:
        return False
    
    try:
        if firebase_admin._apps:
            _firebase_initialized = True
            return True
        
        # On Cloud Run, Application Default Credentials are available.
        # Locally, this works if you've set GOOGLE_APPLICATION_CREDENTIALS or `gcloud auth application-default login`.
        firebase_admin.initialize_app(
            credential=firebase_credentials.ApplicationDefault(),
            options={"projectId": config.FIREBASE_PROJECT_ID},
        )
        _firebase_initialized = True
        logger.info("Firebase initialized successfully with project ID: %s", config.FIREBASE_PROJECT_ID)
        return True
    except Exception as e:
        _firebase_init_failed = True
        _firebase_error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        logger.error("Failed to initialize Firebase: %s", _firebase_error_msg)
        return False


@app.middleware("http")
async def _firebase_auth_middleware(request: Request, call_next):
    """
    Protect all /api/* endpoints with Firebase ID token.
    Frontend must send: Authorization: Bearer <idToken>
    
    Health checks (/health, /api/health) are allowed without authentication.
    """
    path = request.url.path or ""
    
    # Allow health checks without authentication
    if path in ("/health", "/api/health"):
        return await call_next(request)
    
    if path.startswith("/api/"):
        # Initialize Firebase on first API request (lazy loading)
        if not _init_firebase():
            return JSONResponse(
                {"detail": "Firebase authentication is not available. Check server logs."}, 
                status_code=503
            )
        
        # Extract token from appropriate source
        authz = request.headers.get("authorization", "")
        token = None
        if authz.lower().startswith("bearer "):
            token = authz.split(" ", 1)[1].strip()
        # <video>/<track>/<img> cannot send Authorization; Cinema pages pass ?token= for media URLs.
        elif path.startswith("/api/cinema/"):
            token = (request.query_params.get("token") or "").strip()
        # Library file GET: same pattern for in-app video preview (?token= on <video src>).
        elif request.method == "GET" and path.startswith("/api/library/file/"):
            rest = path[len("/api/library/file/") :].lstrip("/")
            if rest and "/" not in rest:
                token = (request.query_params.get("token") or "").strip()
        
        if not token:
            return JSONResponse({"detail": "Missing Authorization: Bearer <idToken>."}, status_code=401)
        
        try:
            claims = firebase_auth.verify_id_token(token)
            request.state.firebase_claims = claims
            request.state.is_cinema_only = False
            allowed_raw = (config.ALLOWED_EMAILS or "").strip()
            # Secure-by-default: if ALLOWED_EMAILS is empty, fall back to ADMIN_EMAILS.
            # This prevents "everyone has full Library access" when allowlist is unset.
            if not allowed_raw:
                allowed_raw = (config.ADMIN_EMAILS or "").strip()
            if allowed_raw:
                allowed = {e.strip().lower() for e in allowed_raw.split(",") if e.strip()}
                email = (claims.get("email") or "").strip().lower()
                if not email or (email not in allowed and not _is_admin_email(email)):
                    # Non-allowlisted users can only access cinema endpoints
                    if not path.startswith("/api/cinema"):
                        return JSONResponse({"detail": "Access restricted to Cinema only."}, status_code=403)
                    request.state.is_cinema_only = True
            else:
                # No allowlist configured at all: keep users in Cinema-only mode.
                if not path.startswith("/api/cinema"):
                    return JSONResponse({"detail": "Access restricted to Cinema only."}, status_code=403)
                request.state.is_cinema_only = True
        except Exception as e:
            # Don't leak token/PII; but provide enough info to debug config mismatches.
            logger.warning("Firebase token verify failed: %s: %s", type(e).__name__, str(e)[:300])
            return JSONResponse({"detail": "Invalid/expired token (Firebase verify failed)."}, status_code=401)
    
    return await call_next(request)


def _metadata_service_account_email() -> str | None:
    """
    On Cloud Run/Compute, fetch the attached service account email from the metadata server.
    Returns None if not available (e.g., local dev).
    """
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:  # nosec - metadata only
            email = (resp.read() or b"").decode("utf-8", "ignore").strip()
            return email or None
    except Exception:
        return None

# ---- Rate limiting ----
def _client_ip(request: Request) -> str:
    """
    Cloud Run sits behind a proxy. Prefer X-Forwarded-For when present.
    Fall back to request.client.
    """
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip, default_limits=[])
app.state.limiter = limiter
if not config.DISABLE_API_RATE_LIMITS:
    app.add_middleware(SlowAPIMiddleware)


def _api_limit(limit_str: str):
    """Apply slowapi limit unless DISABLE_API_RATE_LIMITS is set (see backend/config.py)."""
    if config.DISABLE_API_RATE_LIMITS:

        def _noop(f):
            return f

        return _noop
    return limiter.limit(limit_str)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return PlainTextResponse("Too many requests. Please wait and try again.", status_code=429)

# In-memory progress per job: { job_id: { progress, message, done, error?, eta_seconds? } }
job_progress: dict[str, dict] = {}

def _persist_job_progress(job_id: str, payload: dict) -> None:
    """
    Persist progress to GCS so polling works across Cloud Run instances/restarts.
    Best-effort: failures shouldn't crash the job.
    """
    try:
        bucket = _get_gcs_bucket()
        blob = bucket.blob(f"jobs/{job_id}.json")
        blob.upload_from_string(json.dumps(payload, ensure_ascii=False), content_type="application/json")
    except Exception:
        # Avoid log spam; polling will still work on the same instance via memory.
        return


def set_job_progress(job_id: str, payload: dict) -> None:
    job_progress[job_id] = payload
    _persist_job_progress(job_id, payload)


def _load_persisted_job_progress(job_id: str) -> dict | None:
    try:
        bucket = _get_gcs_bucket()
        blob = bucket.blob(f"jobs/{job_id}.json")
        if not blob.exists():
            return None
        data = blob.download_as_bytes()
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


GCS_JOB_RESULTS_PREFIX = "job_results"


def _gcs_bucket_optional():
    """Bucket for job artifacts; None if GCS not configured or client fails (no HTTPException)."""
    name = (config.GCS_BUCKET_NAME or "").strip()
    if not name:
        return None
    try:
        return storage.Client().bucket(name)
    except Exception as e:
        logger.warning("GCS bucket optional init failed: %s", e)
        return None


def _persist_job_output_to_gcs(local_path: Path) -> None:
    """
    Copy finished job files to GCS so /api/result/* works after Cloud Run scale-to-zero
    or when the download hits a different instance than the worker.
    """
    bucket = _gcs_bucket_optional()
    if bucket is None or not local_path.is_file():
        return
    key = f"{GCS_JOB_RESULTS_PREFIX}/{local_path.name}"
    ct = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    try:
        blob = bucket.blob(key)
        blob.upload_from_filename(str(local_path), content_type=ct)
        logger.info("Persisted job output to gs://%s/%s", bucket.name, key)
    except Exception as e:
        logger.warning("Could not persist job output to GCS: %s", e)


def _fetch_job_output_bytes(filename: str) -> bytes | None:
    """Load bytes for e.g. '{uuid}.vtt' from GCS job_results/."""
    bucket = _gcs_bucket_optional()
    if bucket is None:
        return None
    key = f"{GCS_JOB_RESULTS_PREFIX}/{filename}"
    try:
        blob = bucket.blob(key)
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception as e:
        logger.warning("Could not read job output from GCS: %s", e)
        return None


def _get_job_result_blob(filename: str):
    """Return a GCS blob for job_results/{filename} if it exists, else None."""
    bucket = _gcs_bucket_optional()
    if bucket is None:
        return None
    key = f"{GCS_JOB_RESULTS_PREFIX}/{filename}"
    try:
        blob = bucket.blob(key)
        if not blob.exists():
            return None
        return blob
    except Exception as e:
        logger.warning("Could not stat job output in GCS: %s", e)
        return None


def _download_blob_with_progress(
    blob: storage.Blob,
    target_path: Path,
    job_id: str,
    start_percent: int,
    end_percent: int,
    label: str,
    chunk_size: int = 8 * 1024 * 1024,
    timeout_seconds: int = 300,  # 5 minutes timeout for first chunk
) -> None:
    """
    Stream a GCS blob to disk and update progress between start_percent and end_percent.
    """
    import time
    total = int(getattr(blob, "size", 0) or 0)
    downloaded = 0
    target_path.parent.mkdir(parents=True, exist_ok=True)

    def _set(pct: int, msg: str):
        set_job_progress(job_id, {
            "progress": pct,
            "message": msg,
            "done": False,
            "error": None,
            "eta_seconds": None,
        })

    _set(start_percent, f"{label} (connecting...)")

    try:
        # Try to open blob with timeout
        start_time = time.time()
        with blob.open("rb") as src, target_path.open("wb") as dst:
            _set(start_percent, f"{label} (downloading...)")

            while True:
                # Check for timeout on first chunk
                if downloaded == 0 and time.time() - start_time > timeout_seconds:
                    raise Exception(f"Timeout waiting for first data chunk after {timeout_seconds} seconds")

                buf = src.read(chunk_size)
                if not buf:
                    break
                dst.write(buf)
                downloaded += len(buf)
                frac = min(1.0, downloaded / total) if total > 0 else 0.5
                pct = int(start_percent + (end_percent - start_percent) * frac)
                _set(pct, f"{label} ({downloaded // (1024*1024)} / {total // (1024*1024) if total > 0 else '?'} MB)")

    except Exception as e:
        # If download fails, clean up partial file
        try:
            target_path.unlink(missing_ok=True)
        except:
            pass
        raise Exception(f"GCS download failed: {e}")

    _set(end_percent, f"{label} (complete)")


# Max time for transcription (long sermons can take several minutes)
TRANSCRIPTION_TIMEOUT_SECONDS = 1800  # 30 minutes for longer content


def _is_admin_email(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    admins_raw = (config.ADMIN_EMAILS or "").strip()
    allowed_raw = (config.ALLOWED_EMAILS or "").strip()
    raw = admins_raw or allowed_raw
    if not raw:
        return False
    admins = {e.strip().lower() for e in raw.split(",") if e.strip()}
    return email in admins


def _require_admin(request: Request) -> str:
    claims = getattr(request.state, "firebase_claims", {}) or {}
    email = (claims.get("email") or "").strip().lower()
    if not _is_admin_email(email):
        raise HTTPException(403, "Forbidden")
    return email


def _require_cinema_publisher(request: Request) -> str:
    """Full Library users may publish to Cinema; cinema-only accounts may not."""
    claims = getattr(request.state, "firebase_claims", {}) or {}
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "Unauthorized")
    if getattr(request.state, "is_cinema_only", False):
        raise HTTPException(403, "Publishing is only available for users with full Library access.")
    return email


def _cinema_cover_jpg_path(video_id: str) -> Path:
    return config.OUTPUT_DIR / f"cinema_cover_{video_id}.jpg"


def _extract_cinema_cover_from_video(video_path: Path, video_id: str, at_seconds: float) -> None:
    out = _cinema_cover_jpg_path(video_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    ss = max(0.0, float(at_seconds))
    vp = str(video_path.resolve())
    op = str(out.resolve())
    # Fast keyframe seek + short accurate seek (avoids frame = random keyframe near requested second).
    if ss <= 0.05:
        cmd = ["ffmpeg", "-y", "-i", vp, "-frames:v", "1", "-q:v", "2", op]
    else:
        coarse = max(0.0, ss - 3.0)
        refine = ss - coarse
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(coarse),
            "-i", vp,
            "-ss", str(refine),
            "-frames:v", "1",
            "-q:v", "2",
            op,
        ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip()
        raise HTTPException(500, f"Could not create cover image (ffmpeg): {err[-800:] if err else 'unknown error'}")


def _cinema_item_is_public(file_id: str, allowed_types: tuple[str, ...] | None = None) -> bool:
    entry = library.get_file_entry(file_id)
    if not entry or not entry.get("cinema_public"):
        return False
    t = entry.get("type")
    if allowed_types is None:
        return t in ("video", "text", "audio")
    return t in allowed_types


def _cinema_catalog_row(file_id: str, finfo: dict) -> dict | None:
    if not finfo.get("cinema_public"):
        return None
    t = finfo.get("type")
    if t not in ("video", "text", "audio"):
        return None
    name = finfo.get("name", "") or ""
    nl = name.lower()
    if t == "video" and not nl.endswith((".mp4", ".webm", ".mkv")):
        return None
    if t == "text" and not nl.endswith(".txt"):
        return None
    if t == "audio" and not nl.endswith((".mp3", ".wav")):
        return None
    title = (finfo.get("cinema_title") or "").strip() or name
    desc = (finfo.get("cinema_description") or "").strip()
    subs = finfo.get("cinema_subtitles") or {}
    languages = []
    for lang, vtt_id in subs.items():
        languages.append({
            "code": lang,
            "name": config.TARGET_LANGUAGES.get(lang, lang.upper()),
            "vtt_id": vtt_id,
        })
    cover_path = _cinema_cover_jpg_path(file_id)
    has_cover = (
        bool(finfo.get("cinema_has_cover"))
        or cover_path.exists()
        or library.cinema_cover_exists_on_gcs(file_id)
    )
    kind = "video" if t == "video" else ("ebook" if t == "text" else "audio")
    return {
        "id": file_id,
        "kind": kind,
        "name": name,
        "title": title,
        "description": desc,
        "cover_url": f"/api/cinema/cover/{file_id}" if has_cover else None,
        "languages": languages if t == "video" else [],
        "updated_at": float(finfo.get("cinema_updated_at") or 0),
    }


def _cinema_vtt_allowed(vtt_id: str) -> bool:
    """True if this VTT is linked in cinema_subtitles of any published video."""
    index = library._load_index()
    for finfo in index.get("files", {}).values():
        if not finfo.get("cinema_public"):
            continue
        subs = finfo.get("cinema_subtitles") or {}
        if vtt_id in subs.values():
            return True
    return False


def _estimate_transcription_seconds(file_path: Path) -> int:
    """Rough estimate: based on file size (audio ~1 MB/min, transcription ~1x realtime)."""
    try:
        size_mb = file_path.stat().st_size / (1024 * 1024)
    except OSError:
        return 180  # default 3 min
    # MP4 can be large (video); MP3 ~1 MB/min. Use conservative estimate.
    if file_path.suffix.lower() == ".mp4":
        size_mb = min(size_mb / 10, size_mb)  # assume video is larger than audio
    est = int(size_mb * 50)  # ~50 sec per MB
    return max(60, min(est, 900))  # between 1 min and 15 min


def _get_gcs_bucket():
    if not (config.GCS_BUCKET_NAME or "").strip():
        raise HTTPException(500, "GCS_BUCKET_NAME is not set on the server.")
    return storage.Client().bucket(config.GCS_BUCKET_NAME)


def _signed_gcs_get_url(blob_name: str, expires_seconds: int = 1800) -> str:
    """Generate temporary signed GET URL for streaming files directly from GCS."""
    bucket = _get_gcs_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        raise HTTPException(404, "File not found")
    try:
        return blob.generate_signed_url(
            version="v4",
            expiration=expires_seconds,
            method="GET",
        )
    except Exception as e:
        msg = str(e).lower()
        if "private key" not in msg and "contains a token" not in msg and "sign" not in msg:
            raise
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(GoogleAuthRequest())
        sa_email = _metadata_service_account_email()
        if not sa_email:
            raise HTTPException(500, "Could not sign GCS URL: missing service account email.")
        return blob.generate_signed_url(
            version="v4",
            expiration=expires_seconds,
            method="GET",
            access_token=creds.token,
            service_account_email=sa_email,
        )


def _run_transcription_step(job_id: str, upload_path: Path, on_progress) -> list[dict] | None:
    """Run transcription step and return segments, or None if failed."""
    if upload_path.suffix.lower() == ".mp4":
        on_progress(2, "Extracting audio from video…")
    on_progress(5, "Sending to ElevenLabs for transcription… (please wait, this can take a few minutes)")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(transcribe_file, upload_path, config.ELEVENLABS_API_KEY, openai_api_key=config.OPENAI_API_KEY)
        try:
            segments = future.result(timeout=TRANSCRIPTION_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            set_job_progress(job_id, {
                "progress": 5,
                "message": "Transcription timed out.",
                "done": True,
                "error": "Transcription took longer than 15 minutes. Try a shorter file or check your connection.",
            })
            return None
        except Exception as e:
            set_job_progress(job_id, {
                "progress": 5,
                "message": "Transcription failed.",
                "done": True,
                "error": str(e),
            })
            return None

    if not segments:
        set_job_progress(job_id, {"progress": 0, "message": "Transcription failed.", "done": True, "error": "No segments."})
        return None

    return segments


def _run_translation_step(
    job_id: str, segments: list[dict], lang_codes: list[str], on_progress
) -> tuple[dict[str, list[str]], list[str]]:
    """Run translation step. Returns (translations, failure descriptions for any language that fell back to source)."""
    on_progress(25, "Transcription done. Translating…")

    # Let translation APIs auto-detect the source language
    source_lang = ""
    translations: dict[str, list[str]] = {}
    failures: list[str] = []
    n = len(lang_codes)
    for i, lang in enumerate(lang_codes):
        pct = 25 + int(65 * (i / n))
        label = config.TARGET_LANGUAGES.get(lang, lang)
        on_progress(pct, f"Translating ({label})…")
        try:
            translated = translate_segments(
                segments, lang, source_lang,
                config.DEEPL_API_KEY, config.OPENAI_API_KEY,
            )
            translations[lang] = translated
        except Exception as e:
            logger.warning("Translation failed for %s: %s", lang, e)
            failures.append(f"{label}: {e}")
            translations[lang] = [s["text"] for s in segments]

    return translations, failures


def _run_vtt_generation_step(segments: list[dict], translations: dict[str, list[str]], out_path: Path, on_progress) -> None:
    """Run VTT generation step."""
    on_progress(90, "Generating VTT file…")
    generate_vtt(segments, translations, out_path)
    _persist_job_output_to_gcs(out_path)
    on_progress(100, "Done.")


def _run_pipeline(
    job_id: str,
    upload_path: Path,
    out_path: Path,
    lang_codes: list[str],
    on_progress,
):
    """Run transcribe → translate → VTT in a thread; call on_progress(percent, message)."""
    try:
        # Step 1: Transcription
        segments = _run_transcription_step(job_id, upload_path, on_progress)
        if segments is None:
            return

        # Step 2: Translation
        translations, trans_failures = _run_translation_step(job_id, segments, lang_codes, on_progress)

        warn_msg = None
        err_msg = None
        if trans_failures:
            if len(trans_failures) >= len(lang_codes):
                err_msg = (
                    "Translation failed for all selected languages. "
                    "Check API keys (OpenAI for Kikongo/Lingala/etc., DeepL for Dutch/English/…). Details: "
                    + " | ".join(trans_failures)
                )
            else:
                warn_msg = "Some languages were not translated (original text kept): " + " | ".join(trans_failures)

        # Step 3: VTT Generation
        _run_vtt_generation_step(segments, translations, out_path, on_progress)

        set_job_progress(
            job_id,
            {
                "progress": 100,
                "message": "Done.",
                "done": True,
                "error": err_msg,
                "warning": warn_msg,
            },
        )
    except Exception as e:
        set_job_progress(job_id, {"progress": job_progress.get(job_id, {}).get("progress", 0), "message": str(e), "done": True, "error": str(e)})


def _run_transcription_only(
    job_id: str,
    upload_path: Path,
    out_path: Path,
    use_voice_isolation: bool,
    on_progress,
):
    """Run transcription only (no translation) → VTT with original text."""
    try:
        if upload_path.suffix.lower() == ".mp4":
            on_progress(5, "Extracting audio from video…")
        if use_voice_isolation:
            on_progress(8, "Isolating voice (optional)…")
        on_progress(10, "Sending to ElevenLabs for transcription… (please wait, this can take a few minutes)")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                transcribe_file,
                upload_path,
                config.ELEVENLABS_API_KEY,
                "scribe_v2",
                use_voice_isolation,
                config.VOICE_ISOLATION_API_KEY,
                config.OPENAI_API_KEY,
            )
            try:
                segments = future.result(timeout=TRANSCRIPTION_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                set_job_progress(job_id, {
                    "progress": 10,
                    "message": "Transcription timed out.",
                    "done": True,
                    "error": "Transcription took longer than 15 minutes.",
                })
                return
            except Exception as e:
                set_job_progress(job_id, {
                    "progress": 10,
                    "message": "Transcription failed.",
                    "done": True,
                    "error": str(e),
                })
                return
        if not segments:
            set_job_progress(job_id, {"progress": 0, "message": "Transcription failed.", "done": True, "error": "No segments."})
            return
        on_progress(90, "Generating VTT file…")
        # Generate VTT with only original text (no translations)
        translations = {"original": [s["text"] for s in segments]}
        generate_vtt(segments, translations, out_path)
        _persist_job_output_to_gcs(out_path)
        on_progress(100, "Done.")
        set_job_progress(job_id, {"progress": 100, "message": "Done.", "done": True, "error": None})
    except Exception as e:
        set_job_progress(job_id, {"progress": job_progress.get(job_id, {}).get("progress", 0), "message": str(e), "done": True, "error": str(e)})


def _run_transcription_text_only(
    job_id: str,
    upload_path: Path,
    out_path: Path,
    use_voice_isolation: bool,
    on_progress,
):
    """Run transcription only → plain text file (TXT)."""
    try:
        if upload_path.suffix.lower() == ".mp4":
            on_progress(5, "Extracting audio from video…")
        if use_voice_isolation:
            on_progress(8, "Isolating voice (optional)…")
        on_progress(10, "Sending to ElevenLabs for transcription… (please wait, this can take a few minutes)")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                transcribe_file,
                upload_path,
                config.ELEVENLABS_API_KEY,
                "scribe_v2",
                use_voice_isolation,
                config.VOICE_ISOLATION_API_KEY,
                config.OPENAI_API_KEY,
            )
            try:
                segments = future.result(timeout=TRANSCRIPTION_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                set_job_progress(job_id, {
                    "progress": 10,
                    "message": "Transcription timed out.",
                    "done": True,
                    "error": "Transcription took longer than 15 minutes.",
                })
                return
            except Exception as e:
                set_job_progress(job_id, {
                    "progress": 10,
                    "message": "Transcription failed.",
                    "done": True,
                    "error": str(e),
                })
                return

        if not segments:
            set_job_progress(job_id, {"progress": 0, "message": "Transcription failed.", "done": True, "error": "No segments."})
            return

        on_progress(92, "Writing TXT file…")
        text = "\n".join([(s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip()]).strip()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + ("\n" if text else ""), encoding="utf-8")
        _persist_job_output_to_gcs(out_path)

        on_progress(100, "Done.")
        set_job_progress(job_id, {"progress": 100, "message": "Done.", "done": True, "error": None})
    except Exception as e:
        set_job_progress(job_id, {"progress": job_progress.get(job_id, {}).get("progress", 0), "message": str(e), "done": True, "error": str(e)})


def _run_translation_only(
    job_id: str,
    vtt_path: Path,
    out_path: Path,
    lang_codes: list[str],
    on_progress,
):
    """Translate an existing VTT file to selected languages. on_progress(percent, message, eta_seconds=None)."""
    try:
        on_progress(5, "Parsing VTT file…")
        segments = parse_vtt(vtt_path)
        if not segments:
            set_job_progress(job_id, {"progress": 0, "message": "No segments found in VTT.", "done": True, "error": "Could not parse VTT file."})
            return
        # Rough estimate per segment per language (OpenAI chat can be slow on long texts)
        # Use a more realistic 6 seconds per segment per language so ETA is not unrealistically low.
        estimated_total = len(segments) * len(lang_codes) * 6
        on_progress(10, f"Found {len(segments)} segments. Translating…", estimated_total)

        source_lang = ""
        translations = {}
        failures: list[str] = []
        n = len(lang_codes)
        num_seg = len(segments)
        for i, lang in enumerate(lang_codes):
            lang_name = config.TARGET_LANGUAGES.get(lang, lang)

            def _progress_cb(seg_done: int, total_seg: int):
                pct = 10 + int(80 * (i + seg_done / max(1, total_seg)) / n)
                remaining = max(0, int(estimated_total * (1 - (pct - 10) / 80)))
                on_progress(min(94, pct), f"Translating ({lang_name})… {seg_done}/{total_seg}", remaining)

            on_progress(10 + int(80 * i / n), f"Translating ({lang_name})… 0/{num_seg}", max(0, int(estimated_total * (1 - i / n))))
            try:
                translated = translate_segments(
                    segments, lang, source_lang,
                    config.DEEPL_API_KEY, config.OPENAI_API_KEY,
                    progress_callback=_progress_cb,
                )
                translations[lang] = translated
            except Exception as e:
                logger.warning(
                    "VTT translate failed for language %s, using source text: %s",
                    lang,
                    e,
                    exc_info=True,
                )
                failures.append(f"{lang_name}: {e}")
                translations[lang] = [s["text"] for s in segments]
        warn_msg = None
        err_msg = None
        if failures:
            if len(failures) >= len(lang_codes):
                err_msg = (
                    "Translation failed for all selected languages. "
                    "For Lingala you need OPENAI_API_KEY; for Malagasy, Kikongo and Tshiluba a stronger model is used. "
                    f"(models: Lingala etc.: {config.OPENAI_TRANSLATION_MODEL}; Malagasy/Kikongo/Tshiluba: {config.OPENAI_TRANSLATION_MODEL_MG_KG_TS}). Details: "
                    + " | ".join(failures)
                )
            else:
                warn_msg = "Some languages were not translated (original text kept): " + " | ".join(failures)
        on_progress(95, "Generating VTT file…")
        generate_vtt(segments, translations, out_path)
        _persist_job_output_to_gcs(out_path)
        on_progress(100, "Done.")
        set_job_progress(
            job_id,
            {
                "progress": 100,
                "message": "Done.",
                "done": True,
                "error": err_msg,
                "warning": warn_msg,
                "eta_seconds": None,
            },
        )
    except Exception as e:
        set_job_progress(job_id, {"progress": job_progress.get(job_id, {}).get("progress", 0), "message": str(e), "done": True, "error": str(e)})


def _run_txt_translation_only(
    job_id: str,
    txt_path: Path,
    out_path: Path,
    lang_codes: list[str],
    on_progress,
):
    """Translate a plain-text file (paragraphs separated by blank lines) to selected languages."""
    try:
        on_progress(5, "Reading text file…", None)
        text = txt_path.read_text(encoding="utf-8")
        if not text.strip():
            set_job_progress(job_id, {"progress": 0, "message": "Empty file.", "done": True, "error": "File is empty."})
            return

        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        if not blocks:
            blocks = [text.strip()]
        segments = [{"text": b} for b in blocks]
        num_blocks = len(segments)

        estimated_total = num_blocks * len(lang_codes) * 6
        on_progress(10, f"Found {num_blocks} block(s). Translating…", estimated_total)

        source_lang = ""
        translations: dict[str, list[str]] = {}
        failures: list[str] = []
        n = len(lang_codes)

        for i, lang in enumerate(lang_codes):
            lang_name = config.TARGET_LANGUAGES.get(lang, lang)

            def _progress_cb(seg_done: int, total_seg: int):
                pct = 10 + int(80 * (i + seg_done / max(1, total_seg)) / n)
                remaining = max(0, int(estimated_total * (1 - (pct - 10) / 80)))
                on_progress(min(94, pct), f"Translating ({lang_name})… {seg_done}/{total_seg}", remaining)

            on_progress(10 + int(80 * i / n), f"Translating ({lang_name})… 0/{num_blocks}", max(0, int(estimated_total * (1 - i / n))))
            try:
                translated = translate_segments(
                    segments,
                    lang,
                    source_lang,
                    config.DEEPL_API_KEY,
                    config.OPENAI_API_KEY,
                    progress_callback=_progress_cb,
                )
                translations[lang] = translated
            except Exception as e:
                logger.warning(
                    "TXT translate failed for language %s, using source text: %s",
                    lang,
                    e,
                    exc_info=True,
                )
                failures.append(f"{lang_name}: {e}")
                translations[lang] = [s["text"] for s in segments]

        warn_msg = None
        err_msg = None
        if failures:
            if len(failures) >= len(lang_codes):
                err_msg = (
                    "Translation failed for all selected languages. "
                    "For Lingala you need OPENAI_API_KEY; for Malagasy, Kikongo and Tshiluba a stronger model is used. "
                    f"(models: Lingala etc.: {config.OPENAI_TRANSLATION_MODEL}; Malagasy/Kikongo/Tshiluba: {config.OPENAI_TRANSLATION_MODEL_MG_KG_TS}). Details: "
                    + " | ".join(failures)
                )
            else:
                warn_msg = "Some languages were not translated (original text kept): " + " | ".join(failures)

        on_progress(95, "Writing text file…", None)
        if n == 1:
            lang0 = lang_codes[0]
            body = "\n\n".join(translations.get(lang0, []))
            out_text = body + ("\n" if body else "")
        else:
            parts: list[str] = []
            for lang in lang_codes:
                lang_name = config.TARGET_LANGUAGES.get(lang, lang)
                tlist = translations.get(lang, [])
                body = "\n\n".join(tlist) if tlist else ""
                parts.append(f"=== {lang_name} ({lang}) ===\n\n{body.strip()}")
            out_text = "\n\n".join(parts) + "\n"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_text, encoding="utf-8")
        _persist_job_output_to_gcs(out_path)
        on_progress(100, "Done.", None)
        set_job_progress(
            job_id,
            {
                "progress": 100,
                "message": "Done.",
                "done": True,
                "error": err_msg,
                "warning": warn_msg,
                "eta_seconds": None,
            },
        )
    except Exception as e:
        set_job_progress(job_id, {"progress": job_progress.get(job_id, {}).get("progress", 0), "message": str(e), "done": True, "error": str(e)})


def _estimate_burn_seconds(video_path: Path) -> int:
    """Rough estimate for burn job from video file size (re-encode ~realtime)."""
    try:
        size_mb = video_path.stat().st_size / (1024 * 1024)
    except OSError:
        return 120
    est = int(size_mb * 3)  # ~3 sec per MB
    return max(60, min(est, 3600))


def _run_burn(
    job_id: str,
    video_path: Path,
    vtt_path: Path,
    out_path: Path,
    on_progress,
    burn_preset: str = "veryfast",
):
    """Burn VTT into video in a thread; call on_progress(percent, message, eta_seconds=None)."""
    try:
        on_progress(5, "Converting subtitles…", None)
        on_progress(10, "Burning subtitles into video… (this may take a few minutes)", None)
        def _ffmpeg_progress(frac: float) -> None:
            pct = 10 + int(max(0.0, min(1.0, frac)) * 88)
            on_progress(min(98, pct), "Burning subtitles into video…", None)

        burn.burn_subtitles_into_video(
            video_path,
            vtt_path,
            out_path,
            progress_callback=_ffmpeg_progress,
            video_preset=burn_preset,
        )
        _persist_job_output_to_gcs(out_path)
        on_progress(100, "Done.")
        set_job_progress(job_id, {"progress": 100, "message": "Done.", "done": True, "error": None, "eta_seconds": None})
    except Exception as e:
        set_job_progress(job_id, {"progress": 10, "message": "Burn failed.", "done": True, "error": str(e), "eta_seconds": None})





@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/api/health")
async def api_health_check():
    """API health check - tests API key availability and Firebase status."""
    health = {
        "status": "healthy",
        "apis": {
            "elevenlabs": bool(config.ELEVENLABS_API_KEY),
            "deepl": bool(config.DEEPL_API_KEY),
            "openai": bool(config.OPENAI_API_KEY),
        },
        "firebase": {
            "initialized": _firebase_initialized,
            "failed": _firebase_init_failed,
            "error": _firebase_error_msg if _firebase_init_failed else None,
        },
        # Resolved model IDs (from env or code defaults); not secrets
        "translation_models": {
            "OPENAI_TRANSLATION_MODEL": config.OPENAI_TRANSLATION_MODEL,
            "OPENAI_TRANSLATION_MODEL_MG_KG_TS": config.OPENAI_TRANSLATION_MODEL_MG_KG_TS,
        },
    }

    # Check if at least transcription and one translation API are available
    if not health["apis"]["elevenlabs"]:
        health["status"] = "unhealthy"
    elif not (health["apis"]["deepl"] or health["apis"]["openai"]):
        health["status"] = "degraded"

    return health


@app.get("/api/status/{job_id}")
@_api_limit("120/minute")
async def get_status(request: Request, job_id: str):
    """Return current progress for a job: { progress: 0-100, message, done, error? }."""
    if job_id not in job_progress:
        persisted = _load_persisted_job_progress(job_id)
        if not persisted:
            raise HTTPException(404, "Job not found.")
        return persisted
    return job_progress[job_id]


@app.post("/api/upload")
@_api_limit(config.UPLOAD_RATE_LIMIT)
async def upload_and_generate(
    request: Request,
    file: UploadFile = File(...),
    languages: str = Form("en,nl,pt"),  # comma-separated: en,nl,mg,kg,ts,ln,pt
):
    """
    Upload file and start background job. Returns job_id; poll GET /api/status/{job_id}
    for progress; when done, download VTT from GET /api/result/{job_id}.vtt
    """
    # Validate file type
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".mp4", ".mp3", ".mpeg", ".wav"):
        raise HTTPException(400, f"Unsupported file type: {suffix}. Only MP4, MP3, or WAV allowed.")

    # Validate languages
    lang_codes = [x.strip().lower() for x in languages.split(",") if x.strip()]
    allowed = set(config.TARGET_LANGUAGES)
    invalid_langs = [lang for lang in lang_codes if lang not in allowed]
    if invalid_langs:
        raise HTTPException(400, f"Unsupported languages: {', '.join(invalid_langs)}. Supported: {', '.join(allowed)}")

    if not lang_codes:
        lang_codes = ["en"]

    job_id = str(uuid.uuid4())
    upload_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    out_path = config.OUTPUT_DIR / f"{job_id}.vtt"

    max_b = config.MAX_UPLOAD_BYTES
    try:
        with upload_path.open("wb") as dest:
            if max_b is None:
                shutil.copyfileobj(file.file, dest)
            else:
                total = 0
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_b:
                        raise HTTPException(
                            413,
                            f"File too large. Maximum size is {max_b // (1024 * 1024)}MB.",
                        )
                    dest.write(chunk)
    except HTTPException:
        upload_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload failed: {e}")

    def on_progress(percent: int, message: str):
        set_job_progress(job_id, {"progress": percent, "message": message, "done": False, "error": None})

    set_job_progress(job_id, {"progress": 0, "message": "Starting…", "done": False, "error": None})

    asyncio.create_task(asyncio.to_thread(_run_pipeline, job_id, upload_path, out_path, lang_codes, on_progress))

    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.get("/api/result/{job_id}.vtt")
async def download_vtt(job_id: str):
    """Download the generated VTT file."""
    path = config.OUTPUT_DIR / f"{job_id}.vtt"
    if path.is_file():
        return FileResponse(path, filename=f"subtitles_{job_id}.vtt", media_type="text/vtt")
    data = _fetch_job_output_bytes(f"{job_id}.vtt")
    if data is None:
        raise HTTPException(404, "VTT file not found.")
    return Response(
        content=data,
        media_type="text/vtt",
        headers={"Content-Disposition": f'attachment; filename="subtitles_{job_id}.vtt"'},
    )


@app.get("/api/result/{job_id}.txt")
async def download_txt(job_id: str):
    """Download the generated TXT transcript file."""
    path = config.OUTPUT_DIR / f"{job_id}.txt"
    if path.is_file():
        return FileResponse(path, filename=f"transcript_{job_id}.txt", media_type="text/plain")
    data = _fetch_job_output_bytes(f"{job_id}.txt")
    if data is None:
        raise HTTPException(404, "TXT file not found.")
    return Response(
        content=data,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="transcript_{job_id}.txt"'},
    )


# ============ STEP 1: Transcription only (VTT/TXT) ============

@app.post("/api/transcribe")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def transcribe_only(request: Request, file: UploadFile = File(...), isolate_voice: str = Form("false")):
    """
    Step 1: Upload audio/video → transcribe only (no translation).
    Returns job_id; poll /api/status/{job_id}; download VTT from /api/result/{job_id}.vtt
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".mp4", ".mp3", ".mpeg", ".wav"):
        raise HTTPException(400, "Only MP4, MP3, or WAV allowed.")

    job_id = str(uuid.uuid4())
    upload_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    out_path = config.OUTPUT_DIR / f"{job_id}.vtt"

    try:
        with upload_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")

    estimated_sec = _estimate_transcription_seconds(upload_path)

    def on_progress(percent: int, message: str, eta_seconds: int | None = None):
        eta = eta_seconds
        if eta is None and percent < 100 and estimated_sec:
            eta = max(0, int(estimated_sec * (1 - percent / 100)))
        set_job_progress(job_id, {
            "progress": percent,
            "message": message,
            "done": False,
            "error": None,
            "eta_seconds": eta if percent < 100 else None,
        })

    use_voice_isolation = str(isolate_voice).lower() in ("1", "true", "yes", "on")
    set_job_progress(job_id, {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": estimated_sec})
    asyncio.create_task(asyncio.to_thread(_run_transcription_only, job_id, upload_path, out_path, use_voice_isolation, on_progress))

    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.post("/api/transcribe-library")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def transcribe_only_from_library(
    request: Request,
    file_id: str = Form(...),
    isolate_voice: str = Form("false"),
):
    """
    Step 1: Transcribe a file that already exists in Library (no browser re-upload).
    Returns job_id; poll /api/status/{job_id}; download VTT from /api/result/{job_id}.vtt
    """
    lib = library.get_file_path(file_id)
    if not lib:
        raise HTTPException(404, "File not found")
    lib_path, filename = lib

    suffix = Path(filename).suffix.lower()
    if suffix not in (".mp4", ".mp3", ".mpeg", ".wav"):
        raise HTTPException(400, "Only MP4, MP3, or WAV allowed.")

    job_id = str(uuid.uuid4())
    upload_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    out_path = config.OUTPUT_DIR / f"{job_id}.vtt"

    try:
        shutil.copyfile(str(lib_path), str(upload_path))
    except Exception as e:
        raise HTTPException(500, f"Copy from Library failed: {e}")

    estimated_sec = _estimate_transcription_seconds(upload_path)

    def on_progress(percent: int, message: str, eta_seconds: int | None = None):
        eta = eta_seconds
        if eta is None and percent < 100 and estimated_sec:
            eta = max(0, int(estimated_sec * (1 - percent / 100)))
        set_job_progress(job_id, {
            "progress": percent,
            "message": message,
            "done": False,
            "error": None,
            "eta_seconds": eta if percent < 100 else None,
        })

    use_voice_isolation = str(isolate_voice).lower() in ("1", "true", "yes", "on")
    set_job_progress(job_id, {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": estimated_sec})
    asyncio.create_task(asyncio.to_thread(_run_transcription_only, job_id, upload_path, out_path, use_voice_isolation, on_progress))
    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.post("/api/transcribe-text")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def transcribe_text_only(
    request: Request,
    file: UploadFile = File(...),
    isolate_voice: str = Form("false"),
):
    """
    Upload audio/video → transcribe only (no subtitles) → TXT.
    Returns job_id; poll /api/status/{job_id}; download TXT from /api/result/{job_id}.txt
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".mp4", ".mp3", ".mpeg", ".wav"):
        raise HTTPException(400, "Only MP4, MP3, or WAV allowed.")

    job_id = str(uuid.uuid4())
    upload_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    out_path = config.OUTPUT_DIR / f"{job_id}.txt"

    try:
        with upload_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")

    estimated_sec = _estimate_transcription_seconds(upload_path)

    def on_progress(percent: int, message: str, eta_seconds: int | None = None):
        eta = eta_seconds
        if eta is None and percent < 100 and estimated_sec:
            eta = max(0, int(estimated_sec * (1 - percent / 100)))
        set_job_progress(job_id, {
            "progress": percent,
            "message": message,
            "done": False,
            "error": None,
            "eta_seconds": eta if percent < 100 else None,
        })

    use_voice_isolation = str(isolate_voice).lower() in ("1", "true", "yes", "on")
    set_job_progress(job_id, {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": estimated_sec})
    asyncio.create_task(asyncio.to_thread(_run_transcription_text_only, job_id, upload_path, out_path, use_voice_isolation, on_progress))

    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.post("/api/transcribe-text-library")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def transcribe_text_only_from_library(
    request: Request,
    file_id: str = Form(...),
    isolate_voice: str = Form("false"),
):
    """
    Transcribe a Library audio/video file to TXT (no browser re-upload).
    Returns job_id immediately; copy from library + transcription run in a background thread
    so the HTTP request is not blocked on large files. Poll /api/status/{job_id}; download
    TXT from /api/result/{job_id}.txt
    """
    lib = library.get_file_path(file_id)
    if not lib:
        raise HTTPException(404, "File not found")
    lib_path, filename = lib

    suffix = Path(filename).suffix.lower()
    if suffix not in (".mp4", ".mp3", ".mpeg", ".wav"):
        raise HTTPException(400, "Only MP4, MP3, or WAV allowed.")

    job_id = str(uuid.uuid4())
    upload_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    out_path = config.OUTPUT_DIR / f"{job_id}.txt"
    lib_path_str = str(lib_path)
    use_voice_isolation = str(isolate_voice).lower() in ("1", "true", "yes", "on")

    def worker() -> None:
        try:
            set_job_progress(job_id, {
                "progress": 0,
                "message": "Copying from library…",
                "done": False,
                "error": None,
                "eta_seconds": None,
            })
            shutil.copyfile(lib_path_str, str(upload_path))
            estimated_sec = _estimate_transcription_seconds(upload_path)

            def on_progress(percent: int, message: str, eta_seconds: int | None = None):
                eta = eta_seconds
                if eta is None and percent < 100 and estimated_sec:
                    eta = max(0, int(estimated_sec * (1 - percent / 100)))
                set_job_progress(job_id, {
                    "progress": percent,
                    "message": message,
                    "done": False,
                    "error": None,
                    "eta_seconds": eta if percent < 100 else None,
                })

            set_job_progress(job_id, {
                "progress": 0,
                "message": "Starting…",
                "done": False,
                "error": None,
                "eta_seconds": estimated_sec,
            })
            _run_transcription_text_only(job_id, upload_path, out_path, use_voice_isolation, on_progress)
        except Exception as e:
            logger.exception("transcribe-text-library worker failed")
            set_job_progress(job_id, {
                "progress": 0,
                "message": str(e),
                "done": True,
                "error": f"Copy from Library failed: {e}",
                "eta_seconds": None,
            })

    set_job_progress(job_id, {
        "progress": 0,
        "message": "Queued…",
        "done": False,
        "error": None,
        "eta_seconds": None,
    })
    asyncio.create_task(asyncio.to_thread(worker))
    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


# ============ STEP 1 (Cloud Run): Transcription with GCS upload ============

@app.post("/api/gcs/upload-url")
@_api_limit("10/10 minutes")
async def gcs_upload_url(
    request: Request,
    filename: str = Form(...),
    content_type: str = Form("application/octet-stream"),
):
    """
    Get a signed URL to upload a file directly to GCS (avoids Cloud Run 413 limits).
    Returns: { upload_url, object_name }
    """
    try:
        bucket = _get_gcs_bucket()
        suffix = Path(filename or "").suffix.lower()
        if suffix not in (".mp4", ".mp3", ".mpeg", ".wav", ".vtt", ".txt", ".webm", ".mkv"):
            raise HTTPException(400, "Only MP4, MP3, MPEG, WAV, WebM, MKV, VTT, or TXT allowed.")

        object_name = f"library/files/upload_{uuid.uuid4()}{suffix}"
        blob = bucket.blob(object_name)
        try:
            # Works when credentials include a private key (e.g., local service account JSON).
            upload_url = blob.generate_signed_url(
                version="v4",
                expiration=3600,
                method="PUT",
                content_type=content_type or "application/octet-stream",
            )
        except Exception as e:
            # On Cloud Run, ADC is often "token-only" and cannot sign locally.
            # Fallback: use IAM signBlob by supplying an access token + service account email.
            msg = str(e).lower()
            if "private key" not in msg and "contains a token" not in msg and "sign" not in msg:
                raise

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(GoogleAuthRequest())
            sa_email = _metadata_service_account_email()
            if not sa_email:
                raise HTTPException(
                    500,
                    "Could not create signed URL: missing service account email for IAM signing. "
                    "Set a service account on Cloud Run (recommended).",
                )

            upload_url = blob.generate_signed_url(
                version="v4",
                expiration=3600,
                method="PUT",
                content_type=content_type or "application/octet-stream",
                access_token=creds.token,
                service_account_email=sa_email,
            )
        return {"upload_url": upload_url, "object_name": object_name}
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "private key" in msg.lower() or "credentials" in msg.lower() or "sign" in msg.lower():
            msg += (
                " — On Cloud Run ensure the attached service account can sign blobs (IAMCredentials signBlob) "
                "and has bucket access; locally set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON key, "
                "or use http://127.0.0.1 so uploads skip GCS."
            )
        raise HTTPException(500, f"Could not create signed URL: {msg}")


@app.post("/api/gcs/resumable-session")
@_api_limit("10/10 minutes")
async def gcs_resumable_session(
    request: Request,
    filename: str = Form(...),
    content_type: str = Form("application/octet-stream"),
):
    """
    Create a resumable upload session URL for direct browser -> GCS chunk uploads.
    Returns: { session_url, object_name }
    """
    try:
        bucket = _get_gcs_bucket()
        suffix = Path(filename or "").suffix.lower()
        if suffix not in (".mp4", ".mp3", ".mpeg", ".wav", ".vtt", ".txt", ".webm", ".mkv"):
            raise HTTPException(400, "Only MP4, MP3, MPEG, WAV, WebM, MKV, VTT, or TXT allowed.")
        object_name = f"library/files/upload_{uuid.uuid4()}{suffix}"
        blob = bucket.blob(object_name)
        session_url = blob.create_resumable_upload_session(
            content_type=content_type or "application/octet-stream",
            origin=request.headers.get("origin"),
        )
        return {"session_url": session_url, "object_name": object_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not create resumable session: {e}")


@app.post("/api/burn-gcs")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def burn_into_video_gcs(
    request: Request,
    video_object_name: str = Form(...),
    vtt_object_name: str = Form(...),
    burn_preset: str = Form("veryfast"),
):
    """
    Burn subtitles into video from files uploaded to GCS.
    Expects both objects to exist in the configured bucket.
    """
    v_suffix = Path(video_object_name or "").suffix.lower()
    if v_suffix not in (".mp4", ".webm", ".mkv"):
        raise HTTPException(400, "Video must be MP4, WebM, or MKV.")
    if Path(vtt_object_name or "").suffix.lower() != ".vtt":
        raise HTTPException(400, "Subtitle file must be VTT.")
    burn_preset = (burn_preset or "veryfast").strip().lower()
    if burn_preset not in ("veryfast", "ultrafast"):
        raise HTTPException(400, "burn_preset must be veryfast or ultrafast.")

    job_id = str(uuid.uuid4())
    video_path = config.UPLOAD_DIR / f"{job_id}_video{v_suffix}"
    vtt_path = config.UPLOAD_DIR / f"{job_id}_burn.vtt"
    out_path = config.OUTPUT_DIR / f"{job_id}_burned.mp4"

    def on_progress(percent: int, message: str, eta_seconds: int | None = None):
        eta = eta_seconds
        set_job_progress(job_id, {
            "progress": percent,
            "message": message,
            "done": False,
            "error": None,
            "eta_seconds": eta if percent < 100 else None,
        })

    # Important: return quickly (avoid request timeouts for large GCS downloads).
    set_job_progress(job_id, {"progress": 0, "message": "Queued…", "done": False, "error": None, "eta_seconds": None})

    def _download_and_burn():
        try:
            logger.info(f"Starting GCS burn job {job_id} for video: {video_object_name}, vtt: {vtt_object_name}")
            bucket = _get_gcs_bucket()
            v_blob = bucket.blob(video_object_name)
            s_blob = bucket.blob(vtt_object_name)

            if not v_blob.exists():
                raise HTTPException(404, "Uploaded video not found in GCS.")
            if not s_blob.exists():
                raise HTTPException(404, "Uploaded VTT not found in GCS.")

            logger.info(f"GCS blobs exist for job {job_id}, video size: {v_blob.size}, vtt size: {s_blob.size}")

            # Download with progress so users can see it's moving.
            _download_blob_with_progress(
                v_blob,
                video_path,
                job_id,
                start_percent=1,
                end_percent=35,
                label="Downloading video from storage…",
            )
            _download_blob_with_progress(
                s_blob,
                vtt_path,
                job_id,
                start_percent=36,
                end_percent=40,
                label="Downloading subtitles from storage…",
                chunk_size=512 * 1024,
            )

            logger.info(f"Downloads complete for job {job_id}, starting burn")
            # Now run the burn pipeline (ffmpeg)
            on_progress(45, "Starting burn…")
            _run_burn(job_id, video_path, vtt_path, out_path, on_progress, burn_preset)
            logger.info(f"Burn complete for job {job_id}")
        except HTTPException as e:
            logger.error(f"Burn job {job_id} failed with HTTP error: {e.detail}")
            set_job_progress(job_id, {"progress": 100, "message": "Failed", "done": True, "error": str(e.detail), "eta_seconds": None})
        except GoogleAPIError as e:
            logger.error(f"Burn job {job_id} failed with GCS error: {e}")
            set_job_progress(job_id, {"progress": 100, "message": "Failed", "done": True, "error": f"GCS error: {e}", "eta_seconds": None})
        except Exception as e:
            logger.error(f"Burn job {job_id} failed with unexpected error: {e}", exc_info=True)
            set_job_progress(job_id, {"progress": 100, "message": "Failed", "done": True, "error": f"Failed to download from GCS: {e}", "eta_seconds": None})

    asyncio.create_task(asyncio.to_thread(_download_and_burn))

    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.post("/api/transcribe-gcs")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def transcribe_only_gcs(
    request: Request,
    object_name: str = Form(...),
    isolate_voice: str = Form("false"),
):
    """
    Start transcription from a file already uploaded to GCS.
    Returns job_id immediately; GCS download + transcription run in a background thread
    so the browser can poll /api/status/{job_id} while the file is copied from GCS.
    """
    suffix = Path(object_name or "").suffix.lower()
    if suffix not in (".mp4", ".mp3", ".mpeg", ".wav"):
        raise HTTPException(400, "Only MP4, MP3, or WAV allowed.")

    job_id = str(uuid.uuid4())
    upload_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    out_path = config.OUTPUT_DIR / f"{job_id}.vtt"

    use_voice_isolation = str(isolate_voice).lower() in ("1", "true", "yes", "on")

    def worker() -> None:
        estimated_sec = 180
        try:
            set_job_progress(
                job_id,
                {"progress": 0, "message": "Downloading from storage…", "done": False, "error": None, "eta_seconds": None},
            )
            bucket = _get_gcs_bucket()
            blob = bucket.blob(object_name)
            if not blob.exists():
                set_job_progress(
                    job_id,
                    {
                        "progress": 0,
                        "message": "File not found.",
                        "done": True,
                        "error": "Uploaded file not found in GCS.",
                        "eta_seconds": None,
                    },
                )
                return
            try:
                if blob.size:
                    size_mb = float(blob.size) / (1024 * 1024)
                    if suffix == ".mp4":
                        size_mb = min(size_mb / 10, size_mb)
                    estimated_sec = max(60, min(int(size_mb * 50), 900))
            except Exception:
                pass

            blob.download_to_filename(str(upload_path))

            def on_progress(percent: int, message: str, eta_seconds: int | None = None):
                eta = eta_seconds
                if eta is None and percent < 100 and estimated_sec:
                    eta = max(0, int(estimated_sec * (1 - percent / 100)))
                set_job_progress(job_id, {
                    "progress": percent,
                    "message": message,
                    "done": False,
                    "error": None,
                    "eta_seconds": eta if percent < 100 else None,
                })

            set_job_progress(
                job_id,
                {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": estimated_sec},
            )
            _run_transcription_only(job_id, upload_path, out_path, use_voice_isolation, on_progress)
        except GoogleAPIError as e:
            logger.exception("transcribe-gcs GCS error")
            set_job_progress(
                job_id,
                {"progress": 0, "message": str(e), "done": True, "error": f"GCS error: {e}", "eta_seconds": None},
            )
        except Exception as e:
            logger.exception("transcribe-gcs worker failed")
            set_job_progress(
                job_id,
                {"progress": 0, "message": str(e), "done": True, "error": f"Failed to download from GCS: {e}", "eta_seconds": None},
            )

    set_job_progress(job_id, {"progress": 0, "message": "Queued…", "done": False, "error": None, "eta_seconds": None})
    asyncio.create_task(asyncio.to_thread(worker))
    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.post("/api/transcribe-text-gcs")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def transcribe_text_only_gcs(
    request: Request,
    object_name: str = Form(...),
    isolate_voice: str = Form("false"),
):
    """
    Start text transcription from a file already uploaded to GCS.
    Returns job_id immediately; GCS download + transcription run in a background thread.
    """
    suffix = Path(object_name or "").suffix.lower()
    if suffix not in (".mp4", ".mp3", ".mpeg", ".wav"):
        raise HTTPException(400, "Only MP4, MP3, or WAV allowed.")

    job_id = str(uuid.uuid4())
    upload_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    out_path = config.OUTPUT_DIR / f"{job_id}.txt"

    use_voice_isolation = str(isolate_voice).lower() in ("1", "true", "yes", "on")

    def worker() -> None:
        estimated_sec = 180
        try:
            set_job_progress(
                job_id,
                {"progress": 0, "message": "Downloading from storage…", "done": False, "error": None, "eta_seconds": None},
            )
            bucket = _get_gcs_bucket()
            blob = bucket.blob(object_name)
            if not blob.exists():
                set_job_progress(
                    job_id,
                    {
                        "progress": 0,
                        "message": "File not found.",
                        "done": True,
                        "error": "Uploaded file not found in GCS.",
                        "eta_seconds": None,
                    },
                )
                return
            try:
                if blob.size:
                    size_mb = float(blob.size) / (1024 * 1024)
                    if suffix == ".mp4":
                        size_mb = min(size_mb / 10, size_mb)
                    estimated_sec = max(60, min(int(size_mb * 50), 900))
            except Exception:
                pass

            blob.download_to_filename(str(upload_path))

            def on_progress(percent: int, message: str, eta_seconds: int | None = None):
                eta = eta_seconds
                if eta is None and percent < 100 and estimated_sec:
                    eta = max(0, int(estimated_sec * (1 - percent / 100)))
                set_job_progress(job_id, {
                    "progress": percent,
                    "message": message,
                    "done": False,
                    "error": None,
                    "eta_seconds": eta if percent < 100 else None,
                })

            set_job_progress(
                job_id,
                {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": estimated_sec},
            )
            _run_transcription_text_only(job_id, upload_path, out_path, use_voice_isolation, on_progress)
        except GoogleAPIError as e:
            logger.exception("transcribe-text-gcs GCS error")
            set_job_progress(
                job_id,
                {"progress": 0, "message": str(e), "done": True, "error": f"GCS error: {e}", "eta_seconds": None},
            )
        except Exception as e:
            logger.exception("transcribe-text-gcs worker failed")
            set_job_progress(
                job_id,
                {"progress": 0, "message": str(e), "done": True, "error": f"Failed to download from GCS: {e}", "eta_seconds": None},
            )

    set_job_progress(job_id, {"progress": 0, "message": "Queued…", "done": False, "error": None, "eta_seconds": None})
    asyncio.create_task(asyncio.to_thread(worker))
    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


def _tts_text_from_bytes(filename: str, data: bytes) -> str:
    suffix = Path(filename or '').suffix.lower()
    if suffix == '.vtt':
        tmp = config.UPLOAD_DIR / f"{uuid.uuid4()}_tts_input.vtt"
        try:
            tmp.write_bytes(data)
            segs = parse_vtt(tmp)
            return "\n".join([(s.get("text") or "").strip() for s in segs if (s.get("text") or "").strip()]).strip()
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    # default txt/plain
    return (data or b'').decode('utf-8', 'ignore').strip()


def _write_audio_stream_to_file(audio_stream, out_path: Path) -> None:
    if audio_stream is None:
        raise RuntimeError('No audio returned from ElevenLabs TTS.')
    if isinstance(audio_stream, (bytes, bytearray)):
        out_path.write_bytes(bytes(audio_stream))
    elif hasattr(audio_stream, 'read'):
        out_path.write_bytes(audio_stream.read())
    else:
        chunks = bytearray()
        for chunk in audio_stream:
            if chunk:
                chunks.extend(chunk)
        out_path.write_bytes(bytes(chunks))

    # Guard against silent API failures returning empty payloads.
    try:
        if out_path.stat().st_size <= 0:
            raise RuntimeError('TTS provider returned empty audio data.')
    except FileNotFoundError:
        raise RuntimeError('TTS audio file was not created.')


def _split_text_for_tts(text: str, max_chars: int = 1200) -> list[str]:
    """Split long text into <=max_chars chunks on paragraph/sentence boundaries."""
    src = (text or '').strip()
    if not src:
        return []
    paras = [p.strip() for p in src.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur = ''

    def flush() -> None:
        nonlocal cur
        if cur.strip():
            chunks.append(cur.strip())
        cur = ''

    for ptxt in paras:
        # If paragraph itself is huge, split by sentence-ish boundaries.
        parts = [ptxt]
        if len(ptxt) > max_chars:
            import re
            parts = [s.strip() for s in re.split(r'(?<=[.!?])\s+', ptxt) if s.strip()]

        for part in parts:
            if len(part) > max_chars:
                # Final fallback: hard split.
                for i in range(0, len(part), max_chars):
                    piece = part[i:i + max_chars]
                    if cur:
                        flush()
                    chunks.append(piece)
                continue

            candidate = (cur + ("\n\n" if cur else "") + part).strip()
            if len(candidate) <= max_chars:
                cur = candidate
            else:
                flush()
                cur = part

    flush()
    return chunks


def _concat_mp3_parts(parts: list[Path], out_mp3: Path) -> None:
    """Concatenate MP3 parts to one file using ffmpeg concat demuxer."""
    if not parts:
        raise RuntimeError('No audio parts to concatenate.')
    if len(parts) == 1:
        out_mp3.write_bytes(parts[0].read_bytes())
        return

    list_file = out_mp3.with_suffix('.concat.txt')
    try:
        lines = []
        for pth in parts:
            safe = str(pth.resolve()).replace("'", "'\\''")
            lines.append(f"file '{safe}'")
        list_file.write_text("\n".join(lines) + "\n", encoding='utf-8')

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', str(list_file.resolve()),
            '-c', 'copy',
            str(out_mp3.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if res.returncode != 0:
            err = (res.stderr or '').strip()
            raise RuntimeError(err.splitlines()[-1] if err else 'ffmpeg concat failed')
    finally:
        try:
            list_file.unlink(missing_ok=True)
        except Exception:
            pass


def _format_tts_elevenlabs_error(exc: BaseException) -> str:
    """Readable message for job status when ElevenLabs TTS fails (quota, permissions, etc.)."""
    if isinstance(exc, ApiError):
        body = exc.body
        detail = None
        if isinstance(body, dict):
            detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
        if isinstance(detail, dict):
            status = (detail.get("status") or detail.get("code") or "").lower()
            msg = detail.get("message") or detail.get("detail") or str(detail)
            if status == "quota_exceeded" or "quota" in status:
                return (
                    "ElevenLabs: niet genoeg credits voor deze aanvraag. "
                    f"({msg}) "
                    "Voeg credits toe in het ElevenLabs-dashboard, of gebruik een kortere tekst. "
                    "Let op: de totale kosten voor heel je tekst zijn de som van alle stukjes; "
                    "kleinere stukken helpen alleen als één request te veel credits in één keer vraagt."
                )
            if status in ("missing_permissions", "unauthorized") or exc.status_code == 401:
                return f"ElevenLabs TTS: {msg}"
        if exc.status_code is not None:
            return f"ElevenLabs API error ({exc.status_code}): {body if body is not None else exc}"
    return str(exc)




def _openai_tts_to_file(text: str, out_path: Path, lang: str) -> None:
    """Fallback TTS via OpenAI. Writes MP3 to out_path."""
    if not (config.OPENAI_API_KEY or '').strip():
        raise RuntimeError('OPENAI_API_KEY is not set for OpenAI TTS fallback.')

    # Only enable fallback for languages we explicitly allow.
    allowed = {
        'en', 'nl', 'fr', 'es', 'pt', 'zh',
    }
    if (lang or '').strip().lower() not in allowed:
        raise RuntimeError(f'OpenAI TTS fallback is not enabled for language: {lang}')

    # Built-in voice set; keep simple default.
    voice = 'coral'
    client = OpenAI(api_key=config.OPENAI_API_KEY.strip())
    # Use streaming response to write directly to file (avoids holding large audio in memory).
    with client.audio.speech.with_streaming_response.create(
        model='gpt-4o-mini-tts',
        voice=voice,
        input=text,
    ) as resp:
        resp.stream_to_file(out_path)


def _run_tts_job(job_id: str, text: str, langs: list[str]) -> None:
    out_zip = config.OUTPUT_DIR / f"{job_id}_tts.zip"
    tmp_dir = config.OUTPUT_DIR / f"{job_id}_tts_files"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        if not text.strip():
            set_job_progress(job_id, {"progress": 0, "message": "Input text is empty.", "done": True, "error": "Input text is empty."})
            return
        if not langs:
            set_job_progress(job_id, {"progress": 0, "message": "No languages selected.", "done": True, "error": "Select at least one language."})
            return

        client = ElevenLabs(api_key=config.ELEVENLABS_TTS_API_KEY)
        voice_map: dict[str, str] = {}
        for lang in langs:
            v = (config.TTS_VOICE_IDS.get(lang) or '').strip()
            if not v:
                v = config.TTS_DEFAULT_VOICE_ID
            if not v:
                set_job_progress(
                    job_id,
                    {
                        "progress": 0,
                        "message": f"Missing voice for {lang}.",
                        "done": True,
                        "error": (
                            f"No ElevenLabs voice configured for language '{lang}'. "
                            "Set TTS_DEFAULT_VOICE_ID or TTS_VOICE_IDS_JSON on the server."
                        ),
                    },
                )
                return
            voice_map[lang] = v

        text_chunks = _split_text_for_tts(text, max_chars=config.TTS_MAX_CHUNK_CHARS)
        if not text_chunks:
            set_job_progress(job_id, {"progress": 0, "message": "Input text is empty.", "done": True, "error": "Input text is empty."})
            return

        items = list(voice_map.items())
        n = len(items)
        total_chunks = len(text_chunks)
        total_steps = max(n * total_chunks, 1)
        generated: list[Path] = []
        for i, (lang, voice_id) in enumerate(items):
            set_job_progress(job_id, {"progress": 5, "message": f"Generating audio ({lang})...", "done": False, "error": None})
            part_files: list[Path] = []
            for j, chunk_text in enumerate(text_chunks):
                # Keep progress moving while long requests are processed chunk-by-chunk.
                done_steps = (i * total_chunks) + j
                pct = 5 + int(80 * (done_steps / total_steps))
                set_job_progress(
                    job_id,
                    {
                        "progress": pct,
                        "message": f"Generating audio ({lang}) chunk {j + 1}/{total_chunks}...",
                        "done": False,
                        "error": None,
                    },
                )

                part_path = tmp_dir / f"{lang}.part{j:03d}.mp3"
                try:
                    audio_stream = client.text_to_speech.convert(
                        voice_id=voice_id,
                        model_id=config.TTS_MODEL_ID,
                        output_format='mp3_44100_128',
                        text=chunk_text,
                    )
                    _write_audio_stream_to_file(audio_stream, part_path)
                except Exception as e:
                    # Fallback: OpenAI TTS (only for allowed languages)
                    set_job_progress(job_id, {"progress": pct, "message": f"ElevenLabs failed; trying OpenAI TTS ({lang}) chunk {j + 1}/{total_chunks}...", "done": False, "error": None})
                    _openai_tts_to_file(chunk_text, part_path, lang)

                part_files.append(part_path)

            out_mp3 = tmp_dir / f"{lang}.mp3"
            set_job_progress(job_id, {"progress": 88, "message": f"Merging chunks ({lang})...", "done": False, "error": None})
            _concat_mp3_parts(part_files, out_mp3)
            generated.append(out_mp3)
            # Persist MP3 outside tmp_dir so it can be saved to Library later.
            persisted = config.OUTPUT_DIR / f"{job_id}_tts_{lang}.mp3"
            try:
                persisted.write_bytes(out_mp3.read_bytes())
                _persist_job_output_to_gcs(persisted)
            except Exception:
                pass

        valid_generated = [p for p in generated if p.exists() and p.stat().st_size > 0]
        if not valid_generated:
            raise RuntimeError('No valid MP3 audio was generated for ZIP packaging.')

        set_job_progress(job_id, {"progress": 92, "message": "Packaging ZIP?", "done": False, "error": None})
        with zipfile.ZipFile(out_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for pth in valid_generated:
                zf.write(pth, arcname=pth.name)

        _persist_job_output_to_gcs(out_zip)

        set_job_progress(job_id, {"progress": 100, "message": "Done.", "done": True, "error": None})
    except Exception as e:
        err_msg = _format_tts_elevenlabs_error(e)
        set_job_progress(
            job_id,
            {
                "progress": job_progress.get(job_id, {}).get("progress", 0),
                "message": err_msg,
                "done": True,
                "error": err_msg,
            },
        )
    finally:
        try:
            if tmp_dir.exists():
                for f in tmp_dir.glob('*'):
                    try:
                        f.unlink(missing_ok=True)
                    except Exception:
                        pass
                tmp_dir.rmdir()
        except Exception:
            pass


@app.post('/api/tts-generate')
@_api_limit('5/10 minutes')
async def tts_generate(
    request: Request,
    file: UploadFile = File(...),
    languages: str = Form('en'),
):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ('.txt', '.vtt'):
        raise HTTPException(400, 'Only TXT or VTT files allowed.')
    try:
        raw = await file.read()
    except Exception as e:
        raise HTTPException(500, f'Upload failed: {e}')

    lang_codes = [x.strip().lower() for x in (languages or '').split(',') if x.strip()]
    allowed = set(config.TARGET_LANGUAGES)
    lang_codes = [c for c in lang_codes if c in allowed]
    if not lang_codes:
        raise HTTPException(400, 'Select at least one valid language.')
    # UI supports a single language selection for TTS generation.
    lang_codes = lang_codes[:1]

    text = _tts_text_from_bytes(file.filename or 'input.txt', raw)
    job_id = str(uuid.uuid4())
    set_job_progress(job_id, {"progress": 0, "message": "Queued?", "done": False, "error": None})
    asyncio.create_task(asyncio.to_thread(_run_tts_job, job_id, text, lang_codes))
    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.post('/api/tts-generate-library')
@_api_limit('5/10 minutes')
async def tts_generate_library(
    request: Request,
    file_id: str = Form(...),
    languages: str = Form('en'),
):
    lib = library.get_file(file_id)
    if not lib:
        raise HTTPException(404, 'File not found')
    data, filename = lib
    suffix = Path(filename or '').suffix.lower()
    if suffix not in ('.txt', '.vtt'):
        raise HTTPException(400, 'Only TXT or VTT files allowed.')
    lang_codes = [x.strip().lower() for x in (languages or '').split(',') if x.strip()]
    allowed = set(config.TARGET_LANGUAGES)
    lang_codes = [c for c in lang_codes if c in allowed]
    if not lang_codes:
        raise HTTPException(400, 'Select at least one valid language.')
    # UI supports a single language selection for TTS generation.
    lang_codes = lang_codes[:1]

    text = _tts_text_from_bytes(filename, data)
    job_id = str(uuid.uuid4())
    set_job_progress(job_id, {"progress": 0, "message": "Queued?", "done": False, "error": None})
    asyncio.create_task(asyncio.to_thread(_run_tts_job, job_id, text, lang_codes))
    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.get('/api/result/{job_id}_tts.zip')
async def download_tts_zip(job_id: str):
    fn = f"{job_id}_tts.zip"
    path = config.OUTPUT_DIR / fn
    headers = {
        "Content-Disposition": f'attachment; filename="tts_audio_{job_id}.zip"',
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    }
    if path.is_file():
        try:
            fh = path.open("rb")
        except Exception as e:
            raise HTTPException(500, f"Could not open ZIP: {e}")
        return StreamingResponse(fh, media_type="application/zip", headers=headers)

    blob = _get_job_result_blob(fn)
    if blob is None:
        raise HTTPException(404, "TTS ZIP not found.")

    def iter_gcs():
        try:
            with blob.open("rb") as reader:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.warning("TTS ZIP GCS stream failed: %s", e)
            raise HTTPException(500, f"Could not read ZIP from storage: {e}") from e

    return StreamingResponse(iter_gcs(), media_type="application/zip", headers=headers)


@app.post('/api/tts-save-to-library')
@_api_limit('20/10 minutes')
async def tts_save_to_library(
    request: Request,
    job_id: str = Form(...),
    folder: str = Form(''),
):
    """Save generated TTS MP3s for a job into the Library."""
    folder = (folder or '').strip()
    saved = []
    mp3s = sorted(config.OUTPUT_DIR.glob(f"{job_id}_tts_*.mp3"))
    if mp3s:
        for pth in mp3s:
            name = pth.name
            try:
                res = library.upload_file_from_path(pth, name, folder)
                saved.append(res)
            except Exception as e:
                raise HTTPException(500, f'Could not save {name} to Library: {e}')
        return {"saved": saved, "count": len(saved)}

    # Fallback for Cloud Run multi-instance: read MP3 job artifacts from GCS.
    bucket = _gcs_bucket_optional()
    if bucket is not None:
        prefix = f"{GCS_JOB_RESULTS_PREFIX}/{job_id}_tts_"
        try:
            blobs = sorted(
                [b for b in bucket.list_blobs(prefix=prefix) if b.name.lower().endswith(".mp3")],
                key=lambda b: b.name,
            )
        except Exception as e:
            raise HTTPException(500, f"Could not list TTS artifacts from storage: {e}")
        for blob in blobs:
            try:
                data = blob.download_as_bytes()
                name = Path(blob.name).name
                res = library.upload_file(data, name, folder)
                saved.append(res)
            except Exception as e:
                raise HTTPException(500, f"Could not save {blob.name} to Library: {e}")
        if saved:
            return {"saved": saved, "count": len(saved)}

    raise HTTPException(404, 'No TTS MP3 files found for this job.')


# ============ STEP 2: Translate VTT / TXT ============

@app.post("/api/translate-txt")
@_api_limit("5/10 minutes")
async def translate_txt_file(
    request: Request,
    file: UploadFile = File(...),
    language: str = Form("en"),
):
    """
    Translate a TXT file to a target language.
    Returns job_id; poll /api/status/{job_id}; download translated TXT from /api/result/{job_id}.txt
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".txt":
        raise HTTPException(400, "Only TXT files allowed.")

    job_id = str(uuid.uuid4())
    input_path = config.UPLOAD_DIR / f"{job_id}_input.txt"
    out_path = config.OUTPUT_DIR / f"{job_id}.txt"

    try:
        content = await file.read()
        input_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")

    lang = (language or "en").strip().lower()
    if lang not in config.TARGET_LANGUAGES:
        lang = "en"

    def on_progress(percent: int, message: str, eta_seconds: int | None = None):
        set_job_progress(job_id, {
            "progress": percent,
            "message": message,
            "done": False,
            "error": None,
            "eta_seconds": eta_seconds if percent < 100 else None,
        })

    set_job_progress(job_id, {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": None})

    asyncio.create_task(asyncio.to_thread(_run_txt_translation_only, job_id, input_path, out_path, [lang], on_progress))

    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.post("/api/translate")
@_api_limit("5/10 minutes")
async def translate_vtt(
    request: Request,
    file: UploadFile = File(...),
    languages: str = Form("en,nl,pt"),
):
    """
    Upload a VTT or TXT file → translate to selected languages.
    VTT: download from /api/result/{job_id}.vtt
    TXT: download from /api/result/{job_id}.txt (multiple languages = sections per language).
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".vtt", ".txt"):
        raise HTTPException(400, "Only VTT or TXT files allowed.")

    job_id = str(uuid.uuid4())
    if suffix == ".vtt":
        upload_path = config.UPLOAD_DIR / f"{job_id}.vtt"
        out_path = config.OUTPUT_DIR / f"{job_id}.vtt"
    else:
        upload_path = config.UPLOAD_DIR / f"{job_id}_translate_input.txt"
        out_path = config.OUTPUT_DIR / f"{job_id}.txt"

    try:
        with upload_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")

    def on_progress(percent: int, message: str, eta_seconds: int | None = None):
        set_job_progress(job_id, {
            "progress": percent,
            "message": message,
            "done": False,
            "error": None,
            "eta_seconds": eta_seconds if percent < 100 else None,
        })

    set_job_progress(job_id, {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": None})
    lang_codes = [x.strip().lower() for x in languages.split(",") if x.strip()]
    allowed = set(config.TARGET_LANGUAGES)
    lang_codes = [c for c in lang_codes if c in allowed] or ["en"]

    if suffix == ".vtt":
        asyncio.create_task(asyncio.to_thread(_run_translation_only, job_id, upload_path, out_path, lang_codes, on_progress))
    else:
        asyncio.create_task(asyncio.to_thread(_run_txt_translation_only, job_id, upload_path, out_path, lang_codes, on_progress))

    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


# ============ Burn subtitles into video ============

@app.post("/api/burn")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def burn_into_video(
    request: Request,
    video: UploadFile = File(...),
    vtt: UploadFile = File(...),
    burn_preset: str = Form("veryfast"),
):
    """
    Upload a video and a VTT file; burn subtitles into the video.
    Returns job_id; poll /api/status/{job_id}; download from /api/result/{job_id}_burned.mp4
    """
    v_suffix = Path(video.filename or "").suffix.lower()
    if v_suffix not in (".mp4", ".webm", ".mkv"):
        raise HTTPException(400, "Video must be MP4, WebM, or MKV.")
    if Path(vtt.filename or "").suffix.lower() != ".vtt":
        raise HTTPException(400, "Subtitle file must be VTT.")
    burn_preset = (burn_preset or "veryfast").strip().lower()
    if burn_preset not in ("veryfast", "ultrafast"):
        raise HTTPException(400, "burn_preset must be veryfast or ultrafast.")

    job_id = str(uuid.uuid4())
    video_path = config.UPLOAD_DIR / f"{job_id}_video{v_suffix}"
    vtt_path = config.UPLOAD_DIR / f"{job_id}_burn.vtt"
    out_path = config.OUTPUT_DIR / f"{job_id}_burned.mp4"

    try:
        with video_path.open("wb") as f:
            shutil.copyfileobj(video.file, f)
        with vtt_path.open("wb") as f:
            shutil.copyfileobj(vtt.file, f)
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")

    estimated_sec = _estimate_burn_seconds(video_path)

    def on_progress(percent: int, message: str, eta_seconds: int | None = None):
        eta = eta_seconds
        if eta is None and percent < 100 and estimated_sec:
            eta = max(0, int(estimated_sec * (1 - percent / 100)))
        set_job_progress(job_id, {
            "progress": percent,
            "message": message,
            "done": False,
            "error": None,
            "eta_seconds": eta if percent < 100 else None,
        })

    set_job_progress(job_id, {"progress": 0, "message": "Starting…", "done": False, "error": None, "eta_seconds": estimated_sec})
    asyncio.create_task(asyncio.to_thread(_run_burn, job_id, video_path, vtt_path, out_path, on_progress, burn_preset))

    return {"job_id": job_id, "status_url": f"/api/status/{job_id}"}


@app.get("/api/result/{job_id}_burned.mp4")
async def download_burned_video(job_id: str):
    """Download the video with burned-in subtitles."""
    fn = f"{job_id}_burned.mp4"
    path = config.OUTPUT_DIR / fn
    if path.is_file():
        return FileResponse(path, filename=f"video_with_subtitles_{job_id}.mp4", media_type="video/mp4")

    blob = _get_job_result_blob(fn)
    if blob is None:
        raise HTTPException(404, "Burned video not found.")

    headers = {"Content-Disposition": f'attachment; filename="video_with_subtitles_{job_id}.mp4"'}

    def iter_gcs():
        try:
            with blob.open("rb") as reader:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.warning("Burned video GCS stream failed: %s", e)
            raise HTTPException(500, f"Could not read video from storage: {e}") from e

    return StreamingResponse(iter_gcs(), media_type="video/mp4", headers=headers)





# ============ CINEMA API ============

@app.get("/api/cinema/videos")
async def get_cinema_videos():
    """
    Get all public videos available in Cinema (metadata from library index).
    """
    try:
        index = library._load_index()
        videos = []
        for file_id, finfo in index.get("files", {}).items():
            if finfo.get("type") != "video":
                continue
            if not finfo.get("cinema_public"):
                continue
            name = finfo.get("name", "")
            if not name.lower().endswith((".mp4", ".webm", ".mkv")):
                continue
            title = (finfo.get("cinema_title") or "").strip() or name
            desc = (finfo.get("cinema_description") or "").strip()
            subs = finfo.get("cinema_subtitles") or {}
            languages = []
            for lang, vtt_id in subs.items():
                languages.append({
                    "code": lang,
                    "name": config.TARGET_LANGUAGES.get(lang, lang.upper()),
                    "vtt_id": vtt_id,
                })
            cover_path = _cinema_cover_jpg_path(file_id)
            has_cover = (
                bool(finfo.get("cinema_has_cover"))
                or cover_path.exists()
                or library.cinema_cover_exists_on_gcs(file_id)
            )
            videos.append({
                "id": file_id,
                "name": name,
                "title": title,
                "description": desc,
                "size": finfo.get("size", 0),
                "cover_url": f"/api/cinema/cover/{file_id}" if has_cover else None,
                "languages": languages,
            })
        videos.sort(key=lambda x: (x.get("title") or x.get("name") or "").lower())
        return {"videos": videos}
    except Exception as e:
        logger.error(f"Failed to get cinema videos: {e}")
        raise HTTPException(500, "Failed to load cinema videos")


@app.get("/api/cinema/catalog")
async def get_cinema_catalog():
    """Netflix-style catalog: featured (most recently updated) + videos, ebooks (.txt), audios."""
    try:
        index = library._load_index()
        videos: list[dict] = []
        ebooks: list[dict] = []
        audios: list[dict] = []
        for fid, finfo in index.get("files", {}).items():
            row = _cinema_catalog_row(fid, finfo)
            if not row:
                continue
            if row["kind"] == "video":
                videos.append(row)
            elif row["kind"] == "ebook":
                ebooks.append(row)
            else:
                audios.append(row)

        def sort_key_recent(x: dict) -> tuple[float, str]:
            # Most recent first (left side in row), fallback by id for stable ordering.
            return (float(x.get("updated_at") or 0), str(x.get("id") or ""))

        videos.sort(key=sort_key_recent, reverse=True)
        ebooks.sort(key=sort_key_recent, reverse=True)
        audios.sort(key=sort_key_recent, reverse=True)

        all_rows = videos + ebooks + audios
        featured: dict | None = None
        if all_rows:
            featured = max(all_rows, key=lambda x: (float(x.get("updated_at") or 0), x["id"]))

        return {"featured": featured, "videos": videos, "ebooks": ebooks, "audios": audios}
    except Exception as e:
        logger.error("Failed to get cinema catalog: %s", e)
        raise HTTPException(500, "Failed to load cinema catalog")


@app.get("/api/cinema/video/{video_id}")
async def stream_cinema_video(video_id: str):
    """Stream a published Cinema video. Uses direct GCS signed URL when bucket is configured."""
    if not _cinema_item_is_public(video_id, ("video",)):
        raise HTTPException(404, "Video not found")
    if (config.GCS_BUCKET_NAME or "").strip():
        url = _signed_gcs_get_url(f"library/files/{video_id}", expires_seconds=1800)
        return RedirectResponse(url=url, status_code=307)
    result = library.get_file_path(video_id)
    if not result:
        raise HTTPException(404, "Video not found")
    file_path, filename = result
    suffix = Path(filename).suffix.lower()
    media_type = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(suffix, "application/octet-stream")
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/cinema/audio/{file_id}")
async def stream_cinema_audio(file_id: str):
    """Stream a published Cinema audio file (MP3/WAV)."""
    if not _cinema_item_is_public(file_id, ("audio",)):
        raise HTTPException(404, "Audio not found")
    if (config.GCS_BUCKET_NAME or "").strip():
        url = _signed_gcs_get_url(f"library/files/{file_id}", expires_seconds=1800)
        return RedirectResponse(url=url, status_code=307)
    result = library.get_file_path(file_id)
    if not result:
        raise HTTPException(404, "Audio not found")
    file_path, filename = result
    suffix = Path(filename).suffix.lower()
    media_type = {".mp3": "audio/mpeg", ".wav": "audio/wav"}.get(suffix, "application/octet-stream")
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/cinema/vtt/{vtt_id}")
async def stream_cinema_vtt(vtt_id: str):
    """Serve a VTT linked to a published Cinema video."""
    if not _cinema_vtt_allowed(vtt_id):
        raise HTTPException(404, "Subtitles not found")
    result = library.get_file(vtt_id)
    if not result:
        raise HTTPException(404, "Subtitles not found")
    data, filename = result
    if not filename.lower().endswith(".vtt"):
        raise HTTPException(400, "Not a VTT file")
    return PlainTextResponse(data.decode("utf-8", errors="replace"), media_type="text/vtt")


@app.post("/api/library/file/{file_id}/link-vtt")
async def link_vtt_to_video(file_id: str, vtt_id: str = Form(...), language: str = Form(...)):
    """
    Link a VTT file to a video file for Cinema playback.
    This creates a logical association between video and subtitles.
    """
    # Verify both files exist
    video_result = library.get_file(file_id)
    vtt_result = library.get_file(vtt_id)

    if not video_result:
        raise HTTPException(404, "Video file not found")
    if not vtt_result:
        raise HTTPException(404, "VTT file not found")

    video_data, video_name = video_result
    video_suffix = Path(video_name).suffix.lower()
    video_mime = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(video_suffix, "video/mp4")
    vtt_data, vtt_name = vtt_result

    # Verify video is actually a video file
    if not video_name.lower().endswith((".mp4", ".webm", ".mkv")):
        raise HTTPException(400, "File must be a video (MP4, WebM, or MKV)")

    # Verify VTT is actually a VTT file
    if not vtt_name.lower().endswith(".vtt"):
        raise HTTPException(400, "Linked file must be a VTT subtitle file")

    # For now, we don't store the linkage in the database
    # The frontend will discover linkages by filename patterns
    # In a real implementation, you'd store this in a database

    return {
        "success": True,
        "video": {"id": file_id, "name": video_name},
        "subtitles": {"id": vtt_id, "name": vtt_name, "language": language}
    }


@app.get("/api/cinema/watch/{video_id}")
async def watch_video_with_subtitles(request: Request, video_id: str, lang: str = "nl"):
    """
    Cinema HTML player. Pass ?token=<Firebase idToken> so <video>/<track> can load (?token= on media URLs).
    """
    video_result = library.get_file(video_id)
    if not video_result:
        raise HTTPException(404, "Video not found")

    video_data, video_name = video_result
    entry = library.get_file_entry(video_id) or {}
    if not entry.get("cinema_public") or entry.get("type") != "video":
        raise HTTPException(404, "Video not found")

    subs = entry.get("cinema_subtitles") or {}
    token = (request.query_params.get("token") or "").strip()
    token_q = "&token=" + quote(token, safe="") if token else ""

    vtt_id = None
    eff_lang = lang
    if lang == "none":
        vtt_id = None
    elif subs:
        vtt_id = subs.get(lang)
        if vtt_id is None:
            eff_lang = next(iter(subs.keys()))
            vtt_id = subs.get(eff_lang)

    if (config.GCS_BUCKET_NAME or "").strip():
        video_src = _signed_gcs_get_url(f"library/files/{video_id}", expires_seconds=1800)
    else:
        video_src = f"/api/cinema/video/{video_id}"
        if token:
            video_src += "?token=" + quote(token, safe="")

    video_mime = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(Path(video_name).suffix.lower(), "video/mp4")

    vtt_url = ""
    if vtt_id and token and lang != "none":
        vtt_url = f"/api/cinema/vtt/{vtt_id}?token=" + quote(token, safe="")

    title_display = html.escape((entry.get("cinema_title") or "").strip() or video_name)

    if subs:
        opt_none_sel = " selected" if (lang == "none" or not vtt_id) else ""
        parts = [f'<option value="none"{opt_none_sel}>None</option>']
        for code in subs.keys():
            sel = " selected" if (code == eff_lang and lang != "none" and vtt_id) else ""
            label = html.escape(config.TARGET_LANGUAGES.get(code, code.upper()))
            parts.append(f'<option value="{html.escape(code)}"{sel}>{label}</option>')
        options_html = "".join(parts)
    else:
        options_html = '<option value="none" selected>No subtitles linked</option>'

    track_html = ""
    if vtt_url and eff_lang and lang != "none":
        lbl = html.escape(config.TARGET_LANGUAGES.get(eff_lang, eff_lang.upper()))
        track_html = (
            f"<track src='{vtt_url}' kind='captions' srclang='{html.escape(eff_lang)}' "
            f"label='{lbl}' default>"
        )

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cinema - {title_display}</title>
        <style>
            body {{
                margin: 0;
                padding: 20px;
                background: #000;
                color: #fff;
                font-family: Arial, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .container {{
                max-width: 1200px;
                width: 100%;
            }}
            h1 {{
                text-align: center;
                margin-bottom: 20px;
                font-size: 1.5rem;
            }}
            video {{
                width: 100%;
                max-height: 70vh;
                background: #000;
            }}
            .controls {{
                margin-top: 20px;
                display: flex;
                gap: 20px;
                align-items: center;
                justify-content: center;
                flex-wrap: wrap;
            }}
            .lang-selector {{
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            select {{
                padding: 8px 12px;
                background: #333;
                color: #fff;
                border: 1px solid #666;
                border-radius: 4px;
            }}
            .back-btn {{
                padding: 10px 20px;
                background: #666;
                color: #fff;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                text-decoration: none;
            }}
            .back-btn:hover {{
                background: #777;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{title_display}</h1>
            <video id="videoPlayer" controls>
                <source src="{video_src}" type="{video_mime}">
                {track_html}
                Your browser does not support the video tag.
            </video>
            <div class="controls">
                <div class="lang-selector">
                    <label>Subtitles:</label>
                    <select id="langSelect" onchange="changeLanguage()">
                        {options_html}
                    </select>
                </div>
                <a href="/cinema" class="back-btn">← Back to Cinema</a>
            </div>
        </div>
        <script>
            function changeLanguage() {{
                const lang = document.getElementById('langSelect').value;
                window.location.href = `/api/cinema/watch/{video_id}?lang=${{lang}}{token_q}`;
            }}
        </script>
    </body>
    </html>
    """

    return HTMLResponse(content=html_content)


@app.get("/api/cinema/listen/{file_id}")
async def listen_cinema_audio(request: Request, file_id: str):
    """Simple HTML audio player for published Cinema audio."""
    entry = library.get_file_entry(file_id) or {}
    if not entry.get("cinema_public") or entry.get("type") != "audio":
        raise HTTPException(404, "Audio not found")
    name = entry.get("name", "audio")
    title_display = html.escape((entry.get("cinema_title") or "").strip() or name)
    token = (request.query_params.get("token") or "").strip()
    audio_src = f"/api/cinema/audio/{file_id}"
    if token:
        audio_src += "?token=" + quote(token, safe="")

    html_content = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cinéma — {title_display}</title>
        <style>
            body {{ margin: 0; padding: 24px; background: #000; color: #fff;
                font-family: system-ui, sans-serif; max-width: 640px; margin-inline: auto; }}
            h1 {{ font-size: 1.25rem; font-weight: 600; }}
            audio {{ width: 100%; margin-top: 24px; }}
            a.back-btn {{ display: inline-block; margin-top: 24px; color: #fff; }}
        </style>
    </head>
    <body>
        <h1>{title_display}</h1>
        <audio controls src="{audio_src}">
            Votre navigateur ne lit pas l’audio.
        </audio>
        <p><a class="back-btn" href="/cinema">← Retour au Cinéma</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/cinema/read/{file_id}")
async def read_cinema_ebook(request: Request, file_id: str):
    """HTML reader for published Cinema .txt ebooks."""
    entry = library.get_file_entry(file_id) or {}
    if not entry.get("cinema_public") or entry.get("type") != "text":
        raise HTTPException(404, "Texte introuvable")
    name = entry.get("name", "ebook.txt")
    if not str(name).lower().endswith(".txt"):
        raise HTTPException(404, "Texte introuvable")
    result = library.get_file(file_id)
    if not result:
        raise HTTPException(404, "Texte introuvable")
    raw, _fn = result
    text = raw.decode("utf-8", errors="replace")
    title_display = html.escape((entry.get("cinema_title") or "").strip() or name)
    lines_json = json.dumps(text.splitlines())
    html_content = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cinéma — {title_display}</title>
        <style>
            :root {{
                --reader-bg: #0b0b0b;
                --reader-card: #141414;
                --reader-border: #2a2a2a;
                --reader-text: #ececec;
                --reader-muted: #a8a8a8;
                --line-height: 1.5rem;
                --lines-per-page: 21;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                background: var(--reader-bg);
                color: var(--reader-text);
                font-family: Georgia, serif;
            }}
            .reader-wrap {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 16px 16px 20px;
            }}
            .reader-top {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 10px;
            }}
            .reader-top h1 {{
                margin: 0;
                font-family: system-ui, sans-serif;
                font-size: 1.2rem;
                font-weight: 700;
                color: #fff;
            }}
            .reader-back {{
                color: #fff;
                font-family: system-ui, sans-serif;
                text-decoration: none;
                font-size: 0.9rem;
            }}
            .reader-pages {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 12px;
            }}
            .reader-page {{
                min-height: calc(var(--line-height) * var(--lines-per-page) + 46px);
                background: var(--reader-card);
                border: 1px solid var(--reader-border);
                border-radius: 8px;
                padding: 12px 14px 10px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }}
            .reader-page.hidden {{
                visibility: hidden;
            }}
            .reader-lines {{
                min-height: calc(var(--line-height) * var(--lines-per-page));
            }}
            .reader-line {{
                min-height: var(--line-height);
                line-height: var(--line-height);
                font-size: 1rem;
                white-space: pre-wrap;
                word-break: break-word;
            }}
            .reader-footer {{
                margin-top: 8px;
                text-align: center;
                color: var(--reader-muted);
                font-family: system-ui, sans-serif;
                font-size: 0.8rem;
            }}
            .reader-controls {{
                margin-top: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
                font-family: system-ui, sans-serif;
            }}
            .reader-btn {{
                border: 1px solid #444;
                background: #1b1b1b;
                color: #fff;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 0.9rem;
                cursor: pointer;
            }}
            .reader-btn:disabled {{
                opacity: 0.35;
                cursor: default;
            }}
            .reader-page-nums {{
                margin-top: 10px;
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                justify-content: center;
                font-family: system-ui, sans-serif;
            }}
            .reader-page-num {{
                border: 1px solid #444;
                background: #101010;
                color: #d5d5d5;
                border-radius: 999px;
                min-width: 28px;
                text-align: center;
                padding: 4px 8px;
                font-size: 0.78rem;
                cursor: pointer;
            }}
            .reader-page-num.active {{
                background: #fff;
                color: #000;
            }}
            .reader-hint {{
                margin-top: 8px;
                text-align: center;
                color: var(--reader-muted);
                font-family: system-ui, sans-serif;
                font-size: 0.8rem;
            }}
            @media (max-width: 900px) {{
                .reader-pages {{
                    grid-template-columns: 1fr;
                }}
                .reader-page.hidden {{
                    display: none;
                }}
                .reader-controls {{
                    display: none;
                }}
                .reader-hint::after {{
                    content: "Glissez vers le haut/bas pour changer de page.";
                }}
            }}
        </style>
    </head>
    <body>
        <div class="reader-wrap" id="readerRoot">
            <div class="reader-top">
                <h1>{title_display}</h1>
                <a class="reader-back" href="/cinema">← Retour au Cinéma</a>
            </div>
            <div class="reader-pages">
                <section class="reader-page" id="readerPageA">
                    <div class="reader-lines" id="readerLinesA"></div>
                    <div class="reader-footer" id="readerFooterA">Page 1 / 1</div>
                </section>
                <section class="reader-page" id="readerPageB">
                    <div class="reader-lines" id="readerLinesB"></div>
                    <div class="reader-footer" id="readerFooterB"></div>
                </section>
            </div>
            <div class="reader-controls">
                <button type="button" class="reader-btn" id="readerPrevBtn">Précédent</button>
                <button type="button" class="reader-btn" id="readerNextBtn">Suivant</button>
            </div>
            <div class="reader-page-nums" id="readerPageNums"></div>
            <div class="reader-hint"></div>
        </div>
        <script>
            (function () {{
                const LINES_PER_PAGE = 21;
                const rawLines = {lines_json};
                const pages = [];
                for (let i = 0; i < rawLines.length; i += LINES_PER_PAGE) {{
                    pages.push(rawLines.slice(i, i + LINES_PER_PAGE));
                }}
                if (!pages.length) pages.push([]);

                const linesA = document.getElementById('readerLinesA');
                const linesB = document.getElementById('readerLinesB');
                const pageA = document.getElementById('readerPageA');
                const pageB = document.getElementById('readerPageB');
                const footerA = document.getElementById('readerFooterA');
                const footerB = document.getElementById('readerFooterB');
                const prevBtn = document.getElementById('readerPrevBtn');
                const nextBtn = document.getElementById('readerNextBtn');
                const numsWrap = document.getElementById('readerPageNums');
                const root = document.getElementById('readerRoot');

                let startPage = 0;
                let touchStartY = null;

                function isMobileOnePage() {{
                    return window.matchMedia('(max-width: 900px)').matches;
                }}

                function fillPage(target, lines) {{
                    target.innerHTML = '';
                    for (let i = 0; i < LINES_PER_PAGE; i += 1) {{
                        const div = document.createElement('div');
                        div.className = 'reader-line';
                        const txt = (lines && i < lines.length) ? String(lines[i]) : '';
                        div.textContent = txt || ' ';
                        target.appendChild(div);
                    }}
                }}

                function clampStart(n) {{
                    if (isMobileOnePage()) {{
                        return Math.max(0, Math.min(n, pages.length - 1));
                    }}
                    const maxStart = Math.max(0, pages.length - 2);
                    return Math.max(0, Math.min(n, maxStart));
                }}

                function goToStart(n) {{
                    startPage = clampStart(n);
                    render();
                }}

                function renderNums() {{
                    numsWrap.innerHTML = '';
                    for (let i = 0; i < pages.length; i += 1) {{
                        const b = document.createElement('button');
                        b.type = 'button';
                        b.className = 'reader-page-num';
                        b.textContent = String(i + 1);
                        const active = isMobileOnePage()
                            ? i === startPage
                            : (i === startPage || i === startPage + 1);
                        if (active) b.classList.add('active');
                        b.addEventListener('click', () => {{
                            if (isMobileOnePage()) goToStart(i);
                            else goToStart(i % 2 === 0 ? i : i - 1);
                        }});
                        numsWrap.appendChild(b);
                    }}
                }}

                function render() {{
                    const mobile = isMobileOnePage();
                    const secondIdx = mobile ? -1 : startPage + 1;
                    fillPage(linesA, pages[startPage] || []);
                    footerA.textContent = 'Page ' + (startPage + 1) + ' / ' + pages.length;
                    if (secondIdx >= 0 && secondIdx < pages.length) {{
                        pageB.classList.remove('hidden');
                        fillPage(linesB, pages[secondIdx] || []);
                        footerB.textContent = 'Page ' + (secondIdx + 1) + ' / ' + pages.length;
                    }} else {{
                        pageB.classList.add('hidden');
                        linesB.innerHTML = '';
                        footerB.textContent = '';
                    }}
                    prevBtn.disabled = startPage <= 0;
                    nextBtn.disabled = mobile
                        ? startPage >= pages.length - 1
                        : startPage >= Math.max(0, pages.length - 2);
                    renderNums();
                }}

                prevBtn.addEventListener('click', () => {{
                    goToStart(startPage - (isMobileOnePage() ? 1 : 2));
                }});
                nextBtn.addEventListener('click', () => {{
                    goToStart(startPage + (isMobileOnePage() ? 1 : 2));
                }});

                root.addEventListener('touchstart', (e) => {{
                    if (!isMobileOnePage()) return;
                    if (!e.touches || !e.touches.length) return;
                    touchStartY = e.touches[0].clientY;
                }}, {{ passive: true }});
                root.addEventListener('touchend', (e) => {{
                    if (!isMobileOnePage()) return;
                    if (touchStartY == null || !e.changedTouches || !e.changedTouches.length) return;
                    const delta = e.changedTouches[0].clientY - touchStartY;
                    touchStartY = null;
                    if (Math.abs(delta) < 40) return;
                    if (delta < 0) goToStart(startPage + 1); // swipe up => next
                    else goToStart(startPage - 1); // swipe down => previous
                }}, {{ passive: true }});

                window.addEventListener('resize', () => {{
                    startPage = clampStart(startPage);
                    render();
                }});

                render();
            }})();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/admin/status")
async def admin_status(request: Request):
    """Check if current user is admin."""
    claims = getattr(request.state, 'firebase_claims', {})
    user_email = (claims.get('email') or '').strip().lower()
    return {"is_admin": _is_admin_email(user_email)}


@app.post("/api/admin/invite")
@_api_limit("10/minute")
async def admin_invite_user(request: Request, email: str = Form(...)):
    """
    Option 2: admin creates accounts and shares a password-reset link.
    Returns a password reset link that the admin can send to the user.
    """
    _require_admin(request)
    target_email = (email or "").strip().lower()
    if not target_email or "@" not in target_email:
        raise HTTPException(400, "Invalid email.")

    # If there is an allowlist, only allow inviting allowlisted emails
    allowed_raw = (config.ALLOWED_EMAILS or "").strip()
    if allowed_raw:
        allowed = {e.strip().lower() for e in allowed_raw.split(",") if e.strip()}
        if target_email not in allowed:
            raise HTTPException(400, "Email is not in ALLOWED_EMAILS.")

    try:
        try:
            firebase_auth.get_user_by_email(target_email)
        except Exception:
            firebase_auth.create_user(email=target_email, email_verified=False, disabled=False)

        link = firebase_auth.generate_password_reset_link(target_email)
        return {"email": target_email, "password_reset_link": link}
    except Exception as e:
        raise HTTPException(500, f"Invite failed: {e}")


@app.get("/api/library/file/{file_id}/cinema")
async def get_library_file_cinema_meta(request: Request, file_id: str):
    """Get Cinema publish metadata for a video, TXT e-book, or audio file (library users)."""
    _require_cinema_publisher(request)
    entry = library.get_file_entry(file_id)
    if not entry or entry.get("type") not in ("video", "text", "audio"):
        raise HTTPException(404, "File not found")
    ftype = entry.get("type")
    default_cover = "frame" if ftype == "video" else "upload"
    return {
        "file_type": ftype,
        "cinema_public": bool(entry.get("cinema_public", False)),
        "cinema_title": entry.get("cinema_title") or "",
        "cinema_description": entry.get("cinema_description") or "",
        "cinema_cover_type": entry.get("cinema_cover_type") or default_cover,
        "cinema_cover_second": float(entry.get("cinema_cover_second") or 0),
        "cinema_subtitles": entry.get("cinema_subtitles") or {},
    }


@app.get("/api/library/vtt-list")
async def list_library_vtt_for_cinema(request: Request):
    """All VTT files for Cinema publish dropdowns."""
    _require_cinema_publisher(request)
    return {"items": library.list_all_vtt_files()}


@app.get("/api/cinema/cover/{video_id}")
async def get_cinema_cover(video_id: str):
    """Serve Cinema cover image (requires Authorization like other /api routes)."""
    if not _cinema_item_is_public(video_id):
        raise HTTPException(404, "Cover not found")
    path = _cinema_cover_jpg_path(video_id)
    if path.exists():
        return FileResponse(path, media_type="image/jpeg")
    data = library.download_cinema_cover_bytes(video_id)
    if data:
        return Response(content=data, media_type="image/jpeg")
    raise HTTPException(404, "Cover not found")


@app.post("/api/library/file/{file_id}/cinema")
async def set_library_file_cinema(
    request: Request,
    file_id: str,
    public: str = Form("true"),
    title: str = Form(""),
    description: str = Form(""),
    cover_type: str = Form("frame"),
    cover_second: str = Form("0"),
    subtitles_json: str = Form("{}"),
    cover_file: UploadFile | None = File(None),
):
    """
    Publish or update Cinema entry for video, TXT e-book, or audio. Full library users only.
    cover_type: frame | upload (frame only for video)
    subtitles_json: VTT ids per language (video only)
    """
    _require_cinema_publisher(request)
    entry = library.get_file_entry(file_id)
    if not entry or entry.get("type") not in ("video", "text", "audio"):
        raise HTTPException(404, "File not found")
    ftype = entry.get("type")
    path_result = library.get_file_path(file_id)
    if not path_result:
        raise HTTPException(404, "File missing on storage")
    media_path, media_name = path_result

    is_public = str(public).lower() in ("1", "true", "yes", "on")
    try:
        subs = json.loads(subtitles_json or "{}")
        if not isinstance(subs, dict):
            raise ValueError("subtitles must be object")
    except Exception as e:
        raise HTTPException(400, f"Invalid subtitles_json: {e}")

    cleaned: dict[str, str] = {}
    if ftype == "video":
        for lang, vtt_id in subs.items():
            if not lang or not vtt_id:
                continue
            vtt_entry = library.get_file_entry(str(vtt_id))
            if not vtt_entry or vtt_entry.get("type") != "vtt":
                raise HTTPException(400, f"Invalid VTT for language {lang}")
            cleaned[str(lang).lower().strip()] = str(vtt_id)

    try:
        sec = float(cover_second or 0)
    except ValueError:
        sec = 0.0

    title_f = (title or "").strip() or media_name

    if ftype == "video":
        ct = (cover_type or "frame").strip().lower()
        if ct not in ("frame", "upload"):
            ct = "frame"
        if is_public:
            if ct == "frame":
                _extract_cinema_cover_from_video(media_path, file_id, sec)
            else:
                if cover_file and cover_file.filename:
                    raw = await cover_file.read()
                    if len(raw) > 5 * 1024 * 1024:
                        raise HTTPException(400, "Cover image too large (max 5MB)")
                    out = _cinema_cover_jpg_path(file_id)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(raw)
                elif _cinema_cover_jpg_path(file_id).exists() or library.cinema_cover_exists_on_gcs(file_id):
                    pass
                else:
                    raise HTTPException(400, "Téléversez une image de couverture ou choisissez une image extraite de la vidéo.")
    else:
        ct = "upload"
        if is_public:
            if cover_file and cover_file.filename:
                raw = await cover_file.read()
                if len(raw) > 5 * 1024 * 1024:
                    raise HTTPException(400, "Cover image too large (max 5MB)")
                out = _cinema_cover_jpg_path(file_id)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
            elif _cinema_cover_jpg_path(file_id).exists() or library.cinema_cover_exists_on_gcs(file_id):
                pass
            else:
                raise HTTPException(400, "Une image de couverture est requise pour publier ce fichier dans le Cinéma.")

    cover_path = _cinema_cover_jpg_path(file_id)
    if is_public:
        has_cov = cover_path.exists()
        if has_cov:
            try:
                library.upload_cinema_cover_from_path(file_id, cover_path)
            except Exception as e:
                logger.warning("Cinema cover upload to GCS failed: %s", e)
        if not has_cov:
            has_cov = library.cinema_cover_exists_on_gcs(file_id)
    else:
        library.delete_cinema_cover_gcs(file_id)
        if cover_path.exists():
            try:
                cover_path.unlink()
            except OSError:
                pass
        has_cov = False

    if not library.set_cinema_metadata(
        file_id,
        public=is_public,
        title=title_f,
        description=description or "",
        cover_type=ct,
        cover_second=sec,
        subtitles=cleaned,
        has_cinema_cover=has_cov,
    ):
        raise HTTPException(404, "Could not save")

    return {"success": True, "cinema_public": is_public}


# ============ LIBRARY API ============

@app.get("/api/library")
async def list_library(request: Request, path: str = ""):
    """List contents of a library folder."""
    claims = getattr(request.state, 'firebase_claims', {})
    user_email = (claims.get('email') or '').strip().lower()
    return library.list_folder(path, user_email)


@app.post("/api/library/folder")
async def create_library_folder(request: Request, name: str = Form(...), parent: str = Form(""), allowed_emails: str = Form("")):
    """Create a new folder in the library."""
    claims = getattr(request.state, 'firebase_claims', {})
    user_email = (claims.get('email') or '').strip().lower()
    if not _is_admin_email(user_email):
        raise HTTPException(403, "Only admins can create folders with access restrictions")
    
    allowed_list = [e.strip() for e in allowed_emails.split(',') if e.strip()]
    # Always include the admin's email
    if user_email not in allowed_list:
        allowed_list.append(user_email)
    
    return library.create_folder(name, parent, allowed_list)


@app.delete("/api/library/folder/{folder_id}")
async def delete_library_folder(folder_id: str):
    """Delete a folder from the library."""
    if library.delete_folder(folder_id):
        return {"success": True}
    raise HTTPException(404, "Folder not found")


@app.post("/api/library/folder/{folder_id}/rename")
async def rename_library_folder(folder_id: str, name: str = Form(...)):
    """Rename a folder."""
    if library.rename_folder(folder_id, name):
        return {"success": True}
    raise HTTPException(404, "Folder not found")


@app.post("/api/library/folder/{folder_id}/permissions")
async def update_library_folder_permissions(request: Request, folder_id: str, allowed_emails: str = Form(...)):
    """Update folder access permissions."""
    claims = getattr(request.state, 'firebase_claims', {})
    user_email = (claims.get('email') or '').strip().lower()
    if not _is_admin_email(user_email):
        raise HTTPException(403, "Only admins can update folder permissions")
    
    allowed_list = [e.strip().lower() for e in allowed_emails.split(',') if e.strip()]
    # Always include the admin's email
    if user_email not in allowed_list:
        allowed_list.append(user_email)
    
    if library.update_folder_permissions(folder_id, allowed_list):
        return {"success": True}
    raise HTTPException(404, "Folder not found")


@app.post("/api/library/upload")
async def upload_to_library(
    file: UploadFile = File(...),
    folder: str = Form(""),
    filename: str = Form(""),
    video_preset: str = Form(""),
):
    """Upload a file to the library."""
    original_name = file.filename or "file"
    suffix = Path(original_name).suffix.lower()
    if suffix not in (".vtt", ".txt", ".mp3", ".mp4", ".wav"):
        raise HTTPException(400, "Only VTT, TXT, MP3, MPEG, MP4, or WAV files allowed.")

    desired_name = (filename or "").strip()
    if desired_name:
        desired_suffix = Path(desired_name).suffix.lower()
        # Keep the original extension when user enters a name without extension.
        if not desired_suffix:
            desired_name = f"{desired_name}{suffix}"
        elif desired_suffix != suffix:
            raise HTTPException(400, f"Filename extension must be {suffix}.")
    else:
        desired_name = original_name

    preset = (video_preset or "").strip().lower()
    if preset and preset not in ("veryfast", "ultrafast"):
        raise HTTPException(400, "video_preset must be veryfast or ultrafast.")

    if suffix == ".mp4" and preset:
        temp_in = config.UPLOAD_DIR / f"{uuid.uuid4()}_lib_in.mp4"
        temp_out = config.UPLOAD_DIR / f"{uuid.uuid4()}_lib_out.mp4"
        try:
            with temp_in.open("wb") as f:
                shutil.copyfileobj(file.file, f)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(temp_in.resolve()),
                "-c:v", "libx264",
                "-preset", preset,
                "-crf", "27",
                "-c:a", "aac",
                "-b:a", "96k",
                "-movflags", "+faststart",
                str(temp_out.resolve()),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                err = (res.stderr or "").strip()
                raise HTTPException(500, f"Video recompress failed: {err.splitlines()[-1] if err else 'ffmpeg error'}")
            return library.upload_file_from_path(temp_out, desired_name, folder)
        finally:
            try:
                temp_in.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                temp_out.unlink(missing_ok=True)
            except Exception:
                pass

    data = await file.read()
    return library.upload_file(data, desired_name, folder)


@app.post("/api/youtube-to-library")
@_api_limit(config.TRANSCRIBE_RATE_LIMIT)
async def youtube_to_library(
    request: Request,
    url: str = Form(...),
    filename: str = Form(""),
    folder: str = Form(""),
):
    """
    Download a YouTube URL and store it in Library as MP4 or MP3.
    """
    raw_url = (url or "").strip()
    if not raw_url:
        raise HTTPException(400, "YouTube URL is required.")

    desired_name = (filename or "").strip()
    if desired_name:
        ext = Path(desired_name).suffix.lower()
        if not ext:
            ext = ".mp4"
            desired_name = f"{desired_name}{ext}"
        if ext not in (".mp4", ".mp3"):
            raise HTTPException(400, "Filename extension must be .mp4 or .mp3")
    else:
        ext = ".mp4"
        desired_name = f"youtube_{uuid.uuid4().hex[:8]}{ext}"

    temp_out = config.UPLOAD_DIR / f"{uuid.uuid4()}_yt{ext}"
    try:
        burn.convert_youtube_url_to_mp4(raw_url, temp_out, timeout=7200)
        return library.upload_file_from_path(temp_out, desired_name, folder)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"YouTube conversion failed: {e}")
    finally:
        try:
            temp_out.unlink(missing_ok=True)
        except Exception:
            pass




@app.post("/api/library/import-gcs")
async def import_to_library_from_gcs(
    object_name: str = Form(...),
    folder: str = Form(""),
    filename: str = Form(""),
):
    """Import a file from GCS into the library."""
    temp_path: Path | None = None
    try:
        bucket = _get_gcs_bucket()
        blob = bucket.blob(object_name)
        if not blob.exists():
            raise HTTPException(404, "Uploaded file not found in storage.")

        source_name = Path(object_name).name
        source_suffix = Path(source_name).suffix.lower()
        if source_suffix not in (".vtt", ".txt", ".mp3", ".mp4", ".wav"):
            raise HTTPException(400, "Only VTT, TXT, MP3, MPEG, MP4, or WAV files allowed.")

        desired_name = (filename or "").strip()
        if desired_name:
            desired_suffix = Path(desired_name).suffix.lower()
            if not desired_suffix:
                desired_name = f"{desired_name}{source_suffix}"
            elif desired_suffix != source_suffix:
                raise HTTPException(400, f"Filename extension must be {source_suffix}.")
        else:
            desired_name = source_name

        # Download to a temp file first to avoid loading large videos into memory.
        temp_path = config.UPLOAD_DIR / f"{uuid.uuid4()}_library_import{source_suffix}"
        blob.download_to_filename(str(temp_path))
        result = library.upload_file_from_path(temp_path, desired_name, folder)

        # Best effort cleanup: uploaded object no longer needed once imported.
        try:
            blob.delete()
        except Exception:
            pass

        return result
    except HTTPException:
        raise
    except GoogleAPIError as e:
        raise HTTPException(500, f"GCS error: {e}")
    except Exception as e:
        raise HTTPException(500, f"Could not import file from storage: {e}")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


@app.get("/api/library/file/{file_id}")
async def download_library_file(request: Request, file_id: str):
    """Download a file from the library."""
    result = library.get_file_path(file_id)
    if not result:
        raise HTTPException(404, "File not found")
    
    file_path, filename = result
    suffix = Path(filename).suffix.lower()
    media_type = {
        ".vtt": "text/vtt",
        ".txt": "text/plain",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".wav": "audio/wav",
    }.get(suffix, "application/octet-stream")

    # Inline playback for <video>/<audio> when opened from the app (token or explicit inline=1).
    want_inline = (request.query_params.get("inline") == "1") or bool(
        (request.query_params.get("token") or "").strip()
    )
    if want_inline and suffix in (".mp4", ".webm", ".mp3", ".wav"):
        disp = "inline"
    else:
        disp = "attachment"

    # Stream from disk (important for large videos).
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


@app.get("/api/library/file/{file_id}/content")
async def get_library_file_content(file_id: str):
    """Get file content (for VTT/TXT editing)."""
    result = library.get_file(file_id)
    if not result:
        raise HTTPException(404, "File not found")
    
    data, filename = result
    suffix = Path(filename).suffix.lower()
    if suffix not in (".vtt", ".txt"):
        raise HTTPException(400, "Only VTT or TXT files can be read as text")
    return {"filename": filename, "content": data.decode("utf-8", errors="replace")}


@app.post("/api/library/file/{file_id}/rename")
async def rename_library_file(file_id: str, name: str = Form(...)):
    """Rename a file in the library."""
    if library.rename_file(file_id, name):
        return {"success": True}
    raise HTTPException(404, "File not found")


@app.post("/api/library/file/{file_id}/move")
async def move_library_file(file_id: str, folder: str = Form("")):
    """Move a file to another folder (folder = full path, empty = library root)."""
    ok, err = library.move_file_detailed(file_id, folder)
    if ok:
        return {"success": True}
    if err == "not_found":
        raise HTTPException(404, "File not found")
    if err == "bad_folder":
        raise HTTPException(400, "Target folder does not exist")
    if err == "duplicate":
        raise HTTPException(409, "A file with this name already exists in that folder")
    raise HTTPException(400, "Could not move file")


@app.post("/api/library/file/{file_id}/update")
async def update_library_file(
    file_id: str,
    content: str = Form(...),
    filename: str = Form(""),
):
    """Update file content (VTT/TXT) and optionally filename."""
    new_filename = (filename or "").strip() or None
    if library.update_file(file_id, content.encode("utf-8"), new_filename):
        return {"success": True}
    raise HTTPException(404, "File not found")


@app.delete("/api/library/file/{file_id}")
async def delete_library_file(file_id: str):
    """Delete a file from the library."""
    if library.delete_file(file_id):
        return {"success": True}
    raise HTTPException(404, "File not found")


@app.post("/api/library/file/{file_id}/duplicate")
async def duplicate_library_file(file_id: str):
    """Copy a library file in the same folder with a ``(copie)`` filename."""
    res = library.duplicate_file(file_id)
    if res is None:
        raise HTTPException(404, "File not found")
    return {"success": True, **res}


@app.post("/api/library/folder/{folder_id}/duplicate")
async def duplicate_library_folder(folder_id: str):
    """Deep-copy a folder and its contents as a sibling ``(copie)`` folder."""
    if library.duplicate_folder(folder_id):
        return {"success": True}
    raise HTTPException(404, "Folder not found")


# ============ Frontend (SPA) ============

def _frontend_index_path() -> Path:
    return FRONTEND_DIR / "index.html"


_NO_STORE_HTML = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/", include_in_schema=False)
async def serve_frontend_root():
    """Serve the single-page frontend."""
    index_path = _frontend_index_path()
    if not index_path.exists():
        raise HTTPException(500, "Frontend index.html not found on server.")
    return FileResponse(
        index_path,
        headers=_NO_STORE_HTML,
    )


async def _serve_frontend_shell():
    """Same SPA shell for all in-app routes (path selects initial view in app.js)."""
    return await serve_frontend_root()


@app.get("/accueil", include_in_schema=False)
async def serve_frontend_accueil():
    return await _serve_frontend_shell()


@app.get("/bibliotheque", include_in_schema=False)
async def serve_frontend_bibliotheque():
    return await _serve_frontend_shell()


@app.get("/workspace", include_in_schema=False)
async def serve_frontend_workspace():
    return await _serve_frontend_shell()


@app.get("/administration", include_in_schema=False)
async def serve_frontend_administration():
    return await _serve_frontend_shell()


@app.get("/cinema", include_in_schema=False)
async def serve_frontend_cinema():
    """Frontend route used by the Cinema back button."""
    return await _serve_frontend_shell()


@app.get("/design.css", include_in_schema=False)
async def serve_design_css():
    """Serve stylesheet; must not be swallowed by SPA catch-all (which returns index.html)."""
    path = FRONTEND_DIR / "design.css"
    if not path.exists():
        raise HTTPException(404, "design.css not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_NO_STORE_HTML,
    )


@app.get("/app.js", include_in_schema=False)
async def serve_app_js():
    """ES module bundle for the SPA; must not be caught by the HTML fallback."""
    path = FRONTEND_DIR / "app.js"
    if not path.exists():
        raise HTTPException(404, "app.js not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_NO_STORE_HTML,
    )


@app.get("/brand-logo.png", include_in_schema=False)
async def serve_brand_logo():
    """Serve custom brand logo selected by the user."""
    path = config.BASE_DIR / "Groene druppel met golven ripple.png"
    if not path.exists():
        raise HTTPException(404, "Brand logo not found")
    return FileResponse(
        path,
        media_type="image/png",
        headers=_NO_STORE_HTML,
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_catchall(full_path: str):
    """
    SPA fallback: serve the frontend for non-API routes.
    Must be registered after /api routes so it doesn't shadow them.
    Never return index.html for /design.css or /static/* — browsers need real CSS bytes.
    """
    p = (full_path or "").lstrip("/")
    if p.startswith("api/") or p == "api":
        raise HTTPException(404, "Not Found")
    # /static/* — serve real files (also covers cases where StaticFiles mount order differs)
    if p.startswith("static/"):
        if not STATIC_DIR.exists():
            raise HTTPException(404, "Not Found")
        rel = p[7:]
        if not rel or ".." in rel or rel.startswith(("/", "\\")):
            raise HTTPException(404, "Not Found")
        candidate = (STATIC_DIR / rel).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HTTPException(404, "Not Found")
        if candidate.is_file():
            mt, _ = mimetypes.guess_type(str(candidate))
            return FileResponse(candidate, media_type=mt or "application/octet-stream")
        raise HTTPException(404, "Not Found")
    if p == "design.css":
        css = FRONTEND_DIR / "design.css"
        if css.is_file():
            return FileResponse(
                css,
                media_type="text/css",
                headers=_NO_STORE_HTML,
            )
        raise HTTPException(404, "Not Found")
    if p == "app.js":
        js = FRONTEND_DIR / "app.js"
        if js.is_file():
            return FileResponse(
                js,
                media_type="application/javascript",
                headers=_NO_STORE_HTML,
            )
        raise HTTPException(404, "Not Found")
    if p == "brand-logo.png":
        logo = config.BASE_DIR / "Groene druppel met golven ripple.png"
        if logo.is_file():
            return FileResponse(
                logo,
                media_type="image/png",
                headers=_NO_STORE_HTML,
            )
        raise HTTPException(404, "Not Found")
    if p in (
        "accueil.html",
        "bibliotheque.html",
        "cinema.html",
        "workspace.html",
        "administration.html",
    ):
        stub_path = FRONTEND_DIR / p
        if stub_path.is_file():
            return FileResponse(stub_path, media_type="text/html", headers=_NO_STORE_HTML)
    return await serve_frontend_root()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
