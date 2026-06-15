# Agent routing: deterministic gates run before any LLM call, then primary LLM + reviewer loop.
import logging
import re
import sys
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

import asyncio

import config
import db
from config import GROQ_API_KEY, MAIN_MODEL_NAME, REVIEW_MODEL_NAME, TEMPERATURE
from content import (
    INTENT_MENTOR_PHRASE, INTENT_QNA_PHRASE, INTENT_REPORT_PHRASE,
    MSG_ACK, MSG_ASK_FOR_QUESTION, MSG_ASK_FOR_RESUME, MSG_ASK_TARGET_COUNTRY,
    MSG_ASK_TRACK_AND_PREFS, MSG_RESUME_UPLOADED, NO_MENTORS_PREFIX,
    msg_no_mentors_for_country,
)
from prompts import (
    BASE_DIRECTIVES, COMPRESSION_PROMPT, MENTOR_PROMPT, MENTOR_REVIEWER_PROMPT,
    QA_PROMPT, QA_REVIEWER_PROMPT, REPORT_PROMPT, REPORT_REVIEWER_PROMPT,
)
from utils import general_search, precise_search, retrieve_matching_mentors

logger = logging.getLogger("immigroov.agent")

_n = config.NUM_COUNTRIES
_INTENT_PROMPTS = {
    "report": REPORT_PROMPT.replace("{{num_countries}}", str(_n)),
    "mentor": MENTOR_PROMPT,
    "qna":    QA_PROMPT,
}
_report_reviewer = REPORT_REVIEWER_PROMPT.replace("{{num_countries}}", str(_n))

# Primary handles user-facing answers + tool calls; review handles audits/compression.
primary_llm = ChatGroq(model=MAIN_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)
review_llm  = ChatGroq(model=REVIEW_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)


# ─── State ─────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages:          Annotated[list, add_messages]
    resume_text:       Optional[str]
    resume_processed:  bool
    user_intent:       Optional[str]   # no_resume | awaiting_intent | report | mentor | qna
    track:             Optional[str]   # WORK | STUDY
    target_country:    Optional[str]   # ISO-2 code (DE, NL, US, ...)
    revision_count:    int
    critique:          Optional[str]


# ─── Deterministic extractors (no LLM) ─────────────────────────────────────────

# Country alias → ISO-2. Reverse lookup (ISO → display name) is _COUNTRY_DISPLAY below.
_COUNTRY_ALIASES: dict[str, str] = {
    # Europe
    "germany": "DE", "deutschland": "DE",
    "netherlands": "NL", "holland": "NL", "the netherlands": "NL",
    "united kingdom": "GB", "uk": "GB", "britain": "GB", "england": "GB", "great britain": "GB",
    "ireland": "IE",
    "france": "FR",
    "spain": "ES",
    "portugal": "PT",
    "italy": "IT",
    "switzerland": "CH",
    "belgium": "BE",
    "austria": "AT",
    "luxembourg": "LU",
    "sweden": "SE",
    "denmark": "DK",
    "norway": "NO",
    "finland": "FI",
    "iceland": "IS",
    "poland": "PL",
    "czech republic": "CZ", "czechia": "CZ",
    "slovakia": "SK",
    "hungary": "HU",
    "romania": "RO",
    "bulgaria": "BG",
    "greece": "GR",
    "croatia": "HR",
    "slovenia": "SI",
    "serbia": "RS",
    "estonia": "EE",
    "latvia": "LV",
    "lithuania": "LT",
    "malta": "MT",
    "cyprus": "CY",
    "ukraine": "UA",
    "belarus": "BY",
    "russia": "RU", "russian federation": "RU",
    "moldova": "MD",
    # North America
    "united states": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US", "america": "US",
    "canada": "CA",
    "mexico": "MX",
    # Latin America
    "brazil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE",
    "venezuela": "VE",
    "uruguay": "UY",
    "ecuador": "EC",
    "bolivia": "BO",
    "paraguay": "PY",
    "costa rica": "CR",
    "panama": "PA",
    "dominican republic": "DO",
    "cuba": "CU",
    # Oceania
    "australia": "AU",
    "new zealand": "NZ",
    # Asia
    "japan": "JP",
    "south korea": "KR", "republic of korea": "KR", "korea": "KR",
    "china": "CN",
    "hong kong": "HK",
    "taiwan": "TW",
    "singapore": "SG",
    "malaysia": "MY",
    "thailand": "TH",
    "vietnam": "VN",
    "indonesia": "ID",
    "philippines": "PH",
    "india": "IN",
    "pakistan": "PK",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "nepal": "NP",
    "kazakhstan": "KZ",
    "uzbekistan": "UZ",
    "mongolia": "MN",
    # Middle East
    "uae": "AE", "united arab emirates": "AE", "dubai": "AE", "abu dhabi": "AE",
    "qatar": "QA",
    "saudi arabia": "SA", "ksa": "SA",
    "kuwait": "KW",
    "bahrain": "BH",
    "oman": "OM",
    "israel": "IL",
    "jordan": "JO",
    "lebanon": "LB",
    "turkey": "TR", "türkiye": "TR", "turkiye": "TR",
    "iran": "IR",
    # Africa
    "south africa": "ZA",
    "nigeria": "NG",
    "kenya": "KE",
    "ghana": "GH",
    "egypt": "EG",
    "morocco": "MA",
    "tunisia": "TN",
    "algeria": "DZ",
    "ethiopia": "ET",
    "uganda": "UG",
    "tanzania": "TZ",
    "rwanda": "RW",
    "senegal": "SN",
    "zimbabwe": "ZW",
    "zambia": "ZM",
}

