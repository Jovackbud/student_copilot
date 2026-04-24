# session_manager.py
from typing import Dict, Any, Optional, List
from langchain_redis import RedisChatMessageHistory
from llm_setup import redis_client  # Import the pre-initialized redis_client
from config import logger, CONVERSATION_TTL_SECONDS, LEARNING_METHOD_TTL_SECONDS
import json
import uuid

# Global SESSIONS dictionary to cache history objects, profiles, and summaries
# Structure: {
#   user_id: {
#     conversation_id: {
#       "chat_history_redis": RedisChatMessageHistory,
#       "profile": dict,
#       "summaries": list,
#       "title": str
#     },
#   },
# }
SESSIONS: Dict[str, Dict[str, Dict[str, Any]]] = {}
MAX_CACHED_SESSIONS = 500  # Hard cap on total cached conversations (across all users)

def _enforce_session_bounds():
    """Evicts oldest cached sessions to prevent unbounded memory growth.
    Safe because Redis is the source of truth ΓÇö evicted sessions re-hydrate on next access."""
    total = sum(len(convs) for convs in SESSIONS.values())
    if total <= MAX_CACHED_SESSIONS:
        return
    target = int(MAX_CACHED_SESSIONS * 0.8)
    while total > target and SESSIONS:
        largest_user = max(SESSIONS, key=lambda uid: len(SESSIONS[uid]))
        user_convs = SESSIONS[largest_user]
        if not user_convs:
            del SESSIONS[largest_user]
            continue
        oldest_conv = next(iter(user_convs))
        del user_convs[oldest_conv]
        total -= 1
        if not user_convs:
            del SESSIONS[largest_user]
    logger.info(f"[session_manager] Cache eviction: {total} conversations retained.")


# --- Redis Key Helpers ---
def _get_user_conversations_key(user_id: str) -> str:
    return f"user:{user_id}:conversations"

def _get_profile_key(conversation_id: str) -> str:
    return f"conversation:{conversation_id}:profile"

def _get_summaries_key(conversation_id: str) -> str:
    return f"conversation:{conversation_id}:summaries"

def _get_title_key(conversation_id: str) -> str:
    return f"conversation:{conversation_id}:title"


# --- Database Data Load/Save Functions ---
def load_conversation_data_from_db(conversation_id: str) -> Dict[str, Any]:
    """Loads user profile and summaries for a specific conversation from Supabase (or cached Redis)."""
    from database import get_supabase
    
    profile = {}
    summaries = []
    title = "Untitled Chat"

    supabase = get_supabase()
    if supabase:
        try:
            res = supabase.table('conversations').select('*').eq('id', conversation_id).execute()
            if res.data:
                conv = res.data[0]
                profile = conv.get("profile_override", {}) or {}
                summaries = conv.get("summaries", []) or []
                title = conv.get("title", "Untitled Chat") or "Untitled Chat"
                return {"profile": profile, "summaries": summaries, "title": title}
        except Exception as e:
            logger.error(f"[session_manager] Supabase load error for {conversation_id}: {e}")

    # Fallback to Redis if Supabase is offline or conv is legacy
    if redis_client:
        try:
            profile_json = redis_client.get(_get_profile_key(conversation_id))
            if profile_json: profile = json.loads(profile_json)
            summaries_json = redis_client.get(_get_summaries_key(conversation_id))
            if summaries_json: summaries = json.loads(summaries_json)
            title_bytes = redis_client.get(_get_title_key(conversation_id))
            if title_bytes: title = title_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"[session_manager] Error loading fallback Redis data: {e}")

    return {"profile": profile, "summaries": summaries, "title": title}

