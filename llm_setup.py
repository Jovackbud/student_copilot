# llm_setup.py
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from config import (
    OPENAI_API_KEY, OPENAI_MODEL_NAME, REDIS_URL, logger, LLM_PROVIDER, 
    GEMINI_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_CLOUD, PINECONE_REGION,
    GEMINI_MODEL_NAME, GEMINI_EMBEDDING_MODEL, OPENAI_EMBEDDING_MODEL, LLM_TEMPERATURE
)
import sys
import time

# For Redis client
try:
    import redis
except ImportError:
    logger.error("ERROR: 'redis' package not found. Please install it with `pip install redis`.") # Changed from print
    sys.exit(1)


# --- LLM and Embeddings Initialization ---
llm = None
embeddings = None
try:
    if LLM_PROVIDER == "gemini":
        llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL_NAME, # Minimalist & high speed
            google_api_key=GEMINI_API_KEY,
            temperature=LLM_TEMPERATURE,
        )
        # Import moved here to avoid crash if not using gemini
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        embeddings = GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBEDDING_MODEL, 
            google_api_key=GEMINI_API_KEY
        )
        logger.info(f"[startup] Google Gemini LLM ({GEMINI_MODEL_NAME}) and Embeddings initialized successfully.")
    elif LLM_PROVIDER == "openai":
        llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL_NAME,
            temperature=LLM_TEMPERATURE,
            streaming=True
        )
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(
            api_key=OPENAI_API_KEY,
            model=OPENAI_EMBEDDING_MODEL # Standard high-performance OpenAI embedding model
        )
        logger.info(f"[startup] Standard OpenAI LLM ({OPENAI_MODEL_NAME}) and Embeddings ({OPENAI_EMBEDDING_MODEL}) initialized successfully.")
    else:
        logger.error(f"[startup] Unknown LLM_PROVIDER specified: {LLM_PROVIDER}")
        sys.exit(1)
except Exception as e:
    logger.error(f"[startup] Failed to initialize LLM/Embeddings ({LLM_PROVIDER}): {e}") # Changed from print
    sys.exit(1)

def _ensure_pinecone_index() -> None:
    if not PINECONE_API_KEY:
        return

    if not embeddings:
        logger.warning("[startup] Pinecone API key is set but embeddings are not initialized; skipping index provisioning.")
        return

    try:
        from pinecone import Pinecone, ServerlessSpec
    except Exception as e:
        logger.error(f"[startup] Pinecone client import failed: {e}")
        return

    try:
        test_embed = embeddings.embed_documents(["test"])
        dim = len(test_embed[0])
    except Exception as e:
        logger.warning(f"[startup] Dynamic dim detection failed. Fallback: {e}")
        dim = 768 if LLM_PROVIDER == "gemini" else 1536

    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)

        existing = pc.list_indexes().names()
        if PINECONE_INDEX_NAME not in existing:
            logger.info(f"[startup] Creating Pinecone index {PINECONE_INDEX_NAME!r} (dim={dim}, cloud={PINECONE_CLOUD}, region={PINECONE_REGION})")
            pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=dim,
                metric="cosine",
                spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
            )

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                desc = pc.describe_index(PINECONE_INDEX_NAME)
                status = getattr(desc, "status", None) or {}
                ready = status.get("ready") if isinstance(status, dict) else None
                if ready is True:
                    logger.info(f"[startup] Pinecone index {PINECONE_INDEX_NAME!r} is ready")
                    return
            except Exception:
                pass
            time.sleep(2)

        logger.warning(f"[startup] Pinecone index {PINECONE_INDEX_NAME!r} provisioning not confirmed ready within timeout; continuing.")
    except Exception as e:
        logger.error(f"[startup] Pinecone index provisioning failed: {e}")

# --- Redis Client Initialization ---
redis_client = None # Make redis_client globally accessible within this module
try:
    if REDIS_URL:
        # Added socket_timeout and socket_connect_timeout to prevent complete service hang on Redis outage
        redis_client = redis.Redis.from_url(REDIS_URL, socket_timeout=5, socket_connect_timeout=5)
        redis_client.ping() # Test connection
        logger.info(f"[startup] Redis client initialized successfully for URL: {REDIS_URL}") # Changed from print
    else:
        logger.error("ERROR: REDIS_URL is not set. Cannot initialize Redis client.") # Changed from print
        sys.exit(1)
except Exception as e:
    logger.error(f"[startup] Failed to initialize Redis client for URL {REDIS_URL}: {e}") # Changed from print
    sys.exit(1)

_ensure_pinecone_index()