# ISO-2 → preferred display name for user-facing messages.
_COUNTRY_DISPLAY: dict[str, str] = {
    "DE": "Germany", "NL": "the Netherlands", "GB": "the United Kingdom",
    "IE": "Ireland", "FR": "France", "ES": "Spain", "PT": "Portugal",
    "IT": "Italy", "CH": "Switzerland", "BE": "Belgium", "AT": "Austria",
    "LU": "Luxembourg", "SE": "Sweden", "DK": "Denmark", "NO": "Norway",
    "FI": "Finland", "IS": "Iceland", "PL": "Poland", "CZ": "the Czech Republic",
    "SK": "Slovakia", "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria",
    "GR": "Greece", "HR": "Croatia", "SI": "Slovenia", "RS": "Serbia",
    "EE": "Estonia", "LV": "Latvia", "LT": "Lithuania", "MT": "Malta",
    "CY": "Cyprus", "UA": "Ukraine", "BY": "Belarus", "RU": "Russia",
    "MD": "Moldova",
    "US": "the United States", "CA": "Canada", "MX": "Mexico",
    "BR": "Brazil", "AR": "Argentina", "CL": "Chile", "CO": "Colombia",
    "PE": "Peru", "VE": "Venezuela", "UY": "Uruguay", "EC": "Ecuador",
    "BO": "Bolivia", "PY": "Paraguay", "CR": "Costa Rica", "PA": "Panama",
    "DO": "the Dominican Republic", "CU": "Cuba",
    "AU": "Australia", "NZ": "New Zealand",
    "JP": "Japan", "KR": "South Korea", "CN": "China", "HK": "Hong Kong",
    "TW": "Taiwan", "SG": "Singapore", "MY": "Malaysia", "TH": "Thailand",
    "VN": "Vietnam", "ID": "Indonesia", "PH": "the Philippines", "IN": "India",
    "PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka", "NP": "Nepal",
    "KZ": "Kazakhstan", "UZ": "Uzbekistan", "MN": "Mongolia",
    "AE": "the UAE", "QA": "Qatar", "SA": "Saudi Arabia", "KW": "Kuwait",
    "BH": "Bahrain", "OM": "Oman", "IL": "Israel", "JO": "Jordan",
    "LB": "Lebanon", "TR": "Türkiye", "IR": "Iran",
    "ZA": "South Africa", "NG": "Nigeria", "KE": "Kenya", "GH": "Ghana",
    "EG": "Egypt", "MA": "Morocco", "TN": "Tunisia", "DZ": "Algeria",
    "ET": "Ethiopia", "UG": "Uganda", "TZ": "Tanzania", "RW": "Rwanda",
    "SN": "Senegal", "ZW": "Zimbabwe", "ZM": "Zambia",
}
# Sort longest first so "new zealand" wins over "zealand", "the netherlands" over "netherlands", etc.
_COUNTRY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), iso)
    for alias, iso in sorted(_COUNTRY_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True)
]

