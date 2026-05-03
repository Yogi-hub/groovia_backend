import uuid
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_new_session_no_resume(client, mock_llm):
    """
    A brand-new session without a resume file should succeed and return the
    no_resume phase response (LLM mocked).
    """
    resp = client.post(
        "/chat",
        data={"message": "hello", "thread_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert isinstance(data["response"], str)
    assert len(data["response"]) > 0


def test_resume_upload_runs_compressor(client, sample_pdf_bytes):
    """
    Uploading a PDF resume should trigger compressor_node (review_llm) and then
    call_model (primary_llm) for the intake phase response.
    Both are mocked; we just verify the HTTP response is 200 with a valid body.
    """
    compress_response = AIMessage(content="Software Engineer, 3 years, Python/AWS/Docker.")
    intake_response = AIMessage(
        content="You're a Software Engineer with 3 years experience. Are you looking for Work or Study opportunities?"
    )

    mock_bound = MagicMock()
    mock_bound.invoke.return_value = intake_response

    with patch("backend.review_llm.invoke", return_value=compress_response), \
         patch("backend.primary_llm.invoke", return_value=intake_response), \
         patch("backend.primary_llm.bind_tools", return_value=mock_bound):

        resp = client.post(
            "/chat",
            data={"message": "Analyze my resume.", "thread_id": str(uuid.uuid4())},
            files={"file": ("resume.pdf", sample_pdf_bytes, "application/pdf")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "Work or Study" in data["response"]


def test_track_tag_detected_and_stripped(client, sample_pdf_bytes):
    """
    When the intake LLM emits <TRACK:WORK>, the tag must be stripped from the
    response shown to the user and the session must advance to report phase.
    We verify the tag does not appear in the API response.
    """
    compress_response = AIMessage(content="Software Engineer, 3 years.")
    intake_work_response = AIMessage(
        content="Great, Work track confirmed! Any preferences for your 4-country recommendations?\n<TRACK:WORK>"
    )

    mock_bound = MagicMock()
    mock_bound.invoke.return_value = AIMessage(content="Report placeholder.")

    with patch("backend.review_llm.invoke", return_value=compress_response), \
         patch("backend.primary_llm.invoke", return_value=intake_work_response), \
         patch("backend.primary_llm.bind_tools", return_value=mock_bound):

        thread_id = str(uuid.uuid4())
        # Upload resume
        client.post(
            "/chat",
            data={"message": "Analyze my resume.", "thread_id": thread_id},
            files={"file": ("resume.pdf", sample_pdf_bytes, "application/pdf")},
        )

        # Respond with work selection (in same session / same thread_id)
        intake_resp = client.post(
            "/chat",
            data={"message": "I want to work abroad.", "thread_id": thread_id},
        )

    assert intake_resp.status_code == 200
    response_text = intake_resp.json()["response"]
    assert "<TRACK:WORK>" not in response_text
    assert "<TRACK:STUDY>" not in response_text
