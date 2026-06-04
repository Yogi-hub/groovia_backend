# schema.py
from pydantic import BaseModel


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    status: str = "success"
