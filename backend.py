# backend.py
import re
from typing import Annotated, TypedDict, Optional
from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

import config
from utils import general_search, precise_search
from prompts import (
    BASE_DIRECTIVES, NO_RESUME_PROMPT, INTAKE_PROMPT,
    REPORT_PROMPT, QA_PROMPT,
    REPORT_REVIEWER_PROMPT, QA_REVIEWER_PROMPT, COMPRESSION_PROMPT,
)
from config import GROQ_API_KEY, MAIN_MODEL_NAME, REVIEW_MODEL_NAME, TEMPERATURE

_WORK_WORDS = {
    "work", "job", "jobs", "career", "careers", "employment", "employed",
    "professional", "industry", "company", "corporate", "position", "role",
    "hire", "hiring", "occupation", "workforce",
}
_STUDY_WORDS = {
    "study", "studies", "education", "university", "degree", "master",
    "masters", "msc", "phd", "doctorate", "academic", "academics",
    "research", "school", "college", "program", "programme", "course",
    "scholarship", "admission",
}
_OPT_OUT = {"just questions", "no report", "questions only", "skip report"}
_REPORT_TRIGGERS = {
    "generate report", "generate a report", "create report", "make a report",
    "give me a report", "want a report", "need a report", "show me a report",
}

_n = config.NUM_COUNTRIES
_PHASE_PROMPTS = {
    "no_resume": NO_RESUME_PROMPT,
    "intake":    INTAKE_PROMPT,
    "report":    REPORT_PROMPT.replace("{{num_countries}}", str(_n)),
    "qa":        QA_PROMPT,
}
_report_reviewer  = REPORT_REVIEWER_PROMPT.replace("{{num_countries}}", str(_n))

primary_llm = ChatGroq(model=MAIN_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)
review_llm  = ChatGroq(model=REVIEW_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


class AgentState(TypedDict):
    messages:              Annotated[list, add_messages]
    resume_text:           Optional[str]
    resume_processed:      bool
    track:                 Optional[str]
    revision_count:        int
    qa_revision_count:     int
    critique:              Optional[str]
    phase:                 Optional[str]
    preferences_collected: bool


def _log_groq_failure(e: Exception) -> None:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error", {})
        fg = err.get("failed_generation", "")
        print(f"[GROQ tool_use_failed] code={err.get('code')} msg={err.get('message')}")
        if fg:
            print(f"[GROQ failed_generation]: {fg[:1000]}")
    else:
        print(f"[GROQ error]: {e}")


def compressor_node(state: AgentState):
    raw_text = state.get("resume_text")
    if not raw_text:
        return {}
    try:
        summary = review_llm.invoke([
            SystemMessage(content=COMPRESSION_PROMPT),
            HumanMessage(content=raw_text),
        ]).content
    except Exception:
        summary = raw_text[:2000]
    return {"resume_text": summary, "resume_processed": True, "phase": "intake"}


def call_model(state: AgentState):
    messages = state["messages"]
    phase    = state.get("phase") or "no_resume"
    track    = state.get("track")
    resume   = state.get("resume_text") or "No resume provided."
    critique = state.get("critique") or "None"

    new_phase                = phase
    new_track                = track
    new_revision_count       = state.get("revision_count", 0)
    new_qa_rev               = state.get("qa_revision_count", 0)
    new_preferences_collected = state.get("preferences_collected", False)

    human_msgs      = [m for m in messages if isinstance(m, HumanMessage)]
    last_human_text = _text(human_msgs[-1].content).lower() if human_msgs else ""
    last_msg        = messages[-1] if messages else None

    # ------------------------------------------------------------------
    # phase transitions
    # ------------------------------------------------------------------
    if phase == "intake":
        words = set(last_human_text.split())
        if not new_track:
            if words & _WORK_WORDS:
                new_track = "WORK"
            elif words & _STUDY_WORDS:
                new_track = "STUDY"
        if new_track:
            new_phase = "report"
            new_preferences_collected = False

    elif phase == "report":
        if not new_preferences_collected and isinstance(last_msg, HumanMessage):
            # User responded to the preferences question
            if any(p in last_human_text for p in _OPT_OUT):
                new_phase = "qa"
            else:
                new_preferences_collected = True
                new_revision_count = 0

    elif phase == "qa":
        if any(t in last_human_text for t in _REPORT_TRIGGERS):
            if resume != "No resume provided.":
                new_phase = "report"
                new_revision_count = 0
                new_preferences_collected = False
            else:
                new_phase = "no_resume"

        if isinstance(last_msg, HumanMessage):
            new_qa_rev = 0
        elif isinstance(last_msg, ToolMessage):
            new_qa_rev = state.get("qa_revision_count", 0)
        else:
            new_qa_rev = state.get("qa_revision_count", 0) + 1

    # ------------------------------------------------------------------
    # Preferences question — code-driven, no LLM (guarantees it is always asked)
    # ------------------------------------------------------------------
    if new_phase == "report" and not new_preferences_collected:
        pref_msg = (
            f"Any preferences for your {_n}-country recommendations? "
            "(climate, salary range, work-life balance, company size, etc.) "
            "Say *skip* to proceed based on your profile alone, "
            "or *just questions* if you'd prefer to explore without a full report."
        )
        try:
            pref_response = review_llm.invoke([
                SystemMessage(content="Output ONLY the following message, word for word, with no changes:"),
                HumanMessage(content=pref_msg),
            ])
        except Exception:
            pref_response = AIMessage(content=pref_msg)
        return {
            "messages":              [pref_response],
            "phase":                 new_phase,
            "track":                 new_track,
            "revision_count":        new_revision_count,
            "qa_revision_count":     new_qa_rev,
            "preferences_collected": False,
            "critique":              None,
        }

    # ------------------------------------------------------------------
    # build prompt
    # ------------------------------------------------------------------
    phase_body = _PHASE_PROMPTS.get(new_phase, NO_RESUME_PROMPT)

    instruction = (
        BASE_DIRECTIVES
        + phase_body
        + f"\n\n[LOCKED_CONTEXT]\nPHASE: {new_phase}"
        + f"\nTRACK: {new_track or 'Not yet determined'}"
        + f"\nRESUME_SUMMARY: {resume}"
        + f"\nFEEDBACK: {critique}"
    )

    # Strip any orphaned leading ToolMessages
    history = list(messages)
    while history and isinstance(history[0], ToolMessage):
        history = history[1:]

    payload = [SystemMessage(content=instruction)] + history

    print(f"[CALL_MODEL] phase={new_phase} track={new_track} msgs={len(history)} preferences_collected={new_preferences_collected}")

    try:
        response = primary_llm.bind_tools([general_search, precise_search]).invoke(payload)
    except Exception as e:
        _log_groq_failure(e)
        response = review_llm.bind_tools([general_search, precise_search]).invoke(payload)

    tool_calls = getattr(response, "tool_calls", [])
    print(f"[CALL_MODEL] response type={'tool_call' if tool_calls else 'text'} tool_calls={[tc['name'] for tc in tool_calls]}")

    return {
        "messages":              [response],
        "phase":                 new_phase,
        "track":                 new_track,
        "revision_count":        new_revision_count,
        "qa_revision_count":     new_qa_rev,
        "preferences_collected": new_preferences_collected,
    }


def reviewer_node(state: AgentState):
    last_msg = state["messages"][-1]
    content  = _text(last_msg.content)
    phase    = state.get("phase") or "no_resume"

    print(f"[REVIEWER] phase={phase} content_len={len(content)}")

    prompt_text = QA_REVIEWER_PROMPT if phase == "qa" else _report_reviewer
    prompt = [SystemMessage(content=prompt_text), HumanMessage(content=content)]
    try:
        critique = primary_llm.invoke(prompt)
    except Exception:
        critique = review_llm.invoke(prompt)

    print(f"[REVIEWER] critique={critique.content[:200]}")

    result = {"critique": critique.content}

    if phase == "report":
        country_sections = len(re.findall(r"^###", content, re.MULTILINE))
        passed = "PASSED" in critique.content and country_sections >= config.NUM_COUNTRIES
        print(f"[REVIEWER] country_sections={country_sections} passed={passed}")
        result["revision_count"] = state.get("revision_count", 0) + 1
        if passed:
            result["phase"] = "qa"

    return result


def route_from_start(state: AgentState) -> str:
    if state.get("resume_text") and not state.get("resume_processed"):
        return "compressor"
    return "agent"


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print(f"[ROUTE] agent → tools ({[tc['name'] for tc in last_message.tool_calls]})")
        return "tools"
    phase = state.get("phase") or "no_resume"
    if phase == "report":
        if state.get("preferences_collected", False):
            print("[ROUTE] agent → reviewer (report)")
            return "reviewer"
        print("[ROUTE] agent → end (preferences not collected)")
        return "end"
    if phase == "qa":
        print("[ROUTE] agent → reviewer (qa)")
        return "reviewer"
    print(f"[ROUTE] agent → end (phase={phase})")
    return "end"


def should_revise(state: AgentState) -> str:
    critique = state.get("critique") or ""
    phase    = state.get("phase") or "no_resume"

    if "PASSED" in critique:
        print(f"[REVISE] PASSED → end")
        return "end"

    if phase == "report":
        rev = state.get("revision_count", 0)
        if rev >= config.MAX_REVISION:
            print(f"[REVISE] max revisions ({rev}) reached → end")
            return "end"
        print(f"[REVISE] revision {rev} → agent")
        return "agent"

    if phase == "qa":
        if state.get("qa_revision_count", 0) >= 1:
            print("[REVISE] qa max → end")
            return "end"
        print("[REVISE] qa revision → agent")
        return "agent"

    return "end"


workflow = StateGraph(AgentState)
workflow.add_node("compressor", compressor_node)
workflow.add_node("agent",      call_model)
workflow.add_node("tools",      ToolNode([general_search, precise_search]))
workflow.add_node("reviewer",   reviewer_node)

workflow.add_conditional_edges(START, route_from_start, {"compressor": "compressor", "agent": "agent"})
workflow.add_edge("compressor", "agent")
workflow.add_conditional_edges("agent",    should_continue, {"tools": "tools", "reviewer": "reviewer", "end": END})
workflow.add_edge("tools", "agent")
workflow.add_conditional_edges("reviewer", should_revise,   {"agent": "agent", "end": END})

app = workflow.compile(checkpointer=MemorySaver())