def save_conversation_data_to_db(conversation_id: str, profile: Dict[str, Any], summaries: List[Dict[str, Any]], title: str):
    """Saves user profile and summaries for a specific conversation to Supabase (and cache)."""
    from database import get_supabase
    import datetime
    supabase = get_supabase()

    if supabase:
        try:
            supabase.table('conversations').update({
                "profile_override": profile,
                "summaries": summaries,
                "title": title,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).eq('id', conversation_id).execute()
        except Exception as e:
            logger.error(f"[session_manager] Supabase save error for {conversation_id}: {e}")

    # Mirror to Redis cache for active fast reloads
    if redis_client:
        ttl = CONVERSATION_TTL_SECONDS if CONVERSATION_TTL_SECONDS > 0 else None
        try:
            redis_client.set(_get_profile_key(conversation_id), json.dumps(profile), ex=ttl)
            redis_client.set(_get_summaries_key(conversation_id), json.dumps(summaries), ex=ttl)
            redis_client.set(_get_title_key(conversation_id), title, ex=ttl)
        except Exception:
            pass


# --- User Global Data ---
def load_user_learning_method(user_id: str) -> Optional[str]:
    """Loads a user's globally shared learning method from Supabase."""
    from database import get_supabase
    supabase = get_supabase()
    if supabase:
        try:
            res = supabase.table('users').select('learning_method').eq('username', user_id).execute()
            if res.data:
                return res.data[0].get("learning_method")
        except Exception:
            pass
    return None

def save_user_learning_method(user_id: str, method: str):
    """Saves a user's globally shared learning method to Supabase."""
    from database import get_supabase
    supabase = get_supabase()
    if supabase and method:
        try:
            supabase.table('users').update({'learning_method': method}).eq('username', user_id).execute()
            logger.info(f"[session_manager] Saved global learning method for {user_id} to DB.")
        except Exception as e:
            logger.error(f"[session_manager] Error saving generic learning method for {user_id}: {e}")


# --- Conversation Management ---
def create_new_conversation_id(user_id: str, initial_title: str = "Untitled Chat") -> str:
    """Generates a new conversation ID and associates it with the user in Supabase."""
    from database import get_supabase
    supabase = get_supabase()
    if not supabase:
        raise RuntimeError("Database persistence not configured.")

    conversation_id = str(uuid.uuid4())
    try:
        supabase.table('conversations').insert({
            "id": conversation_id,
            "user_id": user_id,
            "title": initial_title,
            "profile_override": {},
            "summaries": []
        }).execute()
        
        # Mirror user ownership to Redis for quick ownership checks
        if redis_client:
            redis_client.sadd(f"user:{user_id}:conversations", conversation_id)
            
        logger.info(f"[session_manager] Created conversation {conversation_id} for {user_id} in DB.")
        return conversation_id
    except Exception as e:
        logger.error(f"[session_manager] Error creating conversation {conversation_id} for {user_id}: {e}")
        raise RuntimeError(f"Failed to create new conversation: {e}")

def get_user_conversation_ids(user_id: str) -> List[Dict[str, str]]:
    """Retrieves all conversation IDs and titles for a given user from Supabase."""
    from database import get_supabase
    supabase = get_supabase()
    if not supabase:
        return []

    try:
        res = supabase.table('conversations').select('id, title').eq('user_id', user_id).order('created_at', desc=True).execute()
        if res.data:
            return [{"id": row["id"], "title": row.get("title", "Untitled Chat")} for row in res.data]
        return []
    except Exception as e:
        logger.error(f"[session_manager] Error retrieving DB conversations for {user_id}: {e}")
        return []


# --- Conversation History ---
def get_conversation_history(user_id: str, conversation_id: str) -> Optional[RedisChatMessageHistory]:
    """
    Retrieves or creates a RedisChatMessageHistory instance for a given user and conversation ID.
    Manages the session entry in the global SESSIONS dictionary.
    Also loads profile and summaries from Redis if conversation is new to in-memory cache.
    Returns None if IDs are invalid or cannot be processed.
    Raises RuntimeError if Redis connection fails during instantiation.
    """
    if not user_id or not conversation_id:
        logger.warning(f"[session] get_conversation_history called with invalid IDs. User: {user_id}, Conv: {conversation_id}.")
        return None

    if redis_client is None:
        logger.error("[session] Redis client not initialized. Cannot manage session history.")
        raise RuntimeError("Redis client is not initialized. Cannot manage session history.")

    # Enforce ownership: conversation_id must belong to the user
    try:
        is_member = redis_client.sismember(_get_user_conversations_key(user_id), conversation_id)
        if not is_member:
            # BUG-03 fix: Fallback to Supabase when Redis set is lost (flush/restart)
            from database import get_supabase
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table('conversations').select('id').eq('id', conversation_id).eq('user_id', user_id).execute()
                    if res.data:
                        # Re-sync ownership to Redis for future fast lookups
                        redis_client.sadd(_get_user_conversations_key(user_id), conversation_id)
                        logger.info(f"[session] Re-synced ownership for {conversation_id} -> {user_id} from Supabase.")
                        is_member = True
                except Exception as db_err:
                    logger.error(f"[session] Supabase ownership fallback failed: {db_err}")
            if not is_member:
                logger.warning(f"[session] Conversation {conversation_id} not found for user {user_id}.")
                return None
    except Exception as e:
        logger.error(f"[session] Error validating conversation ownership for {user_id}/{conversation_id}: {e}")
        raise RuntimeError(f"Failed to validate conversation ownership: {e}") from e

    # Ensure user_id entry exists in SESSIONS
    if user_id not in SESSIONS:
        SESSIONS[user_id] = {}
        logger.info(f"[session] Initializing new user entry in SESSIONS for: {user_id}")

    # Load or retrieve conversation data
    if conversation_id not in SESSIONS[user_id]:
        logger.info(f"[session] Initializing new conversation entry for user {user_id}, conversation: {conversation_id}")

        persisted_data = load_conversation_data_from_db(conversation_id)

        try:
            redis_history = RedisChatMessageHistory(session_id=conversation_id, redis_client=redis_client)
        except Exception as e:
            logger.error(f"[session] ERROR creating RedisChatMessageHistory for conv {conversation_id}: {e}")
            raise RuntimeError(f"Failed to initialize RedisChatMessageHistory for conversation {conversation_id}: {e}") from e

        _enforce_session_bounds()
        SESSIONS[user_id][conversation_id] = {
            "chat_history_redis": redis_history,
            "profile": persisted_data["profile"],
            "summaries": persisted_data["summaries"],
            "title": persisted_data["title"]
        }
        return redis_history
    else:
        conversation_data = SESSIONS[user_id][conversation_id]
        redis_history = conversation_data.get("chat_history_redis")

        # Re-create history object if missing or wrong type
        if redis_history is None or not isinstance(redis_history, RedisChatMessageHistory):
            logger.warning(f"[session] Re-initializing RedisChatMessageHistory for conv: {conversation_id}")
            try:
                redis_history = RedisChatMessageHistory(session_id=conversation_id, redis_client=redis_client)
                conversation_data["chat_history_redis"] = redis_history
            except Exception as e:
                logger.error(f"[session] ERROR re-initializing RedisChatMessageHistory for conv {conversation_id}: {e}")
                raise RuntimeError(f"Failed to re-initialize RedisChatMessageHistory: {e}") from e

        if "profile" not in conversation_data:
            conversation_data["profile"] = {}
        if "summaries" not in conversation_data:
            conversation_data["summaries"] = []

        return redis_history
