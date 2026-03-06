"""
gRPC transport for the Memory Client.

Uses JSON-over-gRPC to communicate with the MemoryService.
"""

import json
import logging
from typing import Any, Dict

import grpc
from grpc import aio as grpc_aio

logger = logging.getLogger(__name__)

SERVICE_NAME = "memory.v1.MemoryService"


class GrpcTransport:
    """
    gRPC transport that sends JSON-encoded requests to the memory service.

    All methods go through a single generic channel.
    """

    def __init__(self, address: str):
        self._address = address
        self._channel = None

    async def connect(self) -> None:
        """Establish gRPC channel."""
        self._channel = grpc_aio.insecure_channel(self._address)
        # Verify connectivity
        try:
            await self._channel.channel_ready()
            logger.info(f"Connected to memory service at {self._address}")
        except Exception as e:
            raise ConnectionError(f"Cannot connect to {self._address}: {e}")

    async def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            await self._channel.close()
            logger.info("gRPC channel closed")

    async def call(self, method: str, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a service method with a JSON request.

        Args:
            method: Method name (e.g., "LogEvent", "StoreEpisode")
            request: Request dict (will be JSON-serialized)

        Returns:
            Response dict (JSON-deserialized)
        """
        if not self._channel:
            raise ConnectionError("Not connected. Call connect() first.")

        full_method = f"/{SERVICE_NAME}/{method}"

        # Create unary-unary callable
        call = self._channel.unary_unary(
            full_method,
            request_serializer=lambda req: json.dumps(req).encode("utf-8"),
            response_deserializer=lambda data: json.loads(data),
        )

        try:
            response = await call(request)
            return response
        except grpc.aio.AioRpcError as e:
            logger.error(f"gRPC call {method} failed: {e.code()} - {e.details()}")
            raise
