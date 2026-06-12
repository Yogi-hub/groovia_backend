# Unit tests for backend.py — deterministic gates, extractors, graph edges.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import config
from content import (
    MSG_ACK, MSG_ASK_FOR_RESUME, MSG_ASK_TARGET_COUNTRY,
    MSG_ASK_TRACK_AND_PREFS, MSG_RESUME_UPLOADED, NO_MENTORS_PREFIX,
)


# ── _text ─────────────────────────────────────────────────────────────────────

def test_text_plain_string():
    from backend import _text
    assert _text("hello world") == "hello world"


def test_text_list_of_dicts():
    from backend import _text
    assert _text([{"text": "hello"}, {"text": "world"}]) == "hello world"


def test_text_non_string():
    from backend import _text
    assert _text(None) == ""
    assert _text(42) == ""


# ── deterministic extractors ──────────────────────────────────────────────────

def test_is_ack_variants():
    from backend import _is_ack
    assert _is_ack("ok")
    assert _is_ack("Thanks!")
    assert _is_ack("  OKAY ")
    assert not _is_ack("ok but what about germany")
    assert not _is_ack("what is the timeframe?")


def test_classify_intent_chip_phrases():
    from backend import _classify_intent
    assert _classify_intent("i want to generate a career report.", None) == "report"
    assert _classify_intent("i want to find a mentor.", None) == "mentor"
    assert _classify_intent("i just want to ask some questions.", None) == "qna"


def test_classify_intent_loose_phrasing():
    from backend import _classify_intent
    assert _classify_intent("find me another mentor", None) == "mentor"
    assert _classify_intent("can you suggest some mentors in germany", None) == "mentor"
    assert _classify_intent("give me a new career report", None) == "report"


def test_classify_intent_generic_returns_current():
    from backend import _classify_intent
    assert _classify_intent("ok", None) is None
    assert _classify_intent("what are visa rules in canada?", None) is None
    assert _classify_intent("what is the timeframe?", "qna") == "qna"


def test_extract_country():
    from backend import _extract_country
    assert _extract_country("find mentors in russia") == "RU"
    assert _extract_country("the netherlands please") == "NL"
    assert _extract_country("what about the usa") == "US"
    assert _extract_country("no country here") is None


def test_extract_track():
    from backend import _extract_track
    assert _extract_track("no. work") == "WORK"
    assert _extract_track("study please") == "STUDY"
    assert _extract_track("germany") is None


def test_sanitize_strips_leaked_tool_tags():
    from backend import _sanitize_response
    dirty = 'Visa: Express Entry <function=precise_search>{"query": "x"} </function>. Done.'
    cleaned = _sanitize_response(dirty)
    assert "<function" not in cleaned
    assert "Express Entry" in cleaned and "Done." in cleaned


def test_last_ai_is_clarifying():
    from backend import _last_ai_is_clarifying
    gate = [AIMessage(content=MSG_ASK_TRACK_AND_PREFS), HumanMessage(content="work")]
    answer = [AIMessage(content="### CANADA\nlong report"), HumanMessage(content="ok")]
    assert _last_ai_is_clarifying(gate) is True
    assert _last_ai_is_clarifying(answer) is False
    assert _last_ai_is_clarifying([HumanMessage(content="hi")]) is False


# ── should_continue ───────────────────────────────────────────────────────────

def _state(messages, intent="qna", **kw):
    base = {
        "messages": messages, "user_intent": intent, "track": None,
        "target_country": None, "resume_text": "summary", "resume_processed": True,
        "revision_count": 0, "critique": None,
    }
    base.update(kw)
    return base


def test_should_continue_tool_calls_route_to_tools():
    from backend import should_continue
    msg = AIMessage(content="", tool_calls=[{"name": "general_search", "args": {}, "id": "1", "type": "tool_call"}])
    assert should_continue(_state([msg])) == "tools"


def test_should_continue_canned_messages_skip_reviewer():
    from backend import should_continue
    for canned in (MSG_ASK_FOR_RESUME, MSG_RESUME_UPLOADED, MSG_ASK_TARGET_COUNTRY, MSG_ACK):
        assert should_continue(_state([AIMessage(content=canned)])) == "end"


def test_should_continue_no_mentors_message_skips_reviewer():
    from backend import should_continue
    msg = AIMessage(content=f"{NO_MENTORS_PREFIX} **Russia** just yet — expanding.")
    assert should_continue(_state([msg], intent="mentor")) == "end"


def test_should_continue_real_answers_get_reviewed():
    from backend import should_continue
    assert should_continue(_state([AIMessage(content="### CANADA\n...")], intent="report")) == "reviewer"
    assert should_continue(_state([AIMessage(content="The visa requires...")], intent="qna")) == "reviewer"
    assert should_continue(_state([AIMessage(content="- **Jane** — NL expert")], intent="mentor")) == "reviewer"


# ── should_revise ─────────────────────────────────────────────────────────────

