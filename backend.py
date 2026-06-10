# backend.py
# Agent routing and state management
import logging
import re
from typing import Annotated, TypedDict, Optional
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

import config
from utils import general_search, precise_search, retrieve_matching_mentors
from prompts import (
    BASE_DIRECTIVES, NO_RESUME_PROMPT, AWAITING_INTENT_PROMPT,
    REPORT_PROMPT, QA_PROMPT, MENTOR_PROMPT,
    REPORT_REVIEWER_PROMPT, COMPRESSION_PROMPT,
)
from config import GROQ_API_KEY, MAIN_MODEL_NAME, REVIEW_MODEL_NAME, TEMPERATURE

logger = logging.getLogger("immigroov.agent")

# Schema definition for intent routing
class IntentClassification(BaseModel):
    intent: str = Field(
        description="Classify request as: 'report', 'mentor', 'qna', or 'maintain'."
    )

# Intent prompt configuration
_n = config.NUM_COUNTRIES
_INTENT_PROMPTS = {
    "no_resume": NO_RESUME_PROMPT,
    "awaiting_intent": AWAITING_INTENT_PROMPT,
    "report": REPORT_PROMPT.replace("{{num_countries}}", str(_n)),
    "mentor": MENTOR_PROMPT,
    "qna": QA_PROMPT,
}
_report_reviewer = REPORT_REVIEWER_PROMPT.replace("{{num_countries}}", str(_n))

# Core primary and review model definitions
primary_llm = ChatGroq(model=MAIN_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)
review_llm  = ChatGroq(model=REVIEW_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)

# Content extraction helper
def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""

# Agent state definition
class AgentState(TypedDict):
    messages:          Annotated[list, add_messages]
    resume_text:       Optional[str]
    resume_processed:  bool
    user_intent:       Optional[str]
    track:             Optional[str]
    revision_count:    int
    critique:          Optional[str]

# Failure logging helper
def _log_groq_failure(e: Exception) -> None:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error", {})
        logger.error("Groq call failed code=%s msg=%s", err.get("code"), err.get("message"))
    else:
        logger.error("Groq call failed: %s", e)

# Document compression node
async def compressor_node(state: AgentState):
    raw_text = state.get("resume_text")
    if not raw_text:
        return {}
    summary = (await review_llm.ainvoke([
        SystemMessage(content=COMPRESSION_PROMPT),
        HumanMessage(content=raw_text),
    ])).content
    return {"resume_text": summary, "resume_processed": True, "user_intent": "awaiting_intent"}

# Main model invocation node
async def call_model(state: AgentState):
    messages = state["messages"]
    intent = state.get("user_intent") or "no_resume"
    track = state.get("track")
    resume = state.get("resume_text") or "No resume provided."
    critique = state.get("critique") or "None"

    human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
    last_human_text = _text(human_msgs[-1].content).lower() if human_msgs else ""
    
    new_intent = intent
    is_after_tools = bool(messages) and isinstance(messages[-1], ToolMessage)

    if last_human_text and not is_after_tools:
        try:
            structured_llm = review_llm.with_structured_output(IntentClassification)
            # current intent is injected so follow-up answers (e.g. "australia") aren't mis-routed
            classification = await structured_llm.ainvoke([
                SystemMessage(content=(
                    f"You are an intent classifier for an immigration AI. The current intent is '{intent}'. "
                    "Use 'maintain' if the user is answering a follow-up question or continuing the current flow. "
                    "Only switch to 'report', 'mentor', or 'qna' if the user is clearly requesting a new action."
                )),
                HumanMessage(content=last_human_text)
            ])
            if classification.intent in ["report", "mentor", "qna"]:
                new_intent = classification.intent
        except Exception as e:
            logger.warning("Intent classification failed, keeping previous intent: %s", e)

    if resume == "No resume provided.":
        new_intent = "no_resume"

    new_revision_count = state.get("revision_count", 0) if new_intent == intent else 0

    # resolve track from user message so LOCKED_CONTEXT reflects it before LLM evaluates Step 1/2
    if not track and last_human_text:
        if re.search(r'\bwork\b', last_human_text):
            track = "WORK"
        elif re.search(r'\bstudy\b|\bstudies\b|\bstudying\b', last_human_text):
            track = "STUDY"

    instruction = (
        BASE_DIRECTIVES
        + _INTENT_PROMPTS.get(new_intent, NO_RESUME_PROMPT)
        + f"\n\n[LOCKED_CONTEXT]\nINTENT: {new_intent}"
        + f"\nTRACK: {track or 'Unknown'}"
        + f"\nRESUME_SUMMARY: {resume}"
        + f"\nFEEDBACK: {critique}"
    )

    history = list(messages)
    
    if new_intent in ["report", "mentor"] and intent not in [new_intent, "no_resume", "awaiting_intent"]:
        human_history = [m for m in history if isinstance(m, HumanMessage)]
        if human_history:
            history = human_history[-1:]
            
    if len(history) > config.MAX_HISTORY:
        history = history[-config.MAX_HISTORY:]
            
    while history and isinstance(history[0], ToolMessage):
        history = history[1:]

    payload = [SystemMessage(content=instruction)] + history

    logger.info("call_model intent=%s track=%s tools_finished=%s history_len=%d", new_intent, track, is_after_tools, len(history))

    try:
        if new_intent in ["no_resume", "awaiting_intent"] or not _active_tools:
            response = await primary_llm.ainvoke(payload)
        else:
            response = await primary_llm.bind_tools(_active_tools).ainvoke(payload)
    except Exception as e:
        _log_groq_failure(e)
        raise

    new_track = track
    tag_match = re.search(r"<TRACK:(WORK|STUDY)>", _text(response.content))
    if tag_match:
        new_track = tag_match.group(1)
        cleaned = re.sub(r"\s*<TRACK:(?:WORK|STUDY)>\s*", "", _text(response.content)).strip()
        # carry over tool_calls — losing them causes should_continue to skip tools and return empty content
        existing_tool_calls = getattr(response, "tool_calls", None) or []
        response = AIMessage(content=cleaned, tool_calls=existing_tool_calls)

    return {
        "messages": [response],
        "user_intent": new_intent,
        "track": new_track,
        "revision_count": new_revision_count,
        "critique": None if new_intent != intent else state.get("critique"),
    }

