"""Actually reads the web, instead of just opening a browser tab and hoping.
Search results come from DuckDuckGo's HTML endpoint -- no API key needed, and
unlike Google, it doesn't require JS rendering or aggressively block simple
scraping for light, personal-use traffic like this. Page content is extracted
with trafilatura, a purpose-built readability extractor that filters out
navigation/ads/boilerplate rather than returning a page's raw HTML soup.
"""
import logging

import requests
import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MIN_USEFUL_EXTRACT_LENGTH = 200  # shorter than this usually means extraction failed, not a short page
MAX_EXTRACT_CHARS = 3000         # keeps the LLM context (and token cost) bounded


def search_web_results(query: str, max_results: int = 5) -> list[dict]:
    """Returns [{title, url}], most relevant first. Empty list (not an error) if
    the search itself fails -- callers should treat that as 'couldn't find
    anything' rather than crash."""
    try:
        response = requests.post(
            SEARCH_URL, data={"q": query},
            headers={"User-Agent": USER_AGENT}, timeout=10,
        )
        response.raise_for_status()
    except Exception as e:
        logger.error("Web search request failed for %r: %s", query, e)
        return []

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for link in soup.select(".result__a")[:max_results]:
            url = link.get("href", "")
            title = link.get_text().strip()
            if url and title:
                results.append({"title": title, "url": url})
        return results
    except Exception as e:
        logger.error("Failed to parse search results for %r: %s", query, e)
        return []


def read_page(url: str, max_chars: int = MAX_EXTRACT_CHARS) -> str:
    """Returns the page's main readable text (article body, not navigation/ads),
    truncated to max_chars. Empty string if the page can't be fetched or nothing
    substantial could be extracted (e.g. a JS-only page, a paywall)."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded)
        if not text or len(text) < MIN_USEFUL_EXTRACT_LENGTH:
            return ""
        return text[:max_chars]
    except Exception as e:
        logger.error("Failed to read page %r: %s", url, e)
        return ""


def search_and_read(query: str, max_candidates: int = 3) -> dict | None:
    """Searches, then reads results in order until one actually yields useful
    content -- some results fail to extract (JS-heavy pages, paywalls), so this
    doesn't give up after just the top hit. Returns {title, url, text} for the
    first one that works, or None if nothing did."""
    results = search_web_results(query, max_results=max_candidates)

    for result in results:
        text = read_page(result["url"])
        if text:
            return {"title": result["title"], "url": result["url"], "text": text}

    return None
