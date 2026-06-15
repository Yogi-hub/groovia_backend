# routers/chat.py
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from langchain_core.messages import AIMessage, HumanMessage

import config
import db
import backend  # accessed at request-time so we read the lifespan-initialized app
from auth import AuthUser, get_current_user, get_current_user_optional
from backend import _text
from rate_limit import limiter
from schema import ChatResponse
from utils import parse_docx_to_text, parse_pdf_to_text

logger = logging.getLogger("immigroov.routers.chat")

router = APIRouter(tags=["chat"])

PDF_MAGIC = b"%PDF"
DOCX_MAGIC = b"PK\x03\x04"


def _detect_file_type(file_bytes: bytes, filename: str) -> Optional[str]:
    """Validate actual file content against declared extension via magic bytes."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" and file_bytes[:4] == PDF_MAGIC:
        return "pdf"
    if ext == ".docx" and file_bytes[:4] == DOCX_MAGIC:
        return "docx"
    return None


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(config.RATE_LIMIT)
async def chat_handler(
    request: Request,
    message: str = Form(...),
    thread_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    """Main chat endpoint. Works in guest mode (no JWT) and authenticated mode."""
    try:
        uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format.")

    session_config = {"configurable": {"thread_id": thread_id}}

    resume_text = None
    if file:
        file_bytes = await file.read()
        if len(file_bytes) > config.MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max {config.MAX_FILE_BYTES // (1024 * 1024)} MB.",
            )

        file_type = _detect_file_type(file_bytes, file.filename or "")
        if not file_type:
            raise HTTPException(
                status_code=415,
                detail="Unsupported or mismatched file type. Upload PDF or DOCX only.",
            )
        resume_text = (
            parse_pdf_to_text(file_bytes) if file_type == "pdf" else parse_docx_to_text(file_bytes)
        )

    input_state = {"messages": [HumanMessage(content=message)]}
    if resume_text:
        input_state["resume_text"] = resume_text
        input_state["resume_processed"] = False

    if backend.app is None:
        raise HTTPException(status_code=503, detail="Agent not ready. Try again in a moment.")

    try:
        final_state = await asyncio.wait_for(
            backend.app.ainvoke(input_state, config=session_config),
            timeout=config.AGENT_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Agent timed out. Please try again.")
    except Exception:
        logger.exception("Agent invocation failed", extra={"thread_id": thread_id})
        raise HTTPException(status_code=500, detail="Internal error. Please try again.")

    # Title seed: a short snippet of the user's real message (not the system marker).
    title_seed = None
    if message and not message.startswith("[SYSTEM_"):
        title_seed = message.strip()

    # supabase-py is synchronous — run on the default thread pool so we don't block the event loop.
    await asyncio.to_thread(
        db.upsert_chat_thread,
        thread_id=thread_id,
        user_id=user.id if user else None,
        user_intent=final_state.get("user_intent"),
        track=final_state.get("track"),
        title_seed=title_seed,
    )

    # Mirror compressed resume onto the user's profile, write-once (manual edits stay).
    if user and final_state.get("resume_processed") and final_state.get("resume_text"):
        await asyncio.to_thread(
            db.save_profile_summary_if_empty, user.id, final_state["resume_text"]
        )

    return {
        "status": "success",
        "response": _text(final_state["messages"][-1].content),
        "thread_id": thread_id,
    }


@router.get("/chat/threads")
def list_threads(user: AuthUser = Depends(get_current_user)):
    """List the authenticated user's chat threads (newest first).
    Sidebar visibility is gated on the frontend via FEATURES.chatHistory; the data
    endpoint is always available so chat-persist (auto-resume last thread on sign-in)
    can work even when the sidebar history list is hidden."""
    return {"threads": db.list_user_threads(user.id)}


@router.post("/chat/threads/{thread_id}/claim")
def claim_thread(thread_id: str, user: AuthUser = Depends(get_current_user)):
    """Link a guest thread (user_id=NULL) to the now-signed-in user.
    Called by the frontend after sign-in so prior guest chats show up in history."""
    try:
        uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format.")
    ok = db.claim_thread(thread_id, user.id)
    return {"claimed": ok}


@router.get("/chat/threads/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """Return the message history for a thread the user owns."""
    try:
        uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format.")

    owner = await asyncio.to_thread(db.get_thread_owner, thread_id)
    if owner != user.id:
        raise HTTPException(status_code=404, detail="Thread not found.")

    if backend.app is None:
        raise HTTPException(status_code=503, detail="Agent not ready.")

    state = await backend.app.aget_state({"configurable": {"thread_id": thread_id}})
    raw_messages = state.values.get("messages", []) if state and state.values else []

    out = []
    for m in raw_messages:
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        else:
            continue  # skip ToolMessage / SystemMessage
        content = _text(m.content).strip()
        if content:
            out.append({"role": role, "content": content})

    return {"thread_id": thread_id, "messages": out}
