# utils.py
import os
import io
import docx2txt
from pypdf import PdfReader
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from exa_py import Exa
from config import EXA_API_KEY, TAVILY_API_KEY

exa = Exa(api_key=EXA_API_KEY)

def parse_pdf_to_text(file_bytes: bytes) -> str:
    """Parses raw PDF byte streams into plain text for LLM context injection."""
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

def parse_docx_to_text(file_bytes: bytes) -> str:
    """Parses raw DOCX byte streams into plain text for LLM context injection."""
    return docx2txt.process(io.BytesIO(file_bytes))

@tool
def career_market_search(query: str) -> str:
    """
    Perform a broad web search for high-level overviews, general trends, 
    market culture, and general career advice. 
    Use this for: 'What is the tech scene like in Germany?' or 'General cost of living in Eindhoven'.
    DO NOT use this for precise government policies, visa details or salary thresholds.
    """
    search = TavilySearch(max_results=5)
    results = search.invoke({"query": query})
    return str(results)

@tool
def neural_research_tool(query: str, search_type: str = "auto"):
    """
    Advanced Neural Search for precise, factual, and real-time data.
    Use this for: 
    1. Exact visa/immigration law updates (e.g., '30% ruling changes Netherlands 2026').
    2. Specific university course syllabi, credit requirements, or tuition fees.
    3. Mandatory salary floors for Skilled Worker visas or EU Blue Cards.
    
    Arguments:
    - query: A specific, natural language question.
    - search_type: 'auto' for facts, 'deep' for analytical comparisons.
    """
    response = exa.search(
        query,
        type=search_type,
        num_results=3,
        contents={"highlights": {"max_characters": 1000}}
    )
    return [{"url": r.url, "summary": r.highlights[0] if r.highlights else "N/A"} for r in response.results]