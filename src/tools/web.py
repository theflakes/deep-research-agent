import asyncio
import os
import re
import threading

import httpx
from agent_framework import tool
from bs4 import BeautifulSoup

from tools.core import with_quota
from tools.fs import (
    _IN_MEMORY_FS,
    _get_safe_path,
    _get_workspace_dir,
    _get_workspace_type,
)

# Thread-safe SearXNG HTTP client — all traffic routes through Tor
_searxng_client = None
_searxng_lock = threading.Lock()


def _get_proxy():
    """Read Tor SOCKS5h proxy URL from config."""
    import config as app_config

    return (
        app_config.cfg.get("settings", {})
        .get("proxy", {})
        .get("tor_proxy_url", "socks5h://tor-proxy:9050")
    )


def _make_socks_transport(proxy_url):
    """Create an httpx transport that routes all traffic through a SOCKS5h proxy."""
    from httpx._transports.default import SOCKSTransport

    return SOCKSTransport(proxy_url)


def get_searxng_client():
    """Thread-safe lazy initialization of the SearXNG HTTP client.
    All traffic is routed through the Tor SOCKS5h proxy."""
    global _searxng_client
    with _searxng_lock:
        if _searxng_client is None:
            proxy_url = _get_proxy()
            _searxng_client = httpx.Client(
                timeout=30, mounts={"all://": _make_socks_transport(proxy_url)}
            )
    return _searxng_client


_ddgs_lock = threading.Lock()
_ddgs_client = None


def get_ddgs_client():
    """Thread-safe lazy initialization of the DDGS client.
    All traffic is routed through the Tor SOCKS5h proxy."""
    global _ddgs_client
    with _ddgs_lock:
        if _ddgs_client is None:
            # Set Tor proxy so ddgs (via primp) routes all traffic through it
            import os

            proxy_url = _get_proxy()
            os.environ["ALL_PROXY"] = proxy_url
            os.environ["all_proxy"] = proxy_url

            from ddgs import DDGS

            _ddgs_client = DDGS()
            # Pre-warm the internal engine cache to prevent PyO3 deadlocks
            # when multiple threads initialize primp.Client concurrently later.
            _ddgs_client._get_engines("text", "auto")
            _ddgs_client._get_engines("news", "auto")
    return _ddgs_client


