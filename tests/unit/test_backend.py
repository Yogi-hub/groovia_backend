import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ---------------------------------------------------------------------------
# _text()
# ---------------------------------------------------------------------------

def test_text_plain_string():
    from backend import _text
    assert _text("hello world") == "hello world"


def test_text_empty_string():
    from backend import _text
    assert _text("") == ""


def test_text_list_of_dicts():
    from backend import _text
    assert _text([{"text": "hello"}, {"text": "world"}]) == "hello world"


def test_text_list_missing_key():
    from backend import _text
    assert _text([{"other": "ignored"}]) == ""


def test_text_non_string_non_list():
    from backend import _text
    assert _text(None) == ""
    assert _text(42) == ""


# ---------------------------------------------------------------------------
# route_from_start()
# ---------------------------------------------------------------------------

def test_route_no_resume():
    from backend import route_from_start
    state = {"messages": [], "resume_text": None, "resume_processed": False}
    assert route_from_start(state) == "agent"


def test_route_resume_unprocessed():
    from backend import route_from_start
    state = {"messages": [], "resume_text": "John Doe, Software Engineer...", "resume_processed": False}
    assert route_from_start(state) == "compressor"


def test_route_resume_already_processed():
    from backend import route_from_start
    state = {"messages": [], "resume_text": "John Doe, Software Engineer...", "resume_processed": True}
    assert route_from_start(state) == "agent"


# ---------------------------------------------------------------------------
# should_continue()
# ---------------------------------------------------------------------------

def test_should_continue_tool_calls():
    from backend import should_continue
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "general_search", "args": {"query": "x"}, "id": "call_1", "type": "tool_call"}],
    )
    assert should_continue({"messages": [msg], "phase": "report"}) == "tools"


def test_should_continue_report_with_sections():
    from backend import should_continue
    msg = AIMessage(content="### Germany\nContent here\n### Canada\nMore content")
    assert should_continue({"messages": [msg], "phase": "report"}) == "reviewer"


def test_should_continue_report_without_sections():
    from backend import should_continue
    msg = AIMessage(content="Any preferences for your recommendations?")
    assert should_continue({"messages": [msg], "phase": "report"}) == "end"


def test_should_continue_qa_phase():
    from backend import should_continue
    msg = AIMessage(content="The Skilled Worker visa requires a job offer...")
    assert should_continue({"messages": [msg], "phase": "qa"}) == "reviewer"


def test_should_continue_intake_phase():
    from backend import should_continue
    msg = AIMessage(content="You are a Software Engineer with 3 years experience.")
    assert should_continue({"messages": [msg], "phase": "intake"}) == "end"


def test_should_continue_no_resume_phase():
    from backend import should_continue
    msg = AIMessage(content="Please upload your resume.")
    assert should_continue({"messages": [msg], "phase": "no_resume"}) == "end"


# ---------------------------------------------------------------------------
# should_revise()
# ---------------------------------------------------------------------------

def _revise_state(critique, phase, revision_count=0, qa_revision_count=0):
    return {
        "critique": critique,
        "phase": phase,
        "revision_count": revision_count,
        "qa_revision_count": qa_revision_count,
    }


def test_should_revise_passed():
    from backend import should_revise
    assert should_revise(_revise_state("PASSED", "report", revision_count=1)) == "end"


def test_should_revise_passed_qa():
    from backend import should_revise
    assert should_revise(_revise_state("PASSED", "qa")) == "end"


def test_should_revise_report_under_max():
    from backend import should_revise
    assert should_revise(_revise_state("COUNT FAIL: found 3, need 4.", "report", revision_count=0)) == "agent"


def test_should_revise_report_at_max():
    from backend import should_revise
    import config
    assert should_revise(_revise_state("VISA FAIL", "report", revision_count=config.MAX_REVISION)) == "end"


def test_should_revise_qa_under_max():
    from backend import should_revise
    assert should_revise(_revise_state("CITATIONS FAIL", "qa", qa_revision_count=0)) == "agent"


def test_should_revise_qa_at_max():
    from backend import should_revise
    assert should_revise(_revise_state("CITATIONS FAIL", "qa", qa_revision_count=1)) == "end"
