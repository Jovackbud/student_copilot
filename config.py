# config.py
from dotenv import load_dotenv
import os
import sys
import pathlib
import logging
import hashlib
import re
import warnings

# --- Suppress unfixable 3rd-party noise ---
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="langchain_google_genai.*")

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AI_Tutor_App")

# Load .env
project_dir = pathlib.Path.cwd()
logger.info(f"[startup] cwd={project_dir}")
load_dotenv(dotenv_path=project_dir / ".env")

# --- Read Environment Variables ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")

# ΓöÇΓöÇΓöÇ MODEL CONFIGURATION ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
# Chat model names (overridable via .env)
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")
# Embedding model names
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
# LLM temperature (shared across providers)
try:
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
except (ValueError, TypeError):
    logger.warning("[startup] Invalid LLM_TEMPERATURE value. Defaulting to 0.7.")
    LLM_TEMPERATURE = 0.7

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "student-copilot")
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")

# ΓöÇΓöÇΓöÇ AUTH & SECURITY ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
# JWT secret for token signing.
JWT_SECRET_ENV = os.getenv("JWT_SECRET")
ALLOW_LEGACY_AUTH = os.getenv("ALLOW_LEGACY_AUTH", "false").lower() == "true"
ENFORCE_STRONG_JWT_SECRET = os.getenv("ENFORCE_STRONG_JWT_SECRET", "true").lower() == "true"
DEFAULT_JWT_SECRET_MARKERS = {
    "change_me_in_production",
    "default",
    "sovereign_default_key",
}

if not JWT_SECRET_ENV:
    if ENFORCE_STRONG_JWT_SECRET:
        logger.error("ERROR: JWT_SECRET not set and ENFORCE_STRONG_JWT_SECRET=true. Refusing to start.")
        sys.exit(1)
    else:
        logger.warning("WARNING: JWT_SECRET not set. Using temporary random key. Sessions will be invalidated upon restart.")
        import secrets
        JWT_SECRET = secrets.token_urlsafe(32)
else:
    JWT_SECRET = JWT_SECRET_ENV

if ENFORCE_STRONG_JWT_SECRET:
    secret_lower = (JWT_SECRET_ENV or "").lower()
    if any(marker in secret_lower for marker in DEFAULT_JWT_SECRET_MARKERS):
        logger.error("ERROR: JWT_SECRET appears to be a placeholder/default value and ENFORCE_STRONG_JWT_SECRET=true. Refusing to start.")
        sys.exit(1)

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

CORS_ALLOW_ORIGINS_RAW = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ALLOW_ORIGINS = [o.strip() for o in CORS_ALLOW_ORIGINS_RAW.split(",") if o.strip()]

# Admin user IDs (comma-separated in .env for multi-admin support)
ADMIN_IDS = set(filter(None, os.getenv("ADMIN_IDS", "sovereign_admin_1").split(",")))

# ΓöÇΓöÇΓöÇ OPERATIONAL LIMITS ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
# Redis TTL for conversation data (seconds). Default: 30 days.
CONVERSATION_TTL_SECONDS = int(os.getenv("CONVERSATION_TTL_SECONDS", str(30 * 24 * 3600)))
# Learning method persists longer ΓÇö 365 days default.
LEARNING_METHOD_TTL_SECONDS = int(os.getenv("LEARNING_METHOD_TTL_SECONDS", str(365 * 24 * 3600)))
# Enrollment persists until manually removed (no TTL).
ENROLLMENT_TTL_SECONDS = int(os.getenv("ENROLLMENT_TTL_SECONDS", "0"))  # 0 = no expiry
# Teacher content is ground truth ΓÇö persists much longer (default: 365 days). 0 = no expiry.
TEACHER_CONTENT_TTL_SECONDS = int(os.getenv("TEACHER_CONTENT_TTL_SECONDS", str(365 * 24 * 3600)))

# Rate limits (requests per minute)
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "20/minute")
RATE_LIMIT_GENERATE = os.getenv("RATE_LIMIT_GENERATE", "10/minute")
RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "5/minute")
RATE_LIMIT_AUTH = os.getenv("RATE_LIMIT_AUTH", "10/minute")

# Agent execution logging
AGENT_VERBOSE = os.getenv("AGENT_VERBOSE", "false").lower() == "true"

# ΓöÇΓöÇΓöÇ INPUT SANITIZATION ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
# Strict pattern for IDs/keys: alphanumeric, underscores, hyphens, spaces, dots. Max 100 chars.
SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-. ]{1,100}$")
# Broad pattern for display names: blocks injection chars but allows Unicode.
_BLOCKED_NAME_CHARS = re.compile(r'[<>&;"\'\\]|\x00')

def validate_safe_string(value: str, field_name: str = "field") -> str:
    """Validates that a string is safe for use as Redis keys / Pinecone metadata."""
    if not value or not value.strip():
        raise ValueError(f"{field_name} cannot be empty.")
    cleaned = value.strip()
    if not SAFE_ID_PATTERN.match(cleaned):
        raise ValueError(
            f"{field_name} contains invalid characters. "
            f"Only letters, numbers, underscores, hyphens, spaces, and dots are allowed (max 100 chars)."
        )
    return cleaned

def validate_safe_name(value: str, field_name: str = "field") -> str:
    """Validates display names ΓÇö allows Unicode but blocks injection characters."""
    if not value or not value.strip():
        raise ValueError(f"{field_name} cannot be empty.")
    cleaned = value.strip()
    if len(cleaned) > 200:
        raise ValueError(f"{field_name} exceeds maximum length of 200 characters.")
    if _BLOCKED_NAME_CHARS.search(cleaned):
        raise ValueError(
            f"{field_name} contains disallowed characters "
            f"(angled brackets, quotes, semicolons, backslashes)."
        )
    return cleaned


def redact_for_logs(value: str) -> str:
    if value is None:
        return "-"
    s = str(value)
    digest = hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:10]


# --- Initial Validation ---
if LLM_PROVIDER == "openai":
    if not OPENAI_API_KEY:
        logger.error("ERROR: OPENAI_API_KEY is required for OpenAI models.")
        sys.exit(1)
elif LLM_PROVIDER == "gemini":
    if not GEMINI_API_KEY:
        logger.error("ERROR: GEMINI_API_KEY is required for Gemini.")
        sys.exit(1)
else:
    logger.error(f"ERROR: Unsupported LLM_PROVIDER: {LLM_PROVIDER}")
    sys.exit(1)

if not TAVILY_KEY:
    logger.warning("WARNING: TAVILY_API_KEY not set. Tavily web search will fail if used.")

if not PINECONE_API_KEY:
    logger.warning("WARNING: PINECONE_API_KEY not set. File uploads will not be vectorized.")

if not REDIS_URL:
    logger.error("ERROR: REDIS_URL is required for session/memory management.")
    sys.exit(1)

if not JWT_SECRET_ENV and not ENFORCE_STRONG_JWT_SECRET:
    logger.warning("WARNING: Using dynamically generated random JWT_SECRET. Set JWT_SECRET in .env for production.")

logger.info(f"[startup] Config loaded. LLM={LLM_PROVIDER}, Admins={ADMIN_IDS}, ConvTTL={CONVERSATION_TTL_SECONDS}s")