# Response evaluation node
async def reviewer_node(state: AgentState):
    last_msg = state["messages"][-1]
    content = _text(last_msg.content)
    intent = state.get("user_intent")

    prompt = [SystemMessage(content=_report_reviewer), HumanMessage(content=content)]
    critique = await review_llm.ainvoke(prompt)

    country_sections = len(re.findall(r"^###", content, re.MULTILINE))
    passed = "PASSED" in critique.content and country_sections >= config.NUM_COUNTRIES
    
    return {
        "critique": critique.content,
        "revision_count": state.get("revision_count", 0) + 1,
        "user_intent": "qna" if passed else intent
    }

# Initialization routing edge
def route_from_start(state: AgentState) -> str:
    if state.get("resume_text") and not state.get("resume_processed"):
        return "compressor"
    return "agent"

# Processing continuity edge
def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # count tool-call rounds since the last human message to prevent retry loops
        rounds = 0
        for m in reversed(state["messages"][:-1]):
            if isinstance(m, HumanMessage):
                break
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                rounds += 1
        if rounds >= config.MAX_TOOL_ITERATIONS:
            return "end"
        return "tools"
        
    if state.get("user_intent") == "report" and "###" in _text(last_message.content):
        return "reviewer"
        
    return "end"

# Content evaluation edge
def should_revise(state: AgentState) -> str:
    critique = state.get("critique") or ""
    if "PASSED" in critique:
        return "end"

    rev = state.get("revision_count", 0)
    if rev >= config.MAX_REVISION:
        return "end"
        
    return "agent"

# Build the active tool set from feature flags.
_active_tools = []
if config.FEATURE_WEB_SEARCH_TOOL:
    _active_tools.extend([general_search, precise_search])
if config.FEATURE_MENTOR_TOOL:
    _active_tools.append(retrieve_matching_mentors)

# State graph workflow setup
workflow = StateGraph(AgentState)
workflow.add_node("compressor", compressor_node)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(_active_tools))
workflow.add_node("reviewer", reviewer_node)

workflow.add_conditional_edges(START, route_from_start, {"compressor": "compressor", "agent": "agent"})
workflow.add_edge("compressor", "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "reviewer": "reviewer", "end": END})
workflow.add_edge("tools", "agent")
workflow.add_conditional_edges("reviewer", should_revise, {"agent": "agent", "end": END})

# Persistent async checkpointing.
#   Linux (Render):  AsyncConnectionPool — concurrent chats don't serialize
#   Windows (dev):   single AsyncConnection — works around a psycopg-pool asyncio bug
# Both expose an async `close()` so shutdown is the same.
_pg_resource = None  # AsyncConnection or AsyncConnectionPool
_checkpointer: AsyncPostgresSaver | None = None
app = None  # workflow compiled with checkpointer; set by init_agent() at startup


async def init_agent() -> None:
    """Open the DB connection / pool, set up checkpoint tables, compile the graph.
    Called from FastAPI lifespan startup."""
    global _pg_resource, _checkpointer, app

    if sys.platform == "win32":
        # Windows: psycopg-pool's async pool clashes with the Selector loop in some
        # edge cases. A single long-lived connection is reliable for local dev.
        resource: AsyncConnection | AsyncConnectionPool = await AsyncConnection.connect(
            config.SUPABASE_DB_URL,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        mode = "single connection (Windows)"
    else:
        # Linux/Render: pool gives us real concurrency across chats.
        pool = AsyncConnectionPool(
            conninfo=config.SUPABASE_DB_URL,
            min_size=2,
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        resource = pool
        mode = "pool min=2 max=10 (Linux)"

    saver = AsyncPostgresSaver(resource)
    await saver.setup()  # idempotent — creates checkpoint tables on first run

    _pg_resource = resource
    _checkpointer = saver
    app = workflow.compile(checkpointer=saver)
    logger.info("Agent initialized (AsyncPostgresSaver, %s)", mode)


async def shutdown_agent() -> None:
    """Close the DB connection / pool cleanly on FastAPI shutdown."""
    global _pg_resource
    if _pg_resource is not None:
        await _pg_resource.close()
        _pg_resource = None
        logger.info("Agent shutdown (resource closed)")


if __name__ == "__main__":
    # Dev-only graph visualization. Uses MemorySaver so we don't need to open the DB pool.
    if config.DRAW_GRAPH:
        from langgraph.checkpoint.memory import MemorySaver
        _local_app = workflow.compile(checkpointer=MemorySaver())
        try:
            graph_png = _local_app.get_graph().draw_mermaid_png()
            with open("graph.png", "wb") as f:
                f.write(graph_png)
            print("Graph visualization compiled and saved as graph.png")
        except Exception:
            print("Could not generate PNG image. Printing text representation:")
            print(_local_app.get_graph().draw_mermaid())