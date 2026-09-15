import re
import requests
from urllib.parse import urlparse
from typing import Optional

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

class LinkResolver:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })

    def unshorten_url(self, url: str) -> str:
        """Resolve redirects (bit.ly, t.co, linktr.ee, etc.) to get the canonical URL."""
        if not url or not url.startswith("http"):
            return url
        try:
            resp = self.session.head(url, allow_redirects=True, timeout=8)
            return resp.url
        except Exception:
            return url

    def search_official_link(self, resource_name: str, context: str = "") -> Optional[str]:
        """
        Search DuckDuckGo for the official website or repo of the resource.
        """
        if not resource_name or resource_name.lower() in ["unknown", "none", "this tool", "this website"]:
            return None

        if not DDGS:
            return None

        query = f"{resource_name} official website {context}".strip()
        try:
            results = list(DDGS().text(query, max_results=5))
            if not results:
                results = list(DDGS().text(resource_name, max_results=5))

            for item in results:
                href = item.get("href", "")
                parsed = urlparse(href)
                domain = parsed.netloc.lower()
                if any(bad in domain for bad in ["youtube.com", "instagram.com", "tiktok.com", "facebook.com", "pinterest.com"]):
                    continue
                return href
        except Exception as e:
            print(f"[WARN] Web search failed for '{resource_name}': {e}")
            return None
