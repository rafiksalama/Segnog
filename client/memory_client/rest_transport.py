"""
REST transport for the Memory Client.

Uses httpx for async HTTP communication with the memory service.
"""

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class RestTransport:
    """
    REST transport using httpx AsyncClient.
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._prefix = f"{self._base_url}/api/v1/memory"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self._prefix}{path}"
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self._prefix}{path}"
        response = await self._client.post(url, json=body)
        response.raise_for_status()
        return response.json()

    async def put(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self._prefix}{path}"
        response = await self._client.put(url, json=body)
        response.raise_for_status()
        return response.json()

    async def delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self._prefix}{path}"
        response = await self._client.delete(url, params=params)
        response.raise_for_status()
        return response.json()
