# main.py ΓÇö Sovereign AI Tutor Backend (Production-Hardened)
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Request, Form
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List
import uuid
import tempfile
import os
import json
import time
import hmac
import asyncio
import collections

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
import jwt
import sys

# Ensure Python can resolve all general_tutor modules when launched from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import components from our modules
import config
from config import (
    logger, ADMIN_IDS, JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS,
    validate_safe_string, validate_safe_name,
    RATE_LIMIT_CHAT, RATE_LIMIT_GENERATE, RATE_LIMIT_UPLOAD, RATE_LIMIT_AUTH,
    TEACHER_CONTENT_TTL_SECONDS,
)
from models import ChatRequest, ConversationItem, NewConversationRequest
from session_manager import (
    SESSIONS, get_conversation_history, save_conversation_data_to_db,
    create_new_conversation_id, get_user_conversation_ids,
    load_user_learning_method, save_user_learning_method
)
from agent_core import with_message_history
from file_utils import process_uploaded_file
from ai_summarizer import generate_conversation_title

# ΓöÇΓöÇΓöÇ RATE LIMITING ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, storage_uri=config.REDIS_URL)

# ΓöÇΓöÇΓöÇ STREAMING UPLOAD GUARD ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB hard limit

async def _stream_to_tempfile_bounded(file: UploadFile, suffix: str, max_bytes: int = MAX_UPLOAD_BYTES) -> str:
    """Stream-reads an upload directly to disk, enforcing byte limit BEFORE buffering (prevents OOM)."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb")
    try:
        total = 0
        while True:
            chunk = await file.read(8192)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(status_code=413, detail=f"File exceeds {max_bytes // (1024*1024)} MB limit")
            tmp.write(chunk)
        tmp.flush()
        return tmp.name
    except Exception:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise
    finally:
        tmp.close()

# ΓöÇΓöÇΓöÇ PER-CONVERSATION MUTATION LOCK ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
_conv_locks: collections.OrderedDict = collections.OrderedDict()
_MAX_CONV_LOCKS = 1000

def _get_conv_lock(conv_id: str) -> asyncio.Lock:
    """Returns a per-conversation asyncio lock for state mutation protection (bounded)."""
    if conv_id in _conv_locks:
        _conv_locks.move_to_end(conv_id)
        return _conv_locks[conv_id]
    if len(_conv_locks) >= _MAX_CONV_LOCKS:
        _conv_locks.popitem(last=False)  # Evict oldest
    _conv_locks[conv_id] = asyncio.Lock()
    return _conv_locks[conv_id]

# ΓöÇΓöÇΓöÇ STRUCTURED ERROR RESPONSE ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
class ErrorResponse(BaseModel):
    error: str
    code: int
    detail: Optional[str] = None

def error_json(code: int, error: str, detail: str = None) -> JSONResponse:
    """Returns a structured JSON error response."""
    return JSONResponse(
        status_code=code,
        content=ErrorResponse(error=error, code=code, detail=detail).model_dump()
    )

# ΓöÇΓöÇΓöÇ SINGLE FastAPI Instance ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
bearer_scheme = HTTPBearer(auto_error=False)

app = FastAPI(
    title="student_copilot ΓÇö Sovereign AI Tutor",
    openapi_extra={
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "JWT token obtained from /auth/token endpoint."
                }
            }
        },
        "security": [{"BearerAuth": []}]
    }
)

# Attach rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ΓöÇΓöÇΓöÇ CORS ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.openapi_tags = [
    {"name": "Authentication", "description": "JWT token management."},
    {"name": "Conversation Management", "description": "User and conversation lifecycle."},
    {"name": "AI Tutor Core", "description": "Chat and file upload endpoints."},
    {"name": "Notebook Oracle", "description": "Ground-truth retrieval from vectorized documents."},
    {"name": "Teacher Administrative", "description": "Admin-only knowledge curation."},
    {"name": "Revision Mode", "description": "Socratic assessment engine."},
]

# ΓöÇΓöÇΓöÇ GLOBAL EXCEPTION HANDLER ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
@app.exception_handler(HTTPException)
async def structured_http_exception_handler(request: Request, exc: HTTPException):
    """Converts all HTTPExceptions into structured {error, code, detail} responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail if isinstance(exc.detail, str) else "Request failed",
            code=exc.status_code,
            detail=str(exc.detail)
        ).model_dump()
    )

