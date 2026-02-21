"""
Smart Office Assistant - Configuration Module
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from parent directory .env
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MOMS_DIR = DATA_DIR / "moms"
CREDENTIALS_DIR = BASE_DIR / "credentials"
AUDIO_OUTPUT_DIR = BASE_DIR / "audio_output"
RECORDINGS_DIR = BASE_DIR / "recordings"

# Ensure directories exist
for d in [DATA_DIR, MOMS_DIR, CREDENTIALS_DIR, AUDIO_OUTPUT_DIR, RECORDINGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── OpenAI ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID", "")
NLU_MODEL = os.getenv("NLU_MODEL", "gpt-4o-mini")          # For NLU parsing
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")        # For general chat
MOM_MODEL = os.getenv("MOM_MODEL", "gpt-4o-mini")          # For MoM generation
WHISPER_MODEL = "whisper-1"                                  # For transcription
TTS_MODEL = "tts-1"                                          # For text-to-speech
TTS_VOICE = "alloy"                                          # TTS voice choice

# ─── Google Calendar ─────────────────────────────────────────────────────────
# Prefer credentials.json; fall back to client_secret_*.json (Google Cloud download name)
def _resolve_credentials_file() -> Path:
    candidate = CREDENTIALS_DIR / "credentials.json"
    if candidate.exists():
        return candidate
    for path in CREDENTIALS_DIR.glob("client_secret_*.json"):
        return path
    return candidate  # return default path for clearer error messages

GOOGLE_CREDENTIALS_FILE = _resolve_credentials_file()
GOOGLE_TOKEN_FILE = CREDENTIALS_DIR / "token.json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# ─── Meeting Defaults ────────────────────────────────────────────────────────
DEFAULT_MEETING_DURATION_MINUTES = 45
WORKING_HOURS_START = 9   # 9 AM
WORKING_HOURS_END = 18    # 6 PM
SLOT_INCREMENT_MINUTES = 30  # Check availability every 30 min

# Calendar timezone for scheduling (user's local time). Set in .env as CALENDAR_TIMEZONE.
# Examples: America/Los_Angeles, America/New_York, Europe/London, Asia/Kolkata
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "America/New_York")

# ─── Email (SMTP) ────────────────────────────────────────────────────────────
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "nitinsood1976@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # Gmail: use App Password from .env

# ─── Data Files ──────────────────────────────────────────────────────────────
LOGIN_FILE = DATA_DIR / "login.json"
ADDRESS_BOOK_FILE = DATA_DIR / "address_book.json"
MEETINGS_FILE = DATA_DIR / "meetings.json"


def sanitize_user_for_path(email: str) -> str:
    """Convert user email to a safe filename segment (e.g. for per-user files)."""
    if not email:
        return "default"
    return email.strip().replace("@", "_at_").replace(".", "_")


def get_address_book_path_for_user(email: str, is_admin: bool = False) -> Path:
    """Get the address book JSON path for a given user. Admin uses the full org address book."""
    if is_admin:
        return ADDRESS_BOOK_FILE  # Full organization address book
    return DATA_DIR / f"address_book_{sanitize_user_for_path(email)}.json"


def get_chat_history_path_for_user(email: str) -> Path:
    """Get the chat history JSON path for a given user."""
    return DATA_DIR / f"chat_{sanitize_user_for_path(email)}.json"

# ─── App Settings ────────────────────────────────────────────────────────────
APP_TITLE = "Smart Office Assistant"
APP_ICON = "🏢"
MAX_AUDIO_FILE_SIZE_MB = 25  # OpenAI Whisper limit
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501")


def get_meeting_app_link(meeting_id: str) -> str:
    """Build a direct URL to open a specific meeting in the app."""
    return f"{APP_BASE_URL}/?page=Meetings&meeting_id={meeting_id}"

# ─── Debug ────────────────────────────────────────────────────────────────────
# Set DEBUG_LOGGING=true in .env to print debug messages to stdout (use debug_log() anywhere in the app)
DEBUG_LOGGING = os.getenv("DEBUG_LOGGING", "yes").lower() in ("true", "1", "yes")


def debug_log(msg: str) -> None:
    """Print message to stdout only when DEBUG_LOGGING is enabled. Use anywhere in the app for debug output."""
    if DEBUG_LOGGING:
        print(msg, flush=True)
