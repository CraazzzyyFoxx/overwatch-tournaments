"""Shared proxy helpers for outbound HTTP requests.

Usage in services::

    from shared.core.proxy import get_proxy_url
    from src.core.config import settings

    # For httpx
    async with httpx.AsyncClient(proxy=get_proxy_url(settings)) as client:
        ...

    # For discord.py
    client = discord.Client(intents=intents, proxy=get_proxy_url(settings))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.core.config import BaseServiceSettings


def get_proxy_url(settings: BaseServiceSettings) -> str | None:
    """Return the proxy URL from settings, or ``None`` if proxy is disabled."""
    return settings.proxy_url
