import pytest
from unittest.mock import patch, MagicMock


def test_parse_pdf_returns_string(sample_pdf_bytes):
    from utils import parse_pdf_to_text
    result = parse_pdf_to_text(sample_pdf_bytes)
    assert isinstance(result, str)


def test_parse_pdf_blank_page_is_empty(sample_pdf_bytes):
    from utils import parse_pdf_to_text
    assert parse_pdf_to_text(sample_pdf_bytes) == ""


def test_parse_docx_calls_docx2txt():
    from utils import parse_docx_to_text
    with patch("utils.docx2txt.process", return_value="Parsed resume text") as mock_proc:
        result = parse_docx_to_text(b"fake docx bytes")
        mock_proc.assert_called_once()
        assert result == "Parsed resume text"


def test_general_search_returns_error_string_on_exception():
    from utils import general_search
    with patch("utils._tavily.invoke", side_effect=RuntimeError("network error")):
        result = general_search.invoke({"query": "tech jobs in Germany"})
    assert "[SEARCH_ERROR]" in result
    assert "general_search" in result


def test_precise_search_returns_error_string_on_exception():
    from utils import precise_search
    with patch("utils.exa.search", side_effect=RuntimeError("timeout")):
        result = precise_search.invoke({"query": "Germany skilled worker visa requirements"})
    assert "[SEARCH_ERROR]" in result
    assert "precise_search" in result


def test_general_search_returns_string_on_success():
    from utils import general_search
    mock_result = [{"title": "Tech scene in Germany", "url": "https://example.com", "content": "Germany has a booming tech sector."}]
    with patch("utils._tavily.invoke", return_value=mock_result):
        result = general_search.invoke({"query": "tech scene Germany"})
    assert isinstance(result, str)
    assert len(result) > 0


def test_precise_search_returns_json_on_success():
    import json
    from utils import precise_search

    mock_result = MagicMock()
    mock_hit = MagicMock()
    mock_hit.url = "https://gov.de/visa"
    mock_hit.highlights = ["Skilled Worker Visa requires salary above €45,300."]
    mock_result.results = [mock_hit]

    with patch("utils.exa.search", return_value=mock_result):
        result = precise_search.invoke({"query": "Germany skilled worker visa salary threshold"})

    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert parsed[0]["url"] == "https://gov.de/visa"
