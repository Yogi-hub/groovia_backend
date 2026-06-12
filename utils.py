# utils.py
import io
import json
import logging

import docx2txt
from pypdf import PdfReader
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from exa_py import Exa
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import db
from config import (
    EXA_API_KEY, CAL_BASE_URL,
    TAVILY_MAX_RESULTS, EXA_NUM_RESULTS, EXA_HIGHLIGHT_MAX_CHARS,
)

logger = logging.getLogger("immigroov.tools")

exa = Exa(api_key=EXA_API_KEY)
_tavily = TavilySearch(max_results=TAVILY_MAX_RESULTS)

# Transient 5xx/network blips from search providers are common. Retry twice with backoff.
_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)


@_retry
def _tavily_invoke(query: str):
    return _tavily.invoke({"query": query})


@_retry
def _exa_search(query: str):
    return exa.search(
        query,
        type="neural",
        num_results=EXA_NUM_RESULTS,
        contents={"highlights": {"max_characters": EXA_HIGHLIGHT_MAX_CHARS}},
    )


def parse_pdf_to_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])


def parse_docx_to_text(file_bytes: bytes) -> str:
    return docx2txt.process(io.BytesIO(file_bytes))


@tool
def general_search(query: str) -> str:
    """
    Broad web search for country overviews, culture, cost of living, general market trends, pros and cons.
    Use for: 'Tech scene in Germany', 'Cost of living in Amsterdam', 'Issues faced by expats in USA'.
    Do NOT use for visa rules, salary thresholds, or government policies.
    """
    logger.info("tool=general_search (Tavily) query=%r", query)
    try:
        return str(_tavily_invoke(query))
    except Exception as e:
        return f"[SEARCH_ERROR] general_search failed: {e}"


@tool
def precise_search(query: str) -> str:
    """
    Precise neural search for accurate legal, visa, salary, and policy data.
    Use for: exact visa names, salary thresholds, immigration law updates, university syllabi.
    Argument: query — a specific natural language question about visa, law, salary, or policy.
    """
    logger.info("tool=precise_search (Exa) query=%r", query)
    try:
        response = _exa_search(query)
        results = [
            {"url": r.url, "summary": r.highlights[0] if getattr(r, "highlights", None) else "N/A"}
            for r in response.results
        ]
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        return f"[SEARCH_ERROR] precise_search failed: {e}"


@tool
def retrieve_matching_mentors(target_country: str, profile_keyword: str = "") -> str:
    """Retrieves mentors from the database for a specific country.

    target_country MUST be the standard 2-letter ISO 3166-1 alpha-2 code (e.g. 'US' for America/USA,
    'GB' for UK, 'AU' for Australia, 'NL' for Netherlands).
    Optionally accepts a broad profile_keyword (e.g. 'Software', 'AI', 'Finance') to filter by headline.
    """
    logger.info("tool=retrieve_matching_mentors country=%r keyword=%r", target_country, profile_keyword)
    try:
        rows = db.list_active_mentors(
            country_code=target_country,
            profile_keyword=profile_keyword or None,
            limit=20,
        )
        results = [
            {
                "name": r["display_name"],
                "headline": r.get("headline") or "",
                "booking_url": f"{CAL_BASE_URL}/{r['booking_url']}" if r.get("booking_url") else "No booking link available",
            }
            for r in rows
        ]
        return json.dumps(results)
    except Exception as e:
        logger.exception("Mentor retrieval failed")
        return f"[TOOL_ERROR] Mentor retrieval failed: {e}"