_TRACK_WORK_RE  = re.compile(r"\bwork\b", re.IGNORECASE)
_TRACK_STUDY_RE = re.compile(r"\bstud(y|ies|ying)\b", re.IGNORECASE)

# Matches repeat requests like "find me another mentor" / "give me a new career report".
_MENTOR_REQ_RE = re.compile(
    r"\b(?:find|show|recommend|get|need|want|book|connect|suggest)\b(?:\s+\w+){0,3}?\s+mentors?\b",
    re.IGNORECASE,
)
_REPORT_REQ_RE = re.compile(
    r"\b(?:generate|create|give|build|make|need|want|regenerate|new|another)\b(?:\s+\w+){0,3}?\s+(?:career\s+)?reports?\b",
    re.IGNORECASE,
)


def _extract_country(text: str) -> Optional[str]:
    for pattern, iso in _COUNTRY_PATTERNS:
        if pattern.search(text):
            return iso
    return None


def _extract_track(text: str) -> Optional[str]:
    if _TRACK_WORK_RE.search(text):
        return "WORK"
    if _TRACK_STUDY_RE.search(text):
        return "STUDY"
    return None


def _classify_intent(text: str, current: Optional[str]) -> Optional[str]:
    """Map a user message to an intent. Returns None to keep current."""
    t = text.lower()
    if INTENT_REPORT_PHRASE in t or _REPORT_REQ_RE.search(t):
        return "report"
    if INTENT_MENTOR_PHRASE in t or _MENTOR_REQ_RE.search(t):
        return "mentor"
    if INTENT_QNA_PHRASE in t:
        return "qna"
    return current


# If the last assistant message is one of these, the reply belongs to the in-progress flow.
_CLARIFYING_PROMPTS = frozenset({
    MSG_ASK_FOR_RESUME, MSG_RESUME_UPLOADED,
    MSG_ASK_FOR_QUESTION, MSG_ASK_TARGET_COUNTRY, MSG_ASK_TRACK_AND_PREFS,
})

# Canned messages (gates + acks) skip the reviewer — they aren't LLM answers.
_NO_REVIEW_MSGS = _CLARIFYING_PROMPTS | {MSG_ACK}

# Bare acknowledgements get a canned reply instead of re-entering the LLM.
_ACK_WORDS = frozenset({
    "ok", "okay", "k", "kk", "thanks", "thank you", "thanks a lot",
    "thank you so much", "great", "cool", "nice", "got it", "perfect",
    "good", "fine", "sure", "alright", "awesome", "understood", "noted",
})


def _is_ack(text: str) -> bool:
    normalized = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    return normalized in _ACK_WORDS


def _last_ai_is_clarifying(messages: list) -> bool:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return _text(m.content).strip() in _CLARIFYING_PROMPTS
    return False


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


# Llama sometimes emits the tool call as leaked text instead of structured tool_calls.
_LEAKED_TOOL_TAG_RE = re.compile(
    r"\s*<\s*function\s*=\s*\w+\s*>\s*\{.*?\}\s*<\s*/\s*function\s*>\s*",
    re.IGNORECASE | re.DOTALL,
)
_LEAKED_TOOL_INVOKE_RE = re.compile(
    r"\s*<\|tool_call_begin\|>.*?<\|tool_call_end\|>\s*", re.IGNORECASE | re.DOTALL
)


def _sanitize_response(text: str) -> str:
    cleaned = _LEAKED_TOOL_TAG_RE.sub(" ", text)
    cleaned = _LEAKED_TOOL_INVOKE_RE.sub(" ", cleaned)
    # Collapse double spaces left behind by the stripping.
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _log_groq_failure(e: Exception) -> None:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error", {})
        logger.error("Groq call failed code=%s msg=%s", err.get("code"), err.get("message"))
    else:
        logger.error("Groq call failed: %s", e)


