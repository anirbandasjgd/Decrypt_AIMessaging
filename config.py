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

# Ensure directories exist
for d in [DATA_DIR, MOMS_DIR, CREDENTIALS_DIR, AUDIO_OUTPUT_DIR]:
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
GOOGLE_CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
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

# ─── Email (SMTP) ────────────────────────────────────────────────────────────
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # App-specific password for Gmail

# ─── Data Files ──────────────────────────────────────────────────────────────
ADDRESS_BOOK_FILE = DATA_DIR / "address_book.json"
MEETINGS_FILE = DATA_DIR / "meetings.json"

# ─── App Settings ────────────────────────────────────────────────────────────
APP_TITLE = "Smart Office Assistant"
APP_ICON = "🏢"
MAX_AUDIO_FILE_SIZE_MB = 25  # OpenAI Whisper limit
