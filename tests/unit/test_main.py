import uuid
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_invalid_uuid(client):
    resp = client.post("/chat", data={"message": "hello", "thread_id": "not-a-uuid"})
    assert resp.status_code == 400


def test_chat_file_too_large(client):
    large_file = b"%PDF" + b"x" * (5 * 1024 * 1024 + 1)
    resp = client.post(
        "/chat",
        data={"message": "hello", "thread_id": str(uuid.uuid4())},
        files={"file": ("resume.pdf", large_file, "application/pdf")},
    )
    assert resp.status_code == 413


def test_chat_unsupported_extension(client):
    resp = client.post(
        "/chat",
        data={"message": "hello", "thread_id": str(uuid.uuid4())},
        files={"file": ("resume.txt", b"some plain text", "text/plain")},
    )
    assert resp.status_code == 415


def test_chat_magic_bytes_mismatch(client):
    # .docx extension but PDF magic bytes inside
    resp = client.post(
        "/chat",
        data={"message": "hello", "thread_id": str(uuid.uuid4())},
        files={"file": ("resume.docx", b"%PDF-1.4 fake content", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_chat_pdf_magic_mismatch(client):
    # .pdf extension but DOCX (ZIP) magic bytes inside
    resp = client.post(
        "/chat",
        data={"message": "hello", "thread_id": str(uuid.uuid4())},
        files={"file": ("resume.pdf", b"PK\x03\x04fake zip content", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_chat_valid_message_no_file(client, mock_llm):
    resp = client.post(
        "/chat",
        data={"message": "hello", "thread_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["response"] == "Mock LLM response."
    assert "thread_id" in data


def test_chat_response_includes_thread_id(client, mock_llm):
    thread_id = str(uuid.uuid4())
    resp = client.post("/chat", data={"message": "hi", "thread_id": thread_id})
    assert resp.status_code == 200
    assert resp.json()["thread_id"] == thread_id
