import aiohttp
import os
from urllib.parse import urlsplit
from helpers import runtime, image_features

URL = "http://localhost:55510/search"


def search_url() -> str:
    configured = os.environ.get("A0_SEARXNG_URL", "").strip()
    if not configured:
        if not image_features.available("searxng"):
            raise RuntimeError("Bundled SearXNG is not included. Set A0_SEARXNG_URL to an external SearXNG /search endpoint with JSON output enabled.")
        return URL
    try:
        url = urlsplit(configured)
        port = url.port
    except ValueError:
        raise ValueError("A0_SEARXNG_URL must be a valid HTTP(S) search endpoint.") from None
    if (
        url.scheme not in ("http", "https") or not url.hostname or port == 0
        or url.username is not None or url.password is not None or url.query or url.fragment
        or any(char.isspace() for char in configured)
    ):
        raise ValueError("A0_SEARXNG_URL must be an HTTP(S) search endpoint without embedded credentials, query, or fragment.")
    return configured


async def search(query:str):
    return await runtime.call_development_function(_search, query=query)

async def _search(query:str):
    url = search_url()
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data={"q": query, "format": "json"}) as response:
            response.raise_for_status()
            return await response.json()
