"""App configuration and API keys."""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Paths first so .env always loads from the project root (not dependent on cwd).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load base .env, then optional environment-specific override.
load_dotenv(BASE_DIR / ".env")
_env_hint = (os.getenv("ENV", "local") or "local").lower()
_env_config = BASE_DIR / "config" / f"{_env_hint}.env"
if _env_config.exists():
    load_dotenv(_env_config, override=True)

ENV = (os.getenv("ENV", "local") or "local").lower()

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# APIs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
# Optional dedicated TTS key. Falls back to ELEVENLABS_API_KEY when not set.
ELEVENLABS_TTS_API_KEY = (os.getenv("ELEVENLABS_TTS_API_KEY", "") or "").strip() or ELEVENLABS_API_KEY
VOICE_ISOLATION_API_KEY = os.getenv("VOICE_ISOLATION_API_KEY", "")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# Hugging Face Inference (live ASR). Accepts HF_TOKEN or HUGGINGFACE_API_TOKEN.
HUGGINGFACE_API_TOKEN = (
    (os.getenv("HUGGINGFACE_API_TOKEN", "") or os.getenv("HF_TOKEN", "") or "").strip()
)
# Default: Whisper large-v3-turbo on HF Inference Providers
HUGGINGFACE_ASR_MODEL = (
    (os.getenv("HUGGINGFACE_ASR_MODEL", "") or "").strip() or "openai/whisper-large-v3-turbo"
)

# ---- Local offline inference (no API costs; works without internet once models are cached) ----
# Prefer local faster-whisper + Ollama/NLLB when available; cloud APIs remain fallback.
_local_flag = (os.getenv("LOCAL_INFERENCE", "") or "").strip().lower()
if _local_flag in ("0", "false", "off", "no"):
    LOCAL_INFERENCE = False
elif _local_flag in ("1", "true", "on", "yes"):
    LOCAL_INFERENCE = True
else:
    # Default on for local/dev so church laptop can run offline-first
    LOCAL_INFERENCE = ENV == "local"

LOCAL_WHISPER_MODEL = (os.getenv("LOCAL_WHISPER_MODEL", "") or "").strip() or "base"
LOCAL_WHISPER_DEVICE = (os.getenv("LOCAL_WHISPER_DEVICE", "") or "").strip() or "auto"
LOCAL_WHISPER_COMPUTE = (os.getenv("LOCAL_WHISPER_COMPUTE", "") or "").strip() or "default"
OLLAMA_BASE_URL = (os.getenv("OLLAMA_BASE_URL", "") or "").strip() or "http://127.0.0.1:11434"
OLLAMA_TRANSLATE_MODEL = (os.getenv("OLLAMA_TRANSLATE_MODEL", "") or "").strip() or "qwen2.5:7b"
# Bearer token for remote Ollama behind a reverse proxy. Leave empty for local unauthenticated Ollama.
OLLAMA_API_TOKEN = (
    (os.getenv("OLLAMA_API_TOKEN", "") or os.getenv("OLLAMA_BEARER_TOKEN", "") or "").strip()
)
LOCAL_NLLB_MODEL = (
    (os.getenv("LOCAL_NLLB_MODEL", "") or "").strip() or "facebook/nllb-200-distilled-600M"
)
LOCAL_TRANSLATE_PREFER = (os.getenv("LOCAL_TRANSLATE_PREFER", "") or "").strip().lower() or "ollama"

# Chat Completions model for Lingala + DeepL fallbacks (lighter)
OPENAI_TRANSLATION_MODEL = (os.getenv("OPENAI_TRANSLATION_MODEL", "") or "").strip() or "gpt-4o-mini"
# Malagasy / Kikongo / Tshiluba: premium Chat Completions model (default gpt-5.1-chat-latest; costly). Legacy: OPENAI_TRANSLATION_MODEL_KIKONGO
_mg_kg_ts = (
    (os.getenv("OPENAI_TRANSLATION_MODEL_MG_KG_TS", "") or os.getenv("OPENAI_TRANSLATION_MODEL_KIKONGO", "") or "").strip()
    or "gpt-5.1-chat-latest"
)
OPENAI_TRANSLATION_MODEL_MG_KG_TS = _mg_kg_ts
OPENAI_TRANSLATION_MODEL_KIKONGO = _mg_kg_ts  # alias for older configs / health JSON

# Validate required API keys
def validate_config():
    """Validate configuration. In local ENV: warn only so the UI can still boot."""
    errors = []

    # Local-first: cloud keys optional when LOCAL_INFERENCE is on
    has_cloud_stt = bool(ELEVENLABS_API_KEY or OPENAI_API_KEY or HUGGINGFACE_API_TOKEN)
    has_cloud_mt = bool(DEEPL_API_KEY or OPENAI_API_KEY)
    if not LOCAL_INFERENCE and not has_cloud_stt:
        errors.append(
            "Transcription requires ELEVENLABS_API_KEY, OPENAI_API_KEY, HUGGINGFACE_API_TOKEN, "
            "or LOCAL_INFERENCE=true with faster-whisper"
        )
    if not LOCAL_INFERENCE and not has_cloud_mt:
        errors.append(
            "Translation requires DEEPL_API_KEY or OPENAI_API_KEY "
            "(or LOCAL_INFERENCE=true with Ollama/NLLB)"
        )

    if not errors:
        return

    print("Configuration errors:")
    for error in errors:
        print(f"  - {error}")
    print("\nPlease check your .env file and ensure all required API keys are set.")
    if ENV == "local":
        print("Continuing in local mode without API keys (transcription/translation will fail until keys are set).\n")
        return
    sys.exit(1)