@app.exception_handler(ValueError)
async def validation_error_handler(request: Request, exc: ValueError):
    """Catches input validation errors from config.validate_safe_string."""
    logger.warning(f"[validation] {exc}")
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error="Validation error", code=422, detail=str(exc)).model_dump()
    )


# ΓöÇΓöÇΓöÇ JWT AUTH SYSTEM ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
class TokenMetaRequest(BaseModel):
    user_id: str
    role: str = "student"  # "student" or "admin"

def create_jwt(user_id: str, role: str = "student") -> str:
    """Creates a signed JWT token."""
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + (JWT_EXPIRY_HOURS * 3600),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt(token: str) -> Dict[str, Any]:
    """Decodes and validates a JWT token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired. Please re-authenticate.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """
    Dual-mode auth: accepts JWT Bearer token OR legacy X-User-ID header.
    JWT takes priority. Falls back to X-User-ID for backwards compatibility.
    """
    # Try JWT first
    if credentials and credentials.credentials:
        payload = decode_jwt(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim.")
        user_id = validate_safe_string(user_id, "user_id")
        # Inject role into request state for downstream use
        request.state.user_role = payload.get("role", "student")
        return user_id

    # Fallback to legacy X-User-ID header
    if config.ALLOW_LEGACY_AUTH:
        legacy_id = request.headers.get("X-User-ID")
    else:
        legacy_id = None
    if legacy_id:
        legacy_id = validate_safe_string(legacy_id, "user_id")
        logger.warning(f"[auth] Legacy X-User-ID header used by {legacy_id}. Migrate to JWT.")
        request.state.user_role = "admin" if legacy_id in ADMIN_IDS else "student"
        return legacy_id

    raise HTTPException(status_code=401, detail="Authentication required. Send JWT Bearer token or X-User-ID header.")


@app.get("/health")
async def health_check() -> Dict[str, str]:
    from session_manager import redis_client as r
    try:
        if r:
            r.ping()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"[health] Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Health check failed")


async def require_admin(
    request: Request,
    user_id: str = Depends(get_current_user)
):
    """Ensures the current user is an admin (JWT role, static allow-list, or Redis admin set)."""
    is_admin = False
    try:
        if getattr(request.state, "user_role", None) == "admin":
            is_admin = True
        elif user_id in ADMIN_IDS:
            is_admin = True
        else:
            from llm_setup import redis_client as r
            if r:
                is_admin = r.sismember("system:admins", user_id)
    except Exception as e:
        logger.error(f"[auth] Redis check failed for admin status: {e}")

    if not is_admin:
        logger.warning(f"[auth] Non-admin user {user_id} attempted teacher action.")
        raise HTTPException(status_code=403, detail="Forbidden: Admin privileges required.")
    return user_id


# ΓöÇΓöÇΓöÇ USER PROFILE & AUTH ENDPOINTS ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

MIN_PASSWORD_LENGTH = 8
PBKDF2_ITERATIONS = 600_000  # OWASP 2024+ recommendation for SHA-256

class UserRegistration(BaseModel):
    username: str
    password: str
    role: str = "student" # "student" or "admin"
    # Profile fields
    full_name: str
    age: Optional[int] = None
    country: Optional[str] = None
    class_id: Optional[str] = None
    subjects: Optional[str] = None

    @field_validator("username", mode="before")
    @classmethod
    def sanitize_username(cls, v, info):
        return validate_safe_string(v, info.field_name)

    @field_validator("full_name", mode="before")
    @classmethod
    def sanitize_full_name(cls, v, info):
        return validate_safe_name(v, info.field_name)

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, v):
        if not v or len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return v

    @field_validator("role", mode="before")
    @classmethod
    def sanitize_role(cls, v):
        role = validate_safe_string(v, "role").lower()
        if role not in {"student", "admin"}:
            raise ValueError("role must be 'student' or 'admin'")
        return role

class TokenRequest(BaseModel):
    username: str
    password: str

@app.post("/auth/register", tags=["Authentication"])
@limiter.limit(RATE_LIMIT_AUTH)
async def register_user(request: Request, req: UserRegistration):
    """Registers a new user, saving their profile securely to Supabase and cache."""
    from llm_setup import redis_client as r
    from database import get_supabase
    import hashlib
    import secrets

    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="Database persistence not configured.")

    # Check if user exists in Supabase
    existing_user = supabase.table('users').select('username').eq('username', req.username).execute()
    if existing_user.data:
        raise HTTPException(status_code=400, detail="Username already exists.")

    if req.role == "admin" and req.username not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin registration is restricted.")

    salt = secrets.token_hex(16)
    hashed_pw = hashlib.pbkdf2_hmac('sha256', req.password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    stored_hash = f"{salt}:{hashed_pw}"

    profile_data = {
        "username": req.username,
        "password_hash": stored_hash,
        "role": req.role,
        "full_name": req.full_name,
        "age": req.age,
        "country": req.country or "",
        "class_id": req.class_id or "",
        "subjects": req.subjects or "",
        "learning_method": ""
    }
    
    try:
        supabase.table('users').insert(profile_data).execute()
    except Exception as e:
        logger.error(f"[auth] Supabase registration error: {e}")
        raise HTTPException(status_code=500, detail="Failed to register user to database.")
    
    # Save a cached version as strings for fast fallback
    r.hset(f"user:{req.username}:profile", mapping={k: str(v) if v is not None else "" for k, v in profile_data.items()})
    
    # If registering as teacher, add to dynamic admin set
    if req.role == "admin":
        r.sadd("system:admins", req.username)

    logger.info(f"[auth] Registered new {req.role}: {req.username}")
    
    token = create_jwt(req.username, req.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": req.username,
        "role": req.role,
        "message": "Registration successful."
    }


@app.post("/auth/token", tags=["Authentication"])
@limiter.limit(RATE_LIMIT_AUTH)
async def login_for_token(request: Request, req: TokenRequest):
    """Authenticates a user and issues a JWT."""
    from database import get_supabase
    import hashlib

    validate_safe_string(req.username, "username")
    
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="Database persistence not configured.")
        
    res = supabase.table('users').select('*').eq('username', req.username).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    
    profile = res.data[0]
    stored_hash = profile.get("password_hash")
    
    is_valid = False
    if stored_hash and ':' in stored_hash:
        try:
            salt, hashed_pw = stored_hash.split(':', 1)
            check_hash = hashlib.pbkdf2_hmac('sha256', req.password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
            is_valid = hmac.compare_digest(check_hash, hashed_pw)
        except (ValueError, TypeError):
            is_valid = False
            
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    role = profile.get("role", "student")
    token = create_jwt(req.username, role)
    
    logger.info(f"[auth] Login successful for {req.username} (role={role})")
    
    # Sync fast cache just in case
    from llm_setup import redis_client as r
    r.hset(f"user:{req.username}:profile", mapping={k: str(v) if v is not None else "" for k, v in profile.items()})
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_hours": JWT_EXPIRY_HOURS,
        "user_id": req.username,
        "role": role,
    }


@app.get("/users/me", tags=["Authentication"])
async def get_my_profile(user_id: str = Depends(get_current_user)):
    """Returns the current user's personalized data from Supabase."""
    from database import get_supabase
    
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="Database persistence not configured.")
        
    res = supabase.table('users').select('*').eq('username', user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="User profile not found in Supabase.")
        
    profile_out = res.data[0]
    # Remove auth secrets before returning
    profile_out.pop("password_hash", None)
    
    return profile_out


