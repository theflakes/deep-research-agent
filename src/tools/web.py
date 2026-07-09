import asyncio
import os
import random
import re
import threading

import httpx
from agent_framework import tool
from bs4 import BeautifulSoup

from tools.core import with_quota
from tools.fs import (
    _IN_MEMORY_FS,
    _get_safe_path,
    _get_workspace_type,
)

_searxng_client = None
_searxng_lock = threading.Lock()

_ddgs_client = None
_ddgs_lock = threading.Lock()

_SESSION_BROWSER_PROFILE = None

BLOCKED_STATUS_CODES = {401, 403, 429, 451}


def _get_proxy() -> str:
    import config as app_config

    return (
        app_config.cfg.get("settings", {})
        .get("proxy", {})
        .get("tor_proxy_url", "socks5h://tor-proxy:9050")
    )


def _get_fetch_cfg() -> dict:
    import config as app_config

    return app_config.cfg.get("settings", {}).get("fetch", {})


def _build_fetch_headers() -> dict:
    import config as app_config
    import random

    global _SESSION_BROWSER_PROFILE

    fetch_cfg = app_config.cfg.get("settings", {}).get("fetch", {})

    browser_profiles = fetch_cfg.get("browser_profiles", {})
    rotate_browser_profile = fetch_cfg.get("rotate_browser_profile", False)

    if not browser_profiles:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }

    profile_names = list(browser_profiles.keys())

    if rotate_browser_profile:
        profile_name = random.choice(profile_names)
    else:
        if _SESSION_BROWSER_PROFILE not in browser_profiles:
            _SESSION_BROWSER_PROFILE = random.choice(profile_names)
        profile_name = _SESSION_BROWSER_PROFILE

    return dict(browser_profiles[profile_name])


def _make_tor_httpx_client(**kwargs) -> httpx.Client:
    proxy_url = _get_proxy()

    try:
        return httpx.Client(proxy=proxy_url, **kwargs)
    except TypeError:
        return httpx.Client(proxies=proxy_url, **kwargs)


def get_searxng_client() -> httpx.Client:
    global _searxng_client

    with _searxng_lock:
        if _searxng_client is None:
            _searxng_client = httpx.Client(
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
            )

    return _searxng_client


def get_ddgs_client():
    global _ddgs_client

    with _ddgs_lock:
        if _ddgs_client is None:
            proxy_url = _get_proxy()
            os.environ["ALL_PROXY"] = proxy_url
            os.environ["all_proxy"] = proxy_url

            from ddgs import DDGS

            _ddgs_client = DDGS()

            try:
                _ddgs_client._get_engines("text", "auto")
                _ddgs_client._get_engines("news", "auto")
            except Exception:
                pass

    return _ddgs_client


