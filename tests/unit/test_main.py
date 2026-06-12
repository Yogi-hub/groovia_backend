import uuid

from content import MSG_ASK_FOR_RESUME


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


def test_chat_without_resume_hits_gate(client, mock_llm):
    """A message with no resume must get the deterministic resume-ask, zero LLM calls."""
    thread = str(uuid.uuid4())
    resp = client.post("/chat", data={"message": "hello", "thread_id": thread})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["response"] == MSG_ASK_FOR_RESUME
    assert data["thread_id"] == thread
    mock_llm.ainvoke.assert_not_called()
    mock_llm.bind_tools.return_value.ainvoke.assert_not_called()