# ─── Nodes ─────────────────────────────────────────────────────────────────────

async def call_model(state: AgentState):
    messages = state["messages"]
    intent = state.get("user_intent") or "no_resume"
    track = state.get("track")
    target_country = state.get("target_country")
    raw_resume = state.get("resume_text")
    resume_processed = state.get("resume_processed", False)

    human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
    last_human_text = _text(human_msgs[-1].content) if human_msgs else ""
    last_lower = last_human_text.lower()
    is_new_turn = bool(messages) and isinstance(messages[-1], HumanMessage)
    is_after_tools = bool(messages) and isinstance(messages[-1], ToolMessage)

    new_intent = intent
    new_track = track
    new_target_country = target_country

    # Step 1: deterministic state extraction from the latest user message.
    if is_new_turn and last_lower:
        extracted_track = _extract_track(last_lower)
        if extracted_track:
            new_track = extracted_track
        extracted_country = _extract_country(last_lower)
        if extracted_country:
            new_target_country = extracted_country

        reclassified = _classify_intent(last_lower, None)
        if reclassified:
            new_intent = reclassified
        elif intent in ("report", "mentor") and not _last_ai_is_clarifying(messages):
            # A generic follow-up is a question, not a regeneration request, except a bare country name after a mentor list.
            if intent == "mentor" and extracted_country and len(last_lower.split()) <= 4 and "?" not in last_lower:
                new_intent = "mentor"
            else:
                new_intent = "qna"

    # Resume gate trumps everything.
    if not raw_resume:
        new_intent = "no_resume"
    elif new_intent == "no_resume":
        # Resume just arrived; waiting for the user to pick an intent.
        new_intent = "awaiting_intent"

    # Step 2: short-circuit clarification (zero LLM calls).
    short_circuit: Optional[str] = None
    reset_country = False  # If true, clear target_country in returned state.
    if not is_after_tools:
        if new_intent == "no_resume":
            short_circuit = MSG_ASK_FOR_RESUME
        elif new_intent in (None, "awaiting_intent"):
            short_circuit = MSG_RESUME_UPLOADED
            new_intent = "awaiting_intent"
        elif new_intent == "qna" and last_lower.strip() == INTENT_QNA_PHRASE:
            # User clicked the "Ask a Question" chip — no real question yet.
            short_circuit = MSG_ASK_FOR_QUESTION
        elif is_new_turn and _is_ack(last_lower) and not _last_ai_is_clarifying(messages):
            short_circuit = MSG_ACK
        elif new_intent == "mentor" and not new_target_country:
            short_circuit = MSG_ASK_TARGET_COUNTRY
        elif new_intent == "mentor" and new_target_country:
            # Pre-check the DB so we never hallucinate mentors for a country with none.
            try:
                has_mentors = await asyncio.to_thread(
                    db.mentors_available_for_country, new_target_country
                )
            except Exception:
                logger.exception("mentor availability check failed; falling through to LLM")
                has_mentors = True  # fail-open — let the LLM + tool path handle it
            if not has_mentors:
                display = _COUNTRY_DISPLAY.get(new_target_country, new_target_country)
                short_circuit = msg_no_mentors_for_country(display)
                # Clear target_country so the next user message can pick a different one
                # without being trapped by the stale value.
                reset_country = True
        elif new_intent == "report" and not new_track:
            short_circuit = MSG_ASK_TRACK_AND_PREFS

    if short_circuit:
        logger.info("short-circuit intent=%s msg=%r", new_intent, short_circuit[:40])
        return {
            "messages": [AIMessage(content=short_circuit)],
            "user_intent": new_intent,
            "track": new_track,
            "target_country": None if reset_country else new_target_country,
            "resume_text": raw_resume,
            "resume_processed": resume_processed,
            "revision_count": 0,
            "critique": None,
        }

    # Step 3: gates passed — compress the resume on the first real LLM turn.
    if not resume_processed and raw_resume:
        logger.info("compressing resume (intent=%s)", new_intent)
        try:
            summary = (await review_llm.ainvoke([
                SystemMessage(content=COMPRESSION_PROMPT),
                HumanMessage(content=raw_resume),
            ])).content
            raw_resume = summary
        except Exception as e:
            _log_groq_failure(e)
            # If compression fails, fall back to the raw resume so we still proceed.
        resume_processed = True

    # Step 4: revision bookkeeping. A truly new user turn or any state change resets the counter.
    state_changed = (
        is_new_turn
        or new_intent != intent
        or new_track != track
        or new_target_country != target_country
    )
    if state_changed:
        new_revision_count = 0
        critique_to_use = None
    else:
        new_revision_count = state.get("revision_count", 0)
        critique_to_use = state.get("critique")

    # Step 5: prompt assembly. Pre-fetch mentor inventory for report flow so the LLM has real names + URLs.
    mentor_inventory = ""
    if new_intent == "report":
        try:
            grouped = await asyncio.to_thread(db.list_mentors_grouped_by_country)
            if grouped:
                lines = []
                for code in sorted(grouped):
                    display = _COUNTRY_DISPLAY.get(code, code)
                    lines.append(f"{code} ({display}):")
                    for m in grouped[code]:
                        lines.append(f"  - {m['name']} — {m['headline']} — {m['booking_url']}")
                mentor_inventory = "\n".join(lines)
        except Exception:
            logger.exception("mentor inventory fetch failed; report will fall back to directory link")

    instruction = (
        BASE_DIRECTIVES + "\n\n"
        + _INTENT_PROMPTS.get(new_intent, QA_PROMPT)
        + "\n\n[LOCKED_CONTEXT]"
        + f"\nINTENT: {new_intent}"
        + f"\nTRACK: {new_track or 'Unknown'}"
        + f"\nTARGET_COUNTRY: {new_target_country or 'Unknown'}"
        + f"\nRESUME_SUMMARY: {raw_resume}"
        + f"\nFEEDBACK: {critique_to_use or 'None'}"
        + (f"\nMENTOR_INVENTORY:\n{mentor_inventory}" if mentor_inventory else "")
    )

    # Step 6: history pruning.
    history = list(messages)
    # When switching INTO report/mentor from a different real intent, drop noise from prior flow.
    if new_intent in ("report", "mentor") and intent not in (new_intent, "no_resume", "awaiting_intent", None):
        human_history = [m for m in history if isinstance(m, HumanMessage)]
        if human_history:
            history = human_history[-1:]
    if len(history) > config.MAX_HISTORY:
        history = history[-config.MAX_HISTORY:]
    while history and isinstance(history[0], ToolMessage):
        history = history[1:]
    # During a revision, strip the failed assistant turn so the model regenerates.
    if new_revision_count > 0:
        while history and isinstance(history[-1], AIMessage):
            history = history[:-1]

    # Q&A turns: stub out long prior report/mentor answers to avoid context bleed.
    if new_intent == "qna":
        slimmed = []
        for m in history:
            text = _text(m.content)
            if isinstance(m, AIMessage) and len(text) > 1200 and not getattr(m, "tool_calls", None):
                m = AIMessage(content=text[:400] + "\n…[rest of the earlier detailed answer omitted — already shown to the user]")
            slimmed.append(m)
        history = slimmed

    payload = [SystemMessage(content=instruction)] + history

    logger.info(
        "call_model intent=%s track=%s country=%s after_tools=%s rev=%d history=%d",
        new_intent, new_track, new_target_country, is_after_tools, new_revision_count, len(history),
    )

    try:
        if _active_tools:
            response = await primary_llm.bind_tools(_active_tools).ainvoke(payload)
        else:
            response = await primary_llm.ainvoke(payload)
    except Exception as e:
        _log_groq_failure(e)
        raise

    # Defensive: strip stray <TRACK:WORK> tags if the model emits them.
    raw_text = _text(response.content)
    tag_match = re.search(r"<TRACK:(WORK|STUDY)>", raw_text)
    if tag_match and not new_track:
        new_track = tag_match.group(1)
    cleaned = re.sub(r"\s*<TRACK:(?:WORK|STUDY)>\s*", "", raw_text)
    # Strip any leaked <function=...> "fake tool call" text Llama sometimes emits.
    cleaned = _sanitize_response(cleaned)
    if cleaned != raw_text:
        existing_tool_calls = getattr(response, "tool_calls", None) or []
        response = AIMessage(content=cleaned, tool_calls=existing_tool_calls)

    return {
        "messages": [response],
        "user_intent": new_intent,
        "track": new_track,
        "target_country": new_target_country,
        "resume_text": raw_resume,
        "resume_processed": resume_processed,
        "revision_count": new_revision_count,
        "critique": critique_to_use,
    }