@tool
@with_quota
async def fetch_url_to_workspace(
    url: str, filename: str, convert_to_md: bool = True
) -> str:
    """Fetch external web content and save it directly to the workspace. If convert_to_md is True, parses to Markdown."""

    def _fetch():
        import config as app_config

        proxy_url = (
            app_config.cfg.get("settings", {})
            .get("proxy", {})
            .get("tor_proxy_url", "socks5h://tor-proxy:9050")
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        resp = httpx.get(
            url,
            headers=headers,
            timeout=30,
            follow_redirects=True,
            transport=_make_socks_transport(proxy_url),
        )

        if not convert_to_md:
            return resp.content  # Raw bytes

        content_type = resp.headers.get("content-type", "").lower()
        # Check actual bytes — a URL might say .pdf but serve HTML (JS-gated doc viewers)
        is_actual_pdf = resp.content[:4] == b"%PDF"
        is_pdf = is_actual_pdf or ("application/pdf" in content_type and is_actual_pdf)

        if is_pdf:
            # Save to temp file, then parse locally
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            try:
                # Try liteparse first (better spatial accuracy for PDFs)
                import shutil

                if shutil.which("liteparse"):
                    import subprocess

                    result = subprocess.run(
                        ["liteparse", tmp_path],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout

                # Fallback to markitdown on local file
                try:
                    from utils.parsers import convert_to_markdown

                    md_content = convert_to_markdown(tmp_path)
                    if md_content:
                        return md_content
                except ImportError:
                    pass

                return f"[ERROR: PDF at {url} could not be parsed. Size: {len(resp.content)} bytes. Try a different source.]"
            finally:
                os.unlink(tmp_path)
        else:
            # HTML path: try markitdown on local temp file first, then BeautifulSoup fallback
            try:
                import tempfile

                from utils.parsers import convert_to_markdown

                with tempfile.NamedTemporaryFile(
                    suffix=".html", delete=False, mode="wb"
                ) as tmp:
                    tmp.write(resp.content)
                    tmp_path = tmp.name
                try:
                    md_content = convert_to_markdown(tmp_path)
                    if md_content:
                        return md_content
                finally:
                    os.unlink(tmp_path)
            except ImportError:
                pass

            # BeautifulSoup fallback for HTML
            soup = BeautifulSoup(resp.text, "html.parser")
            for script in soup(["script", "style", "nav", "footer"]):
                script.extract()
            return "\n".join(
                line
                for line in (
                    l.strip() for l in soup.get_text(separator="\n").splitlines()
                )
                if line
            )

    try:
        data = await asyncio.to_thread(_fetch)

        # Explicitly tag markdown files
        if convert_to_md and not filename.endswith(".md"):
            filename += ".md"

        path = _get_safe_path(filename)
        if not path:
            return f"Error: Invalid filename '{filename}'."

        if isinstance(data, str):
            chunk = data[:5000000]  # Allow larger sizes for markdown text (up to 5MB)
            mode = "w"
            encoding = "utf-8"
        else:
            chunk = data[:5000000]  # Cap raw binary at 5MB
            mode = "wb"
            encoding = None

        if _get_workspace_type() == "disk":
            parent_dir = os.path.dirname(path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            if encoding:
                with open(path, mode, encoding=encoding) as f:
                    f.write(chunk)
            else:
                with open(path, mode) as f:
                    f.write(chunk)
            return f"Fetched URL successfully to '{filename}' on disk."
        else:
            _IN_MEMORY_FS[path] = chunk
            return f"Fetched URL successfully to '{filename}' in memory."
    except Exception as e:
        import traceback

        return f"Failed: {e}\n\nTraceback:\n{traceback.format_exc()}"


@tool
async def web_search(
    query: str,
    max_results: int = 5,
    topic: str = "general",
) -> str:
    """Search the web for information on a given query.

    Searches both regular web engines AND Tor .onion sites (Ahmia/Torch).
    Each call performs TWO SearXNG API searches and combines the results.

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return per source (default: 5)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

    Returns:
        Formatted search results with titles, URLs, snippets, and source tags ([web] / [tor])
    """
    from tools.core import check_quota

    quota_error = check_quota("web_search")
    if quota_error:
        return quota_error

    def _sanitize_snippet(text: str) -> str:
        """Strip CSS, SVG, and HTML artifacts from search snippets."""
        text = re.sub(r"<svg[\s\S]*?</svg>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"(?:[\w-]+=(?:'[^']*'|\"[^\"]*\")[\s]*){3,}", "", text)
        text = re.sub(r"%3[CEce][^%\s]{10,}", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def _search_searxng(client, base_url, search_query, engines, max_res):
        """Search via SearXNG API and return parsed results.

        Returns a list of dicts with keys: title, url, snippet, source_tag, engine
        """
        results = []
        try:
            params = {
                "q": search_query,
                "format": "json",
                "engines": engines,
            }
            resp = client.get(f"{base_url}/search", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for r in data.get("results", []):
                url = r.get("url", "")
                title = r.get("title", "")
                snippet = _sanitize_snippet(
                    r.get("content", r.get("snippet", "No snippet available"))
                )
                results.append(
                    {
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "engine": r.get("engine", ""),
                    }
                )
                if len(results) >= max_res:
                    break
        except Exception as e:
            results.append(
                {
                    "title": f"[SearXNG error ({engines}): {e}]",
                    "url": "",
                    "snippet": "",
                    "engine": "",
                }
            )
        return results

    def _do_search():
        import config as app_config

        # Determine search provider
        search_cfg = app_config.cfg.get("settings", {}).get("search", {})
        provider = search_cfg.get("provider", "searxng")

        # Fallback to legacy search_provider key if provider not set in new config
        if not search_cfg:
            provider = app_config.cfg.get("settings", {}).get(
                "search_provider", "duckduckgo"
            )

        result_texts = []

        if provider == "searxng":
            searxng_cfg = search_cfg.get("searxng", {})
            base_url = searxng_cfg.get("base_url", "http://tor-searxng:8888")
            tor_engines = searxng_cfg.get("tor_engines", "ahmia,torch")
            standard_engines = searxng_cfg.get(
                "standard_engines", "google,duckduckgo,bing,brave,wikipedia"
            )

            client = get_searxng_client()

            # --- Search 1: Standard web engines ---
            web_results = _search_searxng(
                client, base_url, query, standard_engines, max_results
            )
            for r in web_results:
                result_texts.append(
                    f"## [web] {r['title']}\n"
                    f"**URL:** {r['url']}\n"
                    f"**Engine:** {r['engine']}\n"
                    f"**Snippet:** {r['snippet']}\n"
                )

            # --- Search 2: Tor .onion engines (!ahmia !torch) ---
            tor_results = _search_searxng(
                client, base_url, f"!ahmia !torch {query}", tor_engines, max_results
            )
            for r in tor_results:
                result_texts.append(
                    f"## [tor] {r['title']}\n"
                    f"**URL:** {r['url']}\n"
                    f"**Engine:** {r['engine']}\n"
                    f"**Snippet:** {r['snippet']}\n"
                )

        elif provider == "duckduckgo" or provider not in (
            "duckduckgo",
            "tavily",
            "searxng",
        ):
            # Default/fallback: DuckDuckGo (free, no API key required)
            from ddgs import DDGS

            client = get_ddgs_client()

            if topic == "news":
                search_results = client.news(query, max_results=max_results)
                for result in search_results:
                    url = result.get("url", "")
                    title = result.get("title", "")
                    snippet = _sanitize_snippet(
                        result.get("body", "No snippet available")
                    )
                    result_texts.append(
                        f"## {title}\n**URL:** {url}\n**Snippet:** {snippet}\n"
                    )
            else:
                search_results = client.text(query, max_results=max_results)
                for result in search_results:
                    url = result.get("href", "")
                    title = result.get("title", "")
                    snippet = _sanitize_snippet(
                        result.get("body", "No snippet available")
                    )
                    result_texts.append(
                        f"## {title}\n**URL:** {url}\n**Snippet:** {snippet}\n"
                    )
        elif provider == "tavily":
            pass  # Removed Tavily placeholder to avoid undefined get_tavily_client() error in scaffold

        return f"🔍 Found {len(result_texts)} result(s) for '{query}':\n\n{chr(10).join(result_texts)}"

    try:
        return await asyncio.to_thread(_do_search)
    except Exception as e:
        import traceback

        return f"Search failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
