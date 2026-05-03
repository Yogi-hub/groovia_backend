import io
import os
import uuid

import pytest
from unittest.mock import MagicMock, patch

# Must be set before any app module is imported — config.py calls sys.exit if missing.
# In CI these are real secrets injected via GitHub Actions env; locally they're dummies
# (all LLM/API calls are mocked in tests, so the actual key values don't matter).
os.environ.setdefault("GROQ_API_KEY", "test-dummy-key")
os.environ.setdefault("TAVILY_API_KEY", "test-dummy-key")
os.environ.setdefault("EXA_API_KEY", "test-dummy-key")

from langchain_core.messages import AIMessage  # noqa: E402 — must come after env setup
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from main import api
    with TestClient(api) as c:
        yield c


@pytest.fixture
def sample_pdf_bytes():
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def mock_llm():
    """
    Patches primary_llm and review_llm in backend so no real Groq API calls are made.
    Covers both direct .invoke() and .bind_tools().invoke() call paths.
    """
    mock_response = AIMessage(content="Mock LLM response.")
    mock_bound = MagicMock()
    mock_bound.invoke.return_value = mock_response

    with patch("backend.primary_llm.invoke", return_value=mock_response), \
         patch("backend.primary_llm.bind_tools", return_value=mock_bound), \
         patch("backend.review_llm.invoke", return_value=mock_response):
        yield mock_response
