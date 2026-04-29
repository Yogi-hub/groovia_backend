# utils.py
import io
import json
import docx2txt
from pypdf import PdfReader
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from exa_py import Exa
from config import EXA_API_KEY

exa = Exa(api_key=EXA_API_KEY)
_tavily = TavilySearch(max_results=5)


def parse_pdf_to_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])


def parse_docx_to_text(file_bytes: bytes) -> str:
    return docx2txt.process(io.BytesIO(file_bytes))


@tool
def career_market_search(query: str) -> str:
    """
    Broad web search for country overviews, culture, cost of living, general market trends, pros and cons.
    Use for: 'Tech scene in Germany', 'Cost of living in Amsterdam', 'Issues faced by expats in USA'.
    Do NOT use for visa rules, salary thresholds, or government policies.
    """
    try:
        results = _tavily.invoke({"query": query})
        return str(results)
    except Exception as e:
        return f"[SEARCH_ERROR] career_market_search failed: {e}"


@tool
def neural_research_tool(query: str, search_type: str = "neural") -> str:
    """
    Precise neural search for legal, visa, salary, and policy data.
    Use for: exact visa names, salary thresholds, immigration law updates, university syllabi.
    Arguments:
    - query: specific natural language question.
    - search_type: 'neural' (default) for facts, 'keyword' for exact-match lookups.
    """
    try:
        response = exa.search(
            query,
            type=search_type,
            num_results=3,
            contents={"highlights": {"max_characters": 1000}},
        )
        results = [
            {"url": r.url, "summary": r.highlights[0] if getattr(r, "highlights", None) else "N/A"}
            for r in response.results
        ]
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        return f"[SEARCH_ERROR] neural_research_tool failed: {e}"