# =============================================================================
# CONVERSATION MANAGEMENT
# =============================================================================

@app.post("/conversations/new", tags=["Conversation Management"])
async def new_conversation(
    request_body: NewConversationRequest,
    user_id: str = Depends(get_current_user)
) -> Dict[str, str]:
    """Creates a new conversation ID for the given user."""
    logger.info(f"[main] User {user_id} requested a new conversation.")

    initial_title = request_body.suggested_title
    if not initial_title and request_body.initial_message:
        try:
            initial_title = await generate_conversation_title(request_body.initial_message)
        except Exception as e:
            logger.warning(f"[main] Could not generate title: {e}. Falling back.")
            initial_title = "Untitled Chat"
    elif not initial_title:
        initial_title = "New Chat"

    try:
        conversation_id = create_new_conversation_id(user_id, initial_title)
        global_method = load_user_learning_method(user_id)
        init_profile = {}
        if global_method:
            init_profile["learning_method"] = global_method

        SESSIONS.setdefault(user_id, {}).setdefault(conversation_id, {
            "chat_history_redis": None,
            "profile": init_profile,
            "summaries": [],
            "title": initial_title
        })
        logger.info(f"[main] Created conversation {conversation_id} titled '{initial_title}' for {user_id}.")
        return {
            "conversation_id": conversation_id,
            "title": initial_title,
            "message": "New conversation created.",
            "learning_method": global_method or ""
        }
    except RuntimeError as e:
        logger.error(f"[main] Error creating conversation for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create conversation: {e}")


