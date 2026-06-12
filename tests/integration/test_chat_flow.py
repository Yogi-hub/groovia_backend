# End-to-end /chat journey against the current gate-driven flow.
# All LLMs and DB calls mocked; LangGraph state is real (MemorySaver).
import uuid

from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage

from content import (
    MSG_ACK, MSG_ASK_TARGET_COUNTRY, MSG_RESUME_UPLOADED,
)

MENTOR_ANSWER = (
    "- **Maya Singh** — Software Engineer (NL Blue Card)\n"
    "  [Book a 1-on-1 Session](https://cal.com/maya/30min)\n"
    "To explore other mentors, please visit the [Mentor Directory](http://localhost:3000/mentors)."
)


def test_full_guest_mentor_journey(client, mock_llm):
    """upload resume → pick mentor chip → give country → get mentors → say ok.
    Verifies gates fire deterministically and thread state persists between calls."""
    thread = str(uuid.uuid4())
    mock_llm.bind_tools.return_value.ainvoke = AsyncMock(return_value=AIMessage(content=MENTOR_ANSWER))

    # Turn 1: resume upload → canned MSG_RESUME_UPLOADED, no LLM.
    with patch("routers.chat.parse_pdf_to_text", return_value="John Doe — AI engineer, 3 yrs"):
        r1 = client.post(
            "/chat",
            data={"message": "[SYSTEM_RESUME_UPLOADED]", "thread_id": thread},
            files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert r1.status_code == 200
    assert r1.json()["response"] == MSG_RESUME_UPLOADED

    # Turn 2: mentor chip → asks for country (still no LLM).
    r2 = client.post("/chat", data={"message": "I want to find a mentor.", "thread_id": thread})
    assert r2.json()["response"] == MSG_ASK_TARGET_COUNTRY

    # Turn 3: country given → LLM produces mentor list, reviewer passes.
    r3 = client.post("/chat", data={"message": "netherlands", "thread_id": thread})
    assert "Maya Singh" in r3.json()["response"]

    # Turn 4: bare ack → canned reply, not a regenerated answer.
    r4 = client.post("/chat", data={"message": "ok", "thread_id": thread})
    assert r4.json()["response"] == MSG_ACK


def test_no_mentor_country_resets_cleanly(client, mock_llm):
    """Country without mentors → polite notice; next country retries the flow."""
    thread = str(uuid.uuid4())
    mock_llm.bind_tools.return_value.ainvoke = AsyncMock(return_value=AIMessage(content=MENTOR_ANSWER))

    with patch("routers.chat.parse_pdf_to_text", return_value="John Doe — AI engineer"):
        client.post(
            "/chat",
            data={"message": "[SYSTEM_RESUME_UPLOADED]", "thread_id": thread},
            files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    client.post("/chat", data={"message": "I want to find a mentor.", "thread_id": thread})

    with patch("db.mentors_available_for_country", return_value=False):
        r = client.post("/chat", data={"message": "russia", "thread_id": thread})
    assert "don't have mentors" in r.json()["response"]

    # Next message names a country with mentors → normal flow resumes.
    r2 = client.post("/chat", data={"message": "netherlands", "thread_id": thread})
    assert "Maya Singh" in r2.json()["response"]
