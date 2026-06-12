# tests/conftest.py
import io
import os
import uuid

import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage

# Required env vars — real .env wins locally; these cover bare environments (CI).
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")
os.environ.setdefault("EXA_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "fake-jwt-secret")
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")

# Rate limits would trip across a full test run (shared in-memory counter per IP).
from rate_limit import limiter  # noqa: E402

limiter.enabled = False


@pytest.fixture
def thread_id():
    return str(uuid.uuid4())


@pytest.fixture
def sample_pdf_bytes():
    """A real single-blank-page PDF that pypdf can parse (extracts to '')."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def mock_llm():
    """Patch both LLMs. Primary returns a plain answer; reviewer passes everything."""
    answer = AIMessage(content="Mock LLM response.")
    with patch("backend.primary_llm") as p, patch("backend.review_llm") as r:
        p.ainvoke = AsyncMock(return_value=answer)
        p.bind_tools.return_value.ainvoke = AsyncMock(return_value=answer)
        r.ainvoke = AsyncMock(return_value=AIMessage(content="PASSED"))
        yield p


@pytest.fixture
def mock_db():
    """No-op all Supabase writes/reads the request path touches."""
    with patch("db.upsert_chat_thread"), \
         patch("db.save_profile_summary_if_empty"), \
         patch("db.mentors_available_for_country", return_value=True), \
         patch("db.list_mentors_grouped_by_country", return_value={}):
        yield


@pytest.fixture
def agent_app(mock_db):
    """Compile the workflow with an in-memory checkpointer so /chat works
    without Postgres. Restores the previous app afterwards."""
    import backend
    from langgraph.checkpoint.memory import MemorySaver
    previous = backend.app
    backend.app = backend.workflow.compile(checkpointer=MemorySaver())
    yield backend.app
    backend.app = previous


@pytest.fixture
def client(agent_app):
    """Sync TestClient. Deliberately NOT a context manager — that would run the
    lifespan, which opens a real Postgres connection."""
    from fastapi.testclient import TestClient
    from main import api
    return TestClient(api)