@app.get("/conversations", tags=["Conversation Management"], response_model=Dict[str, List[ConversationItem]])
async def list_user_conversations(user_id: str = Depends(get_current_user)):
    """Lists all conversations for the authenticated user."""
    logger.info(f"[main] User {user_id} requested conversation list.")
    conversations_data = get_user_conversation_ids(user_id)
    return {"conversations": conversations_data}


@app.post("/conversations/{conversation_id}/end", tags=["Conversation Management"])
async def end_conversation(conversation_id: str, user_id: str = Depends(get_current_user)):
    """Evaluate session and update the user's permanent learning strategy."""
    conversation_id = validate_safe_string(conversation_id, "conversation_id")
    logger.info(f"[main] Ending conversation {conversation_id} for {user_id}")

    try:
        conv_history_obj = get_conversation_history(user_id, conversation_id)
        if conv_history_obj is None:
            raise HTTPException(status_code=400, detail="Invalid conversation ID")

        # Acquire lock — prevents race with concurrent /chat mutations (BUG-06 fix)
        async with _get_conv_lock(conversation_id):
            conversation_data = SESSIONS[user_id][conversation_id]
            profile = conversation_data.get("profile", {})

            global_method = load_user_learning_method(user_id) or profile.get("learning_method", "")

            messages = conv_history_obj.messages
            chat_history_str = "\n".join([f"{msg.type}: {msg.content}" for msg in messages])

            from ai_summarizer import evaluate_session_learning_method
            new_method = await evaluate_session_learning_method(profile, chat_history_str, global_method)

            if new_method and new_method != global_method:
                save_user_learning_method(user_id, new_method)
                conversation_data["profile"]["learning_method"] = new_method
                save_conversation_data_to_db(
                    conversation_id,
                    conversation_data["profile"],
                    conversation_data["summaries"],
                    conversation_data.get("title", "Untitled Chat")
                )
                return {"status": "updated", "learning_method": new_method}

            return {"status": "unchanged", "learning_method": global_method}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[main] End conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# UPLOAD ENDPOINT
# =============================================================================

GENERAL_UPLOAD_SUFFIXES = {".pdf", ".txt", ".md", ".csv", ".json"}

@app.post("/upload", tags=["AI Tutor Core"])
@limiter.limit(RATE_LIMIT_UPLOAD)
async def upload_file(
    request: Request,
    conversation_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user)
):
    conversation_id = validate_safe_string(conversation_id, "conversation_id")
    logger.info(f"[main] User {user_id} uploading for conv: {conversation_id}, file: {file.filename}")

    suffix = os.path.splitext(file.filename)[1].lower() if file.filename else ".dat"
    if suffix not in GENERAL_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{suffix}'. Supported: {GENERAL_UPLOAD_SUFFIXES}")

    try:
        conv_history_obj = get_conversation_history(user_id, conversation_id)
        if conv_history_obj is None:
            raise HTTPException(status_code=400, detail=f"Invalid conversation ID: '{conversation_id}'.")
        conversation_data = SESSIONS[user_id][conversation_id]
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Redis connection error: {e}")

    try:
        tmp_path = await _stream_to_tempfile_bounded(file, suffix)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read upload: {e}")

    try:
        summary = await process_uploaded_file(tmp_path, file.filename, owner_id=user_id)
    except Exception as e:
        logger.error(f"[main] File processing error for conv {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process uploaded file.")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    conversation_data["summaries"].append({"filename": file.filename, "summary": summary})
    save_conversation_data_to_db(
        conversation_id,
        conversation_data["profile"],
        conversation_data["summaries"],
        conversation_data.get("title", "Untitled Chat")
    )

    return {"status": "ok", "summary": summary}


# =============================================================================
# CHAT ENDPOINT
# =============================================================================