def _sanitize_snippet(text: str) -> str:
    text = text or ""
    text = re.sub(r"<svg[\s\S]*?</svg>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(?:[\w-]+=(?:'[^']*'|\"[^\"]*\")[\s]*){3,}", "", text)
    text = re.sub(r"%3[CEce][^%\s]{10,}", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _blocked_response_message(url: str, status_code: int, reason: str = "") -> str:
    return (
        f"[FETCH BLOCKED: {status_code} {reason} for {url}. "
        "The site likely blocks Tor, datacenter IPs, or non-browser clients. "
        "Privacy preserved: no non-Tor retry was attempted. "
        "Use the search result snippet, try another source, or manually provide the page text.]"
    )


def _fetch_with_privacy(url: str) -> httpx.Response | str:
    try:
        with _make_tor_httpx_client(
            timeout=30,
            follow_redirects=True,
            headers=_build_fetch_headers(),
        ) as client:
            resp = client.get(url)

        if resp.status_code in BLOCKED_STATUS_CODES:
            return _blocked_response_message(
                url=url,
                status_code=resp.status_code,
                reason=resp.reason_phrase,
            )

        resp.raise_for_status()
        return resp

    except httpx.ProxyError as e:
        return (
            f"[FETCH FAILED: Tor SOCKS proxy error for {url}: {e}. "
            "Privacy preserved: no direct-network retry was attempted.]"
        )

    except httpx.ConnectError as e:
        return (
            f"[FETCH FAILED: connection error through Tor for {url}: {e}. "
            "Privacy preserved: no direct-network retry was attempted.]"
        )

    except httpx.TimeoutException:
        return (
            f"[FETCH FAILED: timeout fetching {url} through Tor. "
            "Privacy preserved: no direct-network retry was attempted.]"
        )

    except httpx.HTTPStatusError as e:
        return (
            f"[FETCH FAILED: HTTP {e.response.status_code} for {url}. "
            "Privacy preserved: no direct-network retry was attempted.]"
        )


@tool
@with_quota
async def fetch_url_to_workspace(
    url: str,
    filename: str,
    convert_to_md: bool = True,
) -> str:
    def _fetch():
        result = _fetch_with_privacy(url)

        if isinstance(result, str):
            return result

        resp = result

        if not convert_to_md:
            return resp.content

        content_type = resp.headers.get("content-type", "").lower()
        is_actual_pdf = resp.content[:4] == b"%PDF"
        is_pdf = is_actual_pdf or ("application/pdf" in content_type and is_actual_pdf)

        if is_pdf:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            try:
                import shutil
                import subprocess

                if shutil.which("liteparse"):
                    parse_result = subprocess.run(
                        ["liteparse", tmp_path],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if parse_result.returncode == 0 and parse_result.stdout.strip():
                        return parse_result.stdout

                try:
                    from utils.parsers import convert_to_markdown

                    md_content = convert_to_markdown(tmp_path)
                    if md_content:
                        return md_content
                except ImportError:
                    pass

                return (
                    f"[ERROR: PDF at {url} could not be parsed. "
                    f"Size: {len(resp.content)} bytes. Try a different source.]"
                )
            finally:
                os.unlink(tmp_path)

        try:
            import tempfile
            from utils.parsers import convert_to_markdown

            with tempfile.NamedTemporaryFile(
                suffix=".html",
                delete=False,
                mode="wb",
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

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "noscript"]):
            tag.extract()

        return "\n".join(
            line
            for line in (
                l.strip() for l in soup.get_text(separator="\n").splitlines()
            )
            if line
        )

    try:
        data = await asyncio.to_thread(_fetch)

        if convert_to_md and not filename.endswith(".md"):
            filename += ".md"

        path = _get_safe_path(filename)
        if not path:
            return f"Error: Invalid filename '{filename}'."

        if isinstance(data, str):
            chunk = data[:5000000]
            mode = "w"
            encoding = "utf-8"
        else:
            chunk = data[:5000000]
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
    from tools.core import check_quota

    quota_error = check_quota("web_search")
    if quota_error:
        return quota_error

    def _format_result(
        title: str,
        url: str,
        engine: str,
        snippet: str,
        source_label: str,
    ) -> str:
        return (
            f"## [{source_label}] {title}\n"
            f"**URL:** {url}\n"
            f"**Engine:** {engine}\n"
            f"**Snippet:** {snippet}\n"
        )

    def _search_searxng(
        client: httpx.Client,
        base_url: str,
        search_query: str,
        max_res: int,
        source_label: str,
        engines: str | None = None,
    ) -> list[str]:
        params = {
            "q": search_query,
            "format": "json",
        }

        if engines:
            params["engines"] = engines

        resp = client.get(
            f"{base_url}/search",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()

        data = resp.json()
        raw_results = data.get("results", [])

        formatted = []

        for item in raw_results[:max_res]:
            title = item.get("title", "")
            url = item.get("url", "")
            engine = item.get("engine", "")
            snippet = _sanitize_snippet(
                item.get("content")
                or item.get("snippet")
                or "No snippet available"
            )

            if not title and not url:
                continue

            formatted.append(
                _format_result(
                    title=title,
                    url=url,
                    engine=engine,
                    snippet=snippet,
                    source_label=source_label,
                )
            )

        return formatted

    def _do_search():
        import config as app_config

        search_cfg = app_config.cfg.get("settings", {}).get("search", {})
        provider = search_cfg.get("provider")

        if not provider:
            provider = app_config.cfg.get("settings", {}).get(
                "search_provider",
                "searxng",
            )

        result_texts = []

        if provider == "searxng":
            searxng_cfg = search_cfg.get("searxng", {})

            base_url = searxng_cfg.get(
                "base_url",
                "http://tor-searxng:8888",
            ).rstrip("/")

            standard_engines = searxng_cfg.get("standard_engines")
            enable_onion_search = searxng_cfg.get("enable_onion_search", True)
            onion_query = f"!ahmia !torch {query}"

            client = get_searxng_client()

            try:
                result_texts.extend(
                    _search_searxng(
                        client=client,
                        base_url=base_url,
                        search_query=query,
                        max_res=max_results,
                        source_label="web",
                        engines=standard_engines,
                    )
                )
            except Exception as e:
                result_texts.append(f"[SearXNG web search failed: {e}]")

            if enable_onion_search:
                try:
                    result_texts.extend(
                        _search_searxng(
                            client=client,
                            base_url=base_url,
                            search_query=onion_query,
                            max_res=max_results,
                            source_label="tor",
                            engines=None,
                        )
                    )
                except Exception as e:
                    result_texts.append(f"[SearXNG onion search failed: {e}]")

        elif provider == "duckduckgo":
            client = get_ddgs_client()

            try:
                if topic == "news":
                    search_results = client.news(query, max_results=max_results)
                    for result in search_results:
                        result_texts.append(
                            _format_result(
                                title=result.get("title", ""),
                                url=result.get("url", ""),
                                engine="duckduckgo-news",
                                snippet=_sanitize_snippet(
                                    result.get("body", "No snippet available")
                                ),
                                source_label="web",
                            )
                        )
                else:
                    search_results = client.text(query, max_results=max_results)
                    for result in search_results:
                        result_texts.append(
                            _format_result(
                                title=result.get("title", ""),
                                url=result.get("href", ""),
                                engine="duckduckgo",
                                snippet=_sanitize_snippet(
                                    result.get("body", "No snippet available")
                                ),
                                source_label="web",
                            )
                        )

            except Exception as e:
                result_texts.append(f"[DuckDuckGo search failed: {e}]")

        else:
            result_texts.append(
                f"[Unsupported search provider: {provider}. "
                f"Set settings.search.provider to searxng.]"
            )

        if not result_texts:
            return f"Found 0 result(s) for '{query}'."

        return (
            f"Found {len(result_texts)} result(s) for '{query}':\n\n"
            f"{chr(10).join(result_texts)}"
        )

    try:
        return await asyncio.to_thread(_do_search)
    except Exception as e:
        import traceback

        return f"Search failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"