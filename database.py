# database.py
from typing import Optional
from supabase import create_client, Client
from config import logger, SUPABASE_URL, SUPABASE_KEY

supabase: Optional[Client] = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("[database] Supabase client initialized successfully.")
    except Exception as e:
        logger.error(f"[database] Failed to initialize Supabase client: {e}")
else:
    logger.warning("[database] Supabase credentials missing. Client not initialized.")

def get_supabase() -> Optional[Client]:
    """Returns the initialized Supabase client."""
    if not supabase:
        logger.error("[database] Attempted to use Supabase client before initialization or without credentials.")
    return supabase