@app.post("/chat", tags=["AI Tutor Core"])
@limiter.limit(RATE_LIMIT_CHAT)
async def chat(
    request: Request,
    req: ChatRequest,
    user_id: str = Depends(get_current_user)
):
    logger.info(f"[main] User {user_id} chat for conv: {req.conversation_id}")

    try:
        conv_history_obj = get_conversation_history(user_id, req.conversation_id)
        if conv_history_obj is None:
            raise HTTPException(status_code=400, detail=f"Invalid conversation ID: '{req.conversation_id}'.")
        conversation_data = SESSIONS[user_id][req.conversation_id]
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Redis connection error: {e}")

    # Acquire per-conversation lock for profile mutation (prevents race on concurrent requests)
    async with _get_conv_lock(req.conversation_id):
        if req.user_profile:
            allowed_profile_keys = {"full_name", "age", "country", "class_id", "subjects"}
            cleaned_updates: Dict[str, Any] = {}
            for k, v in req.user_profile.items():
                if k not in allowed_profile_keys:
                    continue
                if v is None:
                    continue
                if k == "age":
                    try:
                        age_int = int(v)
                    except (ValueError, TypeError):
                        continue
                    if 3 <= age_int <= 120:
                        cleaned_updates[k] = age_int
                    continue
                if isinstance(v, (str, int, float, bool)):
                    s = str(v)
                    if s.strip():
                        cleaned_updates[k] = validate_safe_string(s, k)

            if cleaned_updates:
                conversation_data["profile"].update(cleaned_updates)

            global_method = load_user_learning_method(user_id)
            if not global_method and "learning_method" not in conversation_data["profile"]:
                from ai_summarizer import generate_learning_method
                learning_method = await generate_learning_method(conversation_data["profile"])
                if learning_method:
                    conversation_data["profile"]["learning_method"] = learning_method
                    save_user_learning_method(user_id, learning_method)
            elif global_method and "learning_method" not in conversation_data["profile"]:
                conversation_data["profile"]["learning_method"] = global_method

            save_conversation_data_to_db(
                req.conversation_id,
                conversation_data["profile"],
                conversation_data["summaries"],
                conversation_data.get("title", "Untitled Chat")
            )

    profile_text = ", ".join(f"{k}={v}" for k, v in conversation_data["profile"].items()) if conversation_data["profile"] else "no profile provided"
    file_summaries_text = "\n".join([f"{s['filename']}: {s['summary']}" for s in conversation_data["summaries"]]) if conversation_data["summaries"] else "no uploaded file summaries"

    try:
        input_dict = {
            "input": req.message,
            "user_profile": profile_text,
            "file_summaries": file_summaries_text
        }
        response = await with_message_history.ainvoke(
            input_dict,
            config={"configurable": {"session_id": req.conversation_id, "user_id": user_id}}
        )
        reply = response.get("output", "I'm sorry, I couldn't process that request.")
        return {"status": "ok", "reply": reply}
    except Exception as e:
        logger.error(f"[main] Agent execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during chat processing.")


# =============================================================================
# NOTEBOOK ORACLE MODULE
# =============================================================================

class NotebookQuestionRequest(BaseModel):
    question: str
    active_subject: Optional[str] = None
    active_class: Optional[str] = None

    @field_validator("active_subject", "active_class", mode="before")
    @classmethod
    def sanitize_optional(cls, v):
        if v is not None and v.strip():
            return validate_safe_string(v, "subject/class field")
        return v

SUPPORTED_UPLOAD_SUFFIXES = {".pdf", ".txt", ".md"}


