import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pathlib import Path
from langchain_core.messages import HumanMessage

# Project imports
from backend import app as agent_app
from schema import ChatResponse
from utils import parse_pdf_to_text, parse_docx_to_text
import config

api = FastAPI(title="Immigroov AI Career Engine")

# Security middleware configuration
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

@api.post("/chat", response_model=ChatResponse)
async def chat_handler(
    message: str = Form(...),
    thread_id: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    # session configuration for persistent memory
    session_config = {"configurable": {"thread_id": thread_id}}
    
    # parse resume if a file is uploaded
    resume_text = None
    if file:
        file_bytes = await file.read()
        file_ext = Path(file.filename).suffix.lower()
        if file_ext == '.pdf':
            resume_text = parse_pdf_to_text(file_bytes)
        elif file_ext == '.docx':
            resume_text = parse_docx_to_text(file_bytes)

    # initialize all state keys with default values to prevent crashes
    input_state = {
        "messages": [HumanMessage(content=message)],
        "revision_count": 0,
        "resume_processed": False,
        "track": "Not yet determined",
        "search_route": "TAVILY"
    }

    # inject resume text only if it was extracted in this request
    if resume_text:
        input_state["resume_text"] = resume_text

    try:
        # run the agentic workflow asynchronously
        final_state = await agent_app.ainvoke(input_state, config=session_config)
        return {
            "status": "success",
            "response": final_state["messages"][-1].content,
            "thread_id": thread_id
        }
    except Exception as e:
        # print the exact error to the terminal for easier debugging
        print(f"# [CRITICAL ERROR] Agent crashed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(api, host="0.0.0.0", port=config.PORT)