# backend.py
import re
from typing import Annotated, TypedDict, Optional
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

import config
from utils import career_market_search, neural_research_tool
from prompts import SYSTEM_PROMPT, REVIEWER_PROMPT, COMPRESSION_PROMPT
from config import GROQ_API_KEY, MAIN_MODEL_NAME, REVIEW_MODEL_NAME, TEMPERATURE

system_prompt = SYSTEM_PROMPT.format(num_countries=config.NUM_COUNTRIES)
reviewer_prompt = REVIEWER_PROMPT.format(num_countries=config.NUM_COUNTRIES)

primary_llm = ChatGroq(model=MAIN_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)
review_llm = ChatGroq(model=REVIEW_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    resume_text: Optional[str]
    resume_processed: bool
    track: Optional[str]
    revision_count: int
    critique: Optional[str]
    phase: Optional[str]


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
    return {"resume_text": summary, "resume_processed": True}


def call_model(state: AgentState):
    messages = state["messages"]
    resume_summary = state.get("resume_text", "No resume available.")
    track = state.get("track", "Not yet determined")
    critique = state.get("critique", "None")

    if track == "Not yet determined":
        human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        if human_msgs:
            text = _text(human_msgs[-1].content).lower()
            if any(w in text for w in ["study", "education", "university", "degree", "master", "phd"]):
                track = "STUDY"
            elif any(w in text for w in ["work", "job", "career", "employment", "position"]):
                track = "WORK"

    truncated = messages[-6:] if len(messages) > 6 else messages
    while truncated and isinstance(truncated[0], ToolMessage):
        truncated = truncated[1:]

    instruction = (
        system_prompt
        + f"\n\n[LOCKED_CONTEXT]\nTRACK: {track}\nRESUME_SUMMARY: {resume_summary}\nFEEDBACK: {critique}"
    )
    payload = [SystemMessage(content=instruction)] + truncated

    try:
        response = primary_llm.bind_tools([career_market_search, neural_research_tool]).invoke(payload)
    except Exception:
        response = review_llm.bind_tools([career_market_search, neural_research_tool]).invoke(payload)

    return {"messages": [response], "track": track}


def reviewer_node(state: AgentState):
    last_msg = state["messages"][-1]
    content = _text(last_msg.content)
    prompt = [SystemMessage(content=reviewer_prompt), HumanMessage(content=content)]
    try:
        critique = primary_llm.invoke(prompt)
    except Exception:
        critique = review_llm.invoke(prompt)

    country_sections = len(re.findall(r"^###", content, re.MULTILINE))
    report_passed = "PASSED" in critique.content and country_sections >= config.NUM_COUNTRIES
    new_phase = "qa" if report_passed else state.get("phase")

    return {
        "critique": critique.content,
        "revision_count": state.get("revision_count", 0) + 1,
        "phase": new_phase,
    }


def route_from_start(state: AgentState) -> str:
    if state.get("resume_text") and not state.get("resume_processed"):
        return "compressor"
    return "agent"


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    if state.get("phase") == "qa":
        return "end"
    if "###" in _text(last_message.content):
        return "reviewer"
    return "end"


def should_revise(state: AgentState) -> str:
    if state.get("revision_count", 0) >= config.MAX_REVISION or "PASSED" in state.get("critique", ""):
        return "end"
    return "agent"


workflow = StateGraph(AgentState)
workflow.add_node("compressor", compressor_node)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode([career_market_search, neural_research_tool]))
workflow.add_node("reviewer", reviewer_node)

workflow.add_conditional_edges(START, route_from_start, {"compressor": "compressor", "agent": "agent"})
workflow.add_edge("compressor", "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "reviewer": "reviewer", "end": END})
workflow.add_edge("tools", "agent")
workflow.add_conditional_edges("reviewer", should_revise, {"agent": "agent", "end": END})

app = workflow.compile(checkpointer=MemorySaver())