async def reviewer_node(state: AgentState):
    last_msg = state["messages"][-1]
    content = _text(last_msg.content)
    intent = state.get("user_intent")

    if intent == "report":
        prompt_content = _report_reviewer
    elif intent == "mentor":
        prompt_content = MENTOR_REVIEWER_PROMPT
    else:
        prompt_content = QA_REVIEWER_PROMPT

    critique = await review_llm.ainvoke([
        SystemMessage(content=prompt_content),
        HumanMessage(content=content),
    ])

    passed = "PASSED" in critique.content.upper()
    if intent == "report":
        country_sections = len(re.findall(r"^###", content, re.MULTILINE))
        passed = passed and country_sections >= config.NUM_COUNTRIES

    new_count = state.get("revision_count", 0) + 1
    if passed:
        return {"critique": "PASSED", "revision_count": new_count}

    critique_text = critique.content
    if "PASSED" in critique_text.upper():
        # The LLM reviewer said PASSED but the structural count failed — replace
        # with a concrete failure so should_revise doesn't read a false pass.
        critique_text = f"- STRUCTURE: report must contain exactly {config.NUM_COUNTRIES} '### ' country sections."
    return {"critique": critique_text, "revision_count": new_count}


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        rounds = 0
        for m in reversed(state["messages"][:-1]):
            if isinstance(m, HumanMessage):
                break
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                rounds += 1
        if rounds >= config.MAX_TOOL_ITERATIONS:
            return "end"
        return "tools"

    intent = state.get("user_intent")
    content = _text(last_message.content).strip()

    # Canned messages (gates, acks, no-mentors notice) aren't LLM answers — skip review.
    if content in _NO_REVIEW_MSGS or content.startswith(NO_MENTORS_PREFIX):
        return "end"

    # Every real assistant answer goes through review.
    if intent in ("report", "mentor", "qna"):
        return "reviewer"

    return "end"