def _ingest_to_pinecone(
    tmp_path: str,
    suffix: str,
    filename: str,
    metadata_base: Dict[str, str],
    parent_chunk_size: int = 2000,
    redis_ttl: Optional[int] = None,
) -> int:
    """Shared ingestion: extract text → parent/child chunk → store parents in Redis → vectorize children in Pinecone.
    Returns the total number of child chunks ingested."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_pinecone import PineconeVectorStore
    from llm_setup import redis_client as r, embeddings as _emb
    from config import PINECONE_INDEX_NAME

    if suffix == ".pdf":
        import pymupdf4llm
        text = pymupdf4llm.to_markdown(tmp_path)
    else:
        with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

    if not text.strip():
        raise HTTPException(status_code=422, detail="Uploaded file appears to be empty.")

    parent_splitter = RecursiveCharacterTextSplitter(chunk_size=parent_chunk_size, chunk_overlap=200)
    child_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)

    parent_chunks = parent_splitter.split_text(text)
    all_child_chunks = []
    metadatas = []

    for p_chunk in parent_chunks:
        parent_id = f"parent_{uuid.uuid4().hex}"
        r.hset(parent_id, "content", p_chunk)
        if redis_ttl and redis_ttl > 0:
            r.expire(parent_id, redis_ttl)

        children = child_splitter.split_text(p_chunk)
        all_child_chunks.extend(children)
        metadatas.extend([{
            **metadata_base,
            "source": filename,
            "parent_id": parent_id,
        } for _ in children])

    PineconeVectorStore.from_texts(
        all_child_chunks, embedding=_emb,
        index_name=PINECONE_INDEX_NAME, metadatas=metadatas
    )
    return len(all_child_chunks)


@app.post("/notebook/upload", tags=["Notebook Oracle"])
@limiter.limit(RATE_LIMIT_UPLOAD)
async def notebook_upload(
    request: Request,
    file: UploadFile = File(...),
    subject: str = Form("General"),
    class_id: str = Form("General"),
    user_id: str = Depends(get_current_user)
):
    # Sanitize inputs
    subject = validate_safe_string(subject, "subject")
    class_id = validate_safe_string(class_id, "class_id")

    logger.info(f"[notebook] User {user_id} uploading {file.filename} (Subject: {subject}, Class: {class_id})")
    from config import PINECONE_API_KEY, PINECONE_INDEX_NAME
    from llm_setup import embeddings

    if not PINECONE_API_KEY or not embeddings:
        raise HTTPException(status_code=500, detail="Pinecone not configured.")

    suffix = os.path.splitext(file.filename)[1].lower() if file.filename else ".dat"
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{suffix}'. Supported: {SUPPORTED_UPLOAD_SUFFIXES}")

    try:
        tmp_path = await _stream_to_tempfile_bounded(file, suffix)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read notebook upload: {e}")

    try:
        from config import CONVERSATION_TTL_SECONDS
        chunk_count = _ingest_to_pinecone(
            tmp_path=tmp_path,
            suffix=suffix,
            filename=file.filename,
            metadata_base={"owner_id": user_id, "role": "student", "subject": subject, "class_id": class_id},
            parent_chunk_size=2000,
            redis_ttl=CONVERSATION_TTL_SECONDS if CONVERSATION_TTL_SECONDS and CONVERSATION_TTL_SECONDS > 0 else None,
        )
        session_id = f"notebook_{str(uuid.uuid4())[:8]}"
        return {"session_id": session_id, "chunks": chunk_count, "subject": subject}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[notebook] Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/notebook/ask", tags=["Notebook Oracle"])
@limiter.limit(RATE_LIMIT_CHAT)
async def notebook_ask(
    request: Request,
    req: NotebookQuestionRequest,
    user_id: str = Depends(get_current_user)
):
    logger.info(f"[notebook] User {user_id} asking grounded question on Subject: {req.active_subject}")
    from config import PINECONE_API_KEY, PINECONE_INDEX_NAME
    from llm_setup import llm, embeddings, redis_client as r
    from session_manager import load_user_learning_method

    if not PINECONE_API_KEY or not embeddings:
        raise HTTPException(status_code=500, detail="Pinecone not configured.")

    try:
        global_method = load_user_learning_method(user_id)
        pedagogy_instruction = f"PEDAGOGICAL STRATEGY: {global_method}" if global_method else ""

        user_class = req.active_class
        allowed_subjects = [req.active_subject] if req.active_subject else []

        filter_conditions = [{"owner_id": {"$eq": user_id}}]
        if user_class:
            teacher_filter = {"$and": [
                {"role": {"$eq": "teacher"}},
                {"class_id": {"$eq": user_class}}
            ]}
            if allowed_subjects:
                teacher_filter["$and"].append({"subject": {"$in": allowed_subjects}})
            filter_conditions.append(teacher_filter)

        rbac_filter = {"$or": filter_conditions}

        from langchain_pinecone import PineconeVectorStore
        vectorstore = PineconeVectorStore(index_name=PINECONE_INDEX_NAME, embedding=embeddings)
        retriever = vectorstore.as_retriever(search_kwargs={"k": 5, "filter": rbac_filter})

        docs = retriever.invoke(req.question)
        
        parent_ids = list(set([doc.metadata.get("parent_id") for doc in docs if doc.metadata.get("parent_id")]))
        parent_texts = []
        for pid in parent_ids:
            p_content = r.hget(pid, "content")
            if p_content:
                parent_texts.append(p_content.decode(errors="ignore"))
                
        if parent_texts:
            context = "\n\n---\n\n".join(parent_texts)
        else:
            context = "\n\n".join([doc.page_content for doc in docs])

        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are the Notebook Oracle. Your knowledge is strictly limited to the provided context. "
                       "You must provide accurate, factual answers derived ONLY from the context. "
                       "If information is missing, say: 'I cannot find this in your provided context.' "
                       "Do not apologize. Do not invent facts.\n\n"
                       f"{pedagogy_instruction}\n\nContext:\n{{context}}"),
            ("user", "{question}")
        ])

        chain = prompt | llm | StrOutputParser()
        answer = await chain.ainvoke({"context": context, "question": req.question})

        return {
            "answer": answer.strip(),
            "context_sources": list(set([doc.metadata.get("source") for doc in docs]))
        }
    except Exception as e:
        logger.error(f"[notebook] Ask failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TEACHER ADMINISTRATIVE MODULE (Admin-gated)
# =============================================================================

@app.post("/teacher/upload", tags=["Teacher Administrative"])
@limiter.limit(RATE_LIMIT_UPLOAD)
async def teacher_upload(
    request: Request,
    file: UploadFile = File(...),
    class_id: str = Form(...),
    subject: str = Form(...),
    user_id: str = Depends(require_admin)
):
    # Sanitize inputs
    class_id = validate_safe_string(class_id, "class_id")
    subject = validate_safe_string(subject, "subject")

    logger.info(f"[teacher] Admin {user_id} uploading global context for {class_id} / {subject}")
    from config import PINECONE_API_KEY, PINECONE_INDEX_NAME
    from llm_setup import embeddings

    if not PINECONE_API_KEY or not embeddings:
        raise HTTPException(status_code=500, detail="Pinecone not configured.")

    suffix = os.path.splitext(file.filename)[1].lower() if file.filename else ".dat"

    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{suffix}'. Supported: {SUPPORTED_UPLOAD_SUFFIXES}")

    try:
        tmp_path = await _stream_to_tempfile_bounded(file, suffix)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read upload: {e}")

    try:
        teacher_ttl = TEACHER_CONTENT_TTL_SECONDS if TEACHER_CONTENT_TTL_SECONDS > 0 else None
        chunk_count = _ingest_to_pinecone(
            tmp_path=tmp_path,
            suffix=suffix,
            filename=file.filename,
            metadata_base={"role": "teacher", "class_id": class_id, "subject": subject},
            parent_chunk_size=2500,
            redis_ttl=teacher_ttl,
        )
        return {"status": "Global context ingested", "class": class_id, "subject": subject, "chunks": chunk_count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[teacher] Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Teacher upload processing failed.")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)





# =============================================================================
# REVISION & ASSESSMENT MODULE
# =============================================================================

class RevisionRequest(BaseModel):
    subject: str
    class_id: Optional[str] = None
    topics: Optional[str] = None
    mcq_count: int = 5
    theory_count: int = 2

    @field_validator("subject", mode="before")
    @classmethod
    def sanitize_subject(cls, v):
        return validate_safe_string(v, "subject")

    @field_validator("class_id", mode="before")
    @classmethod
    def sanitize_class_id(cls, v):
        if v is not None and v.strip():
            return validate_safe_string(v, "class_id")
        return v


class RevisionSubmission(BaseModel):
    subject: str
    class_id: Optional[str] = None
    questions: List[Dict[str, Any]]
    answers: Dict[str, str]

    @field_validator("subject", mode="before")
    @classmethod
    def sanitize_subject(cls, v):
        return validate_safe_string(v, "subject")


@app.post("/revision/generate", tags=["Revision Mode"])
@limiter.limit(RATE_LIMIT_GENERATE)
async def generate_exam(
    request: Request,
    req: RevisionRequest,
    user_id: str = Depends(get_current_user)
):
    """Generates a personalized exam based on grounded textbook context."""
    from config import PINECONE_INDEX_NAME
    from llm_setup import llm, embeddings, redis_client as r

    if not embeddings:
        raise HTTPException(status_code=500, detail="Embeddings not initialized.")

    try:
        user_class = req.class_id

        if not user_class:
            raise HTTPException(
                status_code=400,
                detail="No class_id provided. Please specify a class."
            )

        rbac_filter = {
            "$and": [
                {"role": {"$eq": "teacher"}},
                {"class_id": {"$eq": user_class}},
                {"subject": {"$eq": req.subject}}
            ]
        }

        from langchain_pinecone import PineconeVectorStore
        vectorstore = PineconeVectorStore(index_name=PINECONE_INDEX_NAME, embedding=embeddings)
        query = req.topics if req.topics else f"Core concepts of {req.subject}"
        docs = vectorstore.similarity_search(query, k=15, filter=rbac_filter)

        if not docs:
            raise HTTPException(
                status_code=404,
                detail=f"No teaching materials found for {req.subject} in class {user_class}. Ask your teacher to upload content first."
            )

        parent_ids = list(set([doc.metadata.get("parent_id") for doc in docs if doc.metadata.get("parent_id")]))
        parent_texts = []
        for pid in parent_ids:
            p_content = r.hget(pid, "content")
            if p_content:
                parent_texts.append(p_content.decode(errors="ignore"))
                
        if parent_texts:
            context = "\n\n---\n\n".join(parent_texts)
        else:
            context = "\n\n".join([doc.page_content for doc in docs])

        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser

        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an Elite Exam Designer. Generate a high-quality exam based ONLY on the provided context. "
                       "Output EXACTLY a JSON object with this key: 'questions' (a list of objects). "
                       "Each question object must have: 'id' (string), 'type' ('mcq' or 'theory'), 'text' (string), "
                       "'options' (list of strings, for mcq only), 'correct_answer' (string, for mcq only). "
                       f"Generate {req.mcq_count} MCQs and {req.theory_count} Theory questions.\n\n"
                       f"Topics/Focus: {req.topics or 'General'}\n\n"
                       "Context:\n{context}"),
            ("user", "Generate the exam now.")
        ])

        chain = prompt | llm | JsonOutputParser()
        exam = await chain.ainvoke({"context": context})
        return exam

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[revision] Generation failed: {e}")
        raise HTTPException(status_code=500, detail="Exam generation failed.")


@app.post("/revision/evaluate", tags=["Revision Mode"])
@limiter.limit(RATE_LIMIT_GENERATE)
async def evaluate_exam(
    request: Request,
    submission: RevisionSubmission,
    user_id: str = Depends(get_current_user)
):
    """Evaluates the exam, grades it, and provides personalized pedagogical feedback."""
    from config import PINECONE_INDEX_NAME
    from llm_setup import llm, embeddings, redis_client as r
    from session_manager import load_user_learning_method

    if not embeddings:
        raise HTTPException(status_code=500, detail="Embeddings not initialized.")

    try:
        user_class = submission.class_id
        global_method = load_user_learning_method(user_id)

        filter_conditions = [{"role": {"$eq": "teacher"}}, {"subject": {"$eq": submission.subject}}]
        if user_class:
            filter_conditions.append({"class_id": {"$eq": user_class}})
        rbac_filter = {"$and": filter_conditions}

        from langchain_pinecone import PineconeVectorStore
        vectorstore = PineconeVectorStore(index_name=PINECONE_INDEX_NAME, embedding=embeddings)
        docs = vectorstore.similarity_search(submission.subject, k=15, filter=rbac_filter)
        
        parent_ids = list(set([doc.metadata.get("parent_id") for doc in docs if doc.metadata.get("parent_id")]))
        parent_texts = []
        for pid in parent_ids:
            p_content = r.hget(pid, "content")
            if p_content:
                parent_texts.append(p_content.decode(errors="ignore"))
                
        if parent_texts:
            context = "\n\n---\n\n".join(parent_texts)
        else:
            context = "\n\n".join([doc.page_content for doc in docs])

        from langchain_core.prompts import ChatPromptTemplate

        eval_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a Sovereign Educator. Grade this exam submission against the ground truth context. "
                       "Be strict but fair. For every failed question, provide a deep explanation using the student's LEARNING METHOD. "
                       "Also, provide a 'summary' of their strengths and weaknesses. "
                       "If there are significant new insights about how the student learns, suggest an update to their LEARNING METHOD at the end.\n\n"
                       f"STUDENT LEARNING METHOD: {global_method or 'Not yet established'}\n\n"
                       "GROUND TRUTH CONTEXT:\n{context}"),
            ("user", "QUESTIONS: {questions}\n\nANSWERS: {answers}")
        ])

        chain = eval_prompt | llm
        result = await chain.ainvoke({
            "context": context,
            "questions": json.dumps(submission.questions),
            "answers": json.dumps(submission.answers)
        })

        feedback_text = result.content if hasattr(result, 'content') else str(result)
        return {"feedback": feedback_text, "status": "evaluated"}
    except Exception as e:
        logger.error(f"[revision] Evaluation failed: {e}")
        raise HTTPException(status_code=500, detail="Exam evaluation failed.")


# =============================================================================
# SERVER ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload_flag = "--reload" in sys.argv

    logger.info(f"[startup] Starting Uvicorn on {host}:{port} (reload={reload_flag})")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload_flag,
        log_level="info",
    )
