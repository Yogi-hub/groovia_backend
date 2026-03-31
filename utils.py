import os
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_community.tools.tavily_search import TavilySearchResults
from exa_py import Exa

# Ensure environment variables are loaded before any clients initialize
load_dotenv()

SUPPORTED_FORMATS = ['.pdf', '.docx']
SEARCH_RESULTS_K = 5

# Initialize Exa client
# Passing the key explicitly is safer for custom deployments
exa = Exa(api_key=os.getenv("EXA_API_KEY"))

@tool
def extract_resume_tool(file_path: str) -> str:
    """
    Parses a local resume file (PDF or DOCX) and extracts all text content.
    MANDATORY: Use this as the very first step if the user provides a file path 
    to understand their technical skills, education, and experience.
    """
    _, file_extension = os.path.splitext(file_path)
    file_extension = file_extension.lower()

    if file_extension == '.pdf':
        loader = PyPDFLoader(file_path)
    elif file_extension == '.docx':
        loader = Docx2txtLoader(file_path)
    else:
        return f"Error: Unsupported format. Supported: {SUPPORTED_FORMATS}"

    docs = loader.load()
    return "\n".join([doc.page_content for doc in docs])

@tool
def career_market_search(query: str) -> str:
    """
    Broad web search for high-level country overviews, general 2026 economic trends, 
    and general career advice. 
    Use this for: 'What is the tech scene like in Germany?' or 'General cost of living'.
    Returns: A string containing a list of search snippets and URLs.
    """
    search = TavilySearchResults(max_results=SEARCH_RESULTS_K)
    results = search.invoke({"query": query})
    return str(results)

@tool
def neural_research_tool(query: str, search_type: str = "auto"):
    """
    Advanced Neural Search for precise, factual, and real-time 2026 data.
    Use this for: 
    1. Exact visa/immigration law updates (e.g., '30% ruling changes March 2026').
    2. Specific university course syllabi or credit requirements.
    3. Deep-dive comparisons between niche technical roles or specific cities.
    
    Arguments:
    - query: A natural language question (e.g., 'Latest Dutch HSM salary thresholds 2026').
    - search_type: Use 'auto' for facts, 'deep' for complex analytical comparisons.
    
    Returns: A list of objects containing URLs and token-efficient content highlights.
    """
    response = exa.search(
        query,
        type=search_type,
        use_autoprompt=True,
        num_results=3,
        contents={"highlights": {"max_characters": 1000}}
    )
    
    formatted_results = []
    for r in response.results:
        formatted_results.append({
            "url": r.url,
            "published_date": getattr(r, 'published_date', 'N/A'),
            "summary": r.highlights[0] if r.highlights else "No highlight available."
        })
    
    return formatted_results