# schemas.py
from pydantic import BaseModel
from typing import Optional


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    status: str = "success"
