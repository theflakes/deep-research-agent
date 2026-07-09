import os
import shutil
import subprocess

try:
    import httpx

    _httpx_available = True
except ImportError:
    _httpx_available = False

try:
    from markitdown import MarkItDown

    _markitdown_available = True
except ImportError:
    import logging

    logging.warning("markitdown not installed. Markdown conversion will be limited.")
    _markitdown_available = False

# Lazy init for MarkItDown so we can pass a Tor-routed httpx client
_markitdown_instance = None


def _get_markitdown():
    """Lazily create MarkItDown with a Tor-routed httpx client."""
    global _markitdown_instance
    if _markitdown_instance is not None:
        return _markitdown_instance

    if not _markitdown_available:
        return None

    try:
        import config as app_config

        proxy_url = (
            app_config.cfg.get("settings", {})
            .get("proxy", {})
            .get("tor_proxy_url", "socks5h://tor-proxy:9050")
        )
        if _httpx_available:
            httpx_client = httpx.Client(
                timeout=30,
                mounts={"all://": httpx.SOCKSTransport(proxy_url)},
            )
            _markitdown_instance = MarkItDown(httpx_client=httpx_client)
        else:
            _markitdown_instance = MarkItDown()
    except Exception:
        import logging

        logging.exception("Failed to initialize MarkItDown with Tor proxy")
        _markitdown_instance = None

    return _markitdown_instance


def convert_to_markdown(url_or_filepath: str) -> str:
    """
    Attempts to fetch and convert a URL or raw file to markdown using markitdown.
    All network requests go through the Tor SOCKS5h proxy.
    Returns None if markitdown is unavailable or fails, allowing graceful fallback.
    """
    if not _markitdown_available:
        return None

    md = _get_markitdown()
    if md is None:
        return None

    try:
        result = md.convert(url_or_filepath)
        if result and result.text_content:
            return result.text_content
        return None
    except Exception:
        return None


def extract_advanced_pdf(filepath: str) -> str:
    """
    Utilizes Liteparse for layout comprehension of complex PDFs.
    Requires system-level installation: `npm install -g @llamaindex/liteparse`.
    """
    if not shutil.which("liteparse"):
        raise EnvironmentError(
            "liteparse is missing. Run: npm install -g @llamaindex/liteparse"
        )

    result = subprocess.run(
        ["liteparse", filepath], capture_output=True, text=True, check=True
    )
    return result.stdout
