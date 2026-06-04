# main.py
import asyncio
import logging
import uuid
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from typing import Optional
from pathlib import Path
from langchain_core.messages import HumanMessage

from backend import app as agent_app, _text
from schema import ChatResponse
from utils import parse_pdf_to_text, parse_docx_to_text
import config

PDF_MAGIC = b"%PDF"
DOCX_MAGIC = b"PK\x03\x04"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("immigroov.api")

limiter = Limiter(key_func=get_remote_address)
api = FastAPI(title="Immigroov AI Career Engine")
api.state.limiter = limiter
api.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

api.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _detect_file_type(file_bytes: bytes, filename: str) -> Optional[str]:
    # validate actual file content against the declared extension via magic bytes
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" and file_bytes[:4] == PDF_MAGIC:
        return "pdf"
    if ext == ".docx" and file_bytes[:4] == DOCX_MAGIC:
        return "docx"
    return None


@api.get("/health")
def health():
    return {"status": "ok"}


@api.post("/chat", response_model=ChatResponse)
@limiter.limit(config.RATE_LIMIT)
async def chat_handler(
    request: Request,
    message: str = Form(...),
    thread_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    try:
        uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format.")

    session_config = {"configurable": {"thread_id": thread_id}}

    resume_text = None
    if file:
        file_bytes = await file.read()
        if len(file_bytes) > config.MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"File too large. Max {config.MAX_FILE_BYTES // (1024 * 1024)} MB.")

        file_type = _detect_file_type(file_bytes, file.filename)
        if not file_type:
            raise HTTPException(status_code=415, detail="Unsupported or mismatched file type. Upload PDF or DOCX only.")

        if file_type == "pdf":
            resume_text = parse_pdf_to_text(file_bytes)
        elif file_type == "docx":
            resume_text = parse_docx_to_text(file_bytes)

    input_state = {"messages": [HumanMessage(content=message)]}
    if resume_text:
        input_state["resume_text"] = resume_text
        input_state["resume_processed"] = False

    try:
        final_state = await asyncio.wait_for(
            agent_app.ainvoke(input_state, config=session_config),
            timeout=config.AGENT_TIMEOUT_SEC,
        )
        return {
            "status": "success",
            "response": _text(final_state["messages"][-1].content),
            "thread_id": thread_id,
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Agent timed out. Please try again.")
    except Exception:
        logger.exception("Agent invocation failed", extra={"thread_id": thread_id})
        raise HTTPException(status_code=500, detail="Internal error. Please try again.")


if __name__ == "__main__":
    uvicorn.run(api, host=config.HOST, port=config.PORT)