# Validate on import
validate_config()

# Google Cloud Storage (for large uploads in Cloud Run)
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")

# Firebase Authentication (email magic link).
# Must match the Firebase project used by the web client. If Cloud Run's GCP project
# differs from the Firebase project ID, token verification fails unless this is set.
_DEFAULT_FIREBASE_PROJECT_ID = "ondertitels-1"
FIREBASE_PROJECT_ID = (os.getenv("FIREBASE_PROJECT_ID", "") or "").strip() or _DEFAULT_FIREBASE_PROJECT_ID

# Stripe subscriptions for church workspaces.
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY", "") or "").strip()
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET", "") or "").strip()
APP_BASE_URL = (os.getenv("APP_BASE_URL", "") or "").strip()

# Allowlist (comma-separated emails). If empty: allow any Firebase user.
ALLOWED_EMAILS = os.getenv("ALLOWED_EMAILS", "")

# Admin allowlist (comma-separated emails). If empty: fall back to ALLOWED_EMAILS.
# Admins can "invite" users by generating a password reset link.
ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "")

# Debug settings
DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes", "on")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Rate limiting (slowapi). Set DISABLE_API_RATE_LIMITS=true to turn off all API rate limits.
# When disabled, more users can use the app in parallel without 429s; you still pay for Cloud Run / APIs.
DISABLE_API_RATE_LIMITS = os.getenv("DISABLE_API_RATE_LIMITS", "true").lower() in (
    "true",
    "1",
    "yes",
    "on",
)

# Only used when DISABLE_API_RATE_LIMITS is false (string format: e.g. "100/minute", "2/10minutes").
UPLOAD_RATE_LIMIT = os.getenv("UPLOAD_RATE_LIMIT", "10000/minute")
TRANSCRIBE_RATE_LIMIT = os.getenv("TRANSCRIBE_RATE_LIMIT", "10000/minute")

# Max size for POST /api/upload body check (MB). 0 or unset = no app-side limit (use GCS/resumable for huge files).
# Cloud Run may still enforce request size unless clients use direct-to-GCS uploads.
def _max_upload_bytes() -> int | None:
    raw = (os.getenv("MAX_UPLOAD_MB") or "").strip().lower()
    if raw in ("", "0", "none", "unlimited", "-1"):
        return None
    try:
        mb = float(raw)
    except ValueError:
        return None
    if mb <= 0:
        return None
    return int(mb * 1024 * 1024)


MAX_UPLOAD_BYTES: int | None = _max_upload_bytes()

# yt-dlp / YouTube conversion settings (Cloud Run often needs authenticated cookies)
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
YTDLP_EXTRACTOR_ARGS = (
    os.getenv("YTDLP_EXTRACTOR_ARGS", "").strip()
    or "youtube:player_client=android,web"
)

# Language config: which API to use per target language
# DeepL: NL, EN, PT, ES, ZH, FR, SW (with OpenAI fallback)
# OpenAI: Malgasy, Kikongo, Tshiluba, Lingala (with DeepL fallback)
DEEPL_LANGUAGES = {"nl", "en", "pt", "es", "zh", "fr", "sw"}
OPENAI_LANGUAGES = {"mg", "kg", "ts", "ln"}

# Target languages for the app (code -> English display name, no region suffix)
TARGET_LANGUAGES = {
    "nl": "Dutch",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "mg": "Malagasy",
    "kg": "Kikongo",
    "ts": "Tshiluba",
    "ln": "Lingala",
    "pt": "Portuguese",
    "zh": "Chinese",
    "sw": "Swahili",
}

# ElevenLabs TTS defaults (server-side; end users should not provide API/model/voice IDs)
TTS_MODEL_ID = (os.getenv("TTS_MODEL_ID", "") or "").strip() or "eleven_multilingual_v2"
TTS_DEFAULT_VOICE_ID = (os.getenv("TTS_DEFAULT_VOICE_ID", "") or "").strip()
_raw_tts_voice_ids = (os.getenv("TTS_VOICE_IDS_JSON", "") or "").strip()
try:
    _parsed_tts_voice_ids = json.loads(_raw_tts_voice_ids) if _raw_tts_voice_ids else {}
except Exception:
    _parsed_tts_voice_ids = {}
TTS_VOICE_IDS = _parsed_tts_voice_ids if isinstance(_parsed_tts_voice_ids, dict) else {}


def _tts_max_chunk_chars() -> int:
    """Max characters per TTS API call (ElevenLabs bills per request; large chunks need many credits)."""
    raw = (os.getenv("TTS_MAX_CHUNK_CHARS", "") or "").strip()
    default = 1200
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    # API hard limit is 10000; keep margin. Minimum avoids huge request counts.
    return max(400, min(v, 9999))


TTS_MAX_CHUNK_CHARS = _tts_max_chunk_chars()