def should_revise(state: AgentState) -> str:
    critique = (state.get("critique") or "").upper()
    if "PASSED" in critique:
        return "end"
    # revision_count was already incremented by reviewer_node, so ">" (not ">=")
    # allows exactly MAX_REVISION regeneration passes.
    if state.get("revision_count", 0) > config.MAX_REVISION:
        return "end"
    return "agent"


# ─── Tool activation + graph wiring ───────────────────────────────────────────

_active_tools = []
if config.FEATURE_WEB_SEARCH_TOOL:
    _active_tools.extend([general_search, precise_search])
if config.FEATURE_MENTOR_TOOL:
    _active_tools.append(retrieve_matching_mentors)

workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(_active_tools))
workflow.add_node("reviewer", reviewer_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "reviewer": "reviewer", "end": END})
workflow.add_edge("tools", "agent")
workflow.add_conditional_edges("reviewer", should_revise, {"agent": "agent", "end": END})


# ─── Async checkpointer lifecycle ─────────────────────────────────────────────
# Linux uses AsyncConnectionPool; Windows uses a single AsyncConnection (psycopg-pool asyncio bug).

_pg_resource: AsyncConnection | AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None
app = None  # workflow compiled with checkpointer; set by init_agent() at startup


async def init_agent() -> None:
    global _pg_resource, _checkpointer, app

    if sys.platform == "win32":
        resource: AsyncConnection | AsyncConnectionPool = await AsyncConnection.connect(
            config.SUPABASE_DB_URL,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        mode = "single connection (Windows)"
    else:
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
    global _pg_resource
    if _pg_resource is not None:
        await _pg_resource.close()
        _pg_resource = None
        logger.info("Agent shutdown (resource closed)")


if __name__ == "__main__":
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
