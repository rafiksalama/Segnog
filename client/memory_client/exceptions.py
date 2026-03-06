"""Memory client exceptions."""


class MemoryClientError(Exception):
    """Base exception for memory client errors."""


class ConnectionError(MemoryClientError):
    """Failed to connect to memory service."""


class NotImplementedError(MemoryClientError):
    """Operation not yet implemented on the server."""