def test_should_revise_passes_end():
    from backend import should_revise
    assert should_revise(_state([], critique="PASSED", revision_count=1)) == "end"


def test_should_revise_allows_exactly_max_revision_regens():
    from backend import should_revise
    # reviewer increments first, so after the FIRST review revision_count == 1.
    assert should_revise(_state([], critique="- CITATIONS: missing", revision_count=1)) == "agent"
    assert should_revise(_state([], critique="- CITATIONS: missing", revision_count=config.MAX_REVISION + 1)) == "end"


# ── call_model gates (zero-LLM short-circuits) ───────────────────────────────

def _run_call_model(state):
    import asyncio
    from backend import call_model
    return asyncio.run(call_model(state))


@pytest.fixture
def no_llm():
    """Fail the test if any LLM call happens during a gate turn."""
    with patch("backend.primary_llm") as p, patch("backend.review_llm") as r:
        p.ainvoke = AsyncMock(side_effect=AssertionError("primary LLM called during gate"))
        p.bind_tools.return_value.ainvoke = AsyncMock(side_effect=AssertionError("primary LLM called during gate"))
        r.ainvoke = AsyncMock(side_effect=AssertionError("review LLM called during gate"))
        yield


def test_gate_no_resume(no_llm):
    out = _run_call_model(_state([HumanMessage(content="hello")], intent=None, resume_text=None, resume_processed=False))
    assert out["messages"][0].content == MSG_ASK_FOR_RESUME
    assert out["user_intent"] == "no_resume"


def test_gate_resume_uploaded_awaiting_intent(no_llm):
    out = _run_call_model(_state(
        [HumanMessage(content="[SYSTEM_RESUME_UPLOADED]")],
        intent="no_resume", resume_text="raw resume text", resume_processed=False,
    ))
    assert out["messages"][0].content == MSG_RESUME_UPLOADED
    assert out["user_intent"] == "awaiting_intent"
    assert out["resume_processed"] is False  # compression deferred


def test_gate_mentor_without_country(no_llm):
    out = _run_call_model(_state(
        [HumanMessage(content="I want to find a mentor.")],
        intent="awaiting_intent",
    ))
    assert out["messages"][0].content == MSG_ASK_TARGET_COUNTRY
    assert out["user_intent"] == "mentor"


def test_gate_report_without_track(no_llm):
    out = _run_call_model(_state(
        [HumanMessage(content="I want to generate a career report.")],
        intent="awaiting_intent",
    ))
    assert out["messages"][0].content == MSG_ASK_TRACK_AND_PREFS
    assert out["user_intent"] == "report"


def test_gate_mentor_country_without_mentors(no_llm):
    with patch("backend.db.mentors_available_for_country", return_value=False):
        out = _run_call_model(_state(
            [AIMessage(content=MSG_ASK_TARGET_COUNTRY), HumanMessage(content="russia")],
            intent="mentor",
        ))
    assert out["messages"][0].content.startswith(NO_MENTORS_PREFIX)
    assert out["target_country"] is None  # reset so next message can pick another


def test_gate_ack_after_answer(no_llm):
    out = _run_call_model(_state(
        [AIMessage(content="### CANADA\n" + "x" * 1500), HumanMessage(content="ok")],
        intent="report", track="WORK",
    ))
    assert out["messages"][0].content == MSG_ACK


def test_demotion_generic_question_after_report():
    """A non-report question after a delivered report must demote to qna."""
    response = AIMessage(content="The processing time is ~6 months. Source: https://x.y")
    with patch("backend.primary_llm") as p, patch("backend.review_llm"):
        p.bind_tools.return_value.ainvoke = AsyncMock(return_value=response)
        p.ainvoke = AsyncMock(return_value=response)
        out = _run_call_model(_state(
            [AIMessage(content="### CANADA\n" + "x" * 1500), HumanMessage(content="What are visa rules in canada?")],
            intent="report", track="WORK",
        ))
    assert out["user_intent"] == "qna"


def test_track_gate_answer_stays_report(no_llm):
    """'no. work' answering the track question must STAY report (not demote)."""
    with patch("backend.db.list_mentors_grouped_by_country", return_value={}):
        with patch("backend.primary_llm") as p, patch("backend.review_llm") as r:
            p.bind_tools.return_value.ainvoke = AsyncMock(return_value=AIMessage(content="### A\n### B\n### C"))
            p.ainvoke = AsyncMock(return_value=AIMessage(content="### A\n### B\n### C"))
            r.ainvoke = AsyncMock(return_value=AIMessage(content="Summary of resume"))
            out = _run_call_model(_state(
                [AIMessage(content=MSG_ASK_TRACK_AND_PREFS), HumanMessage(content="no. work")],
                intent="report", resume_text="raw resume", resume_processed=False,
            ))
    assert out["user_intent"] == "report"
    assert out["track"] == "WORK"
    assert out["resume_processed"] is True  # compression fired exactly at gate-pass
