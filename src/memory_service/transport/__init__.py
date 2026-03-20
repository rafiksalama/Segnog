"""
Transport — request/response adapters (REST and gRPC).

Responsibility: Accept inbound requests, validate input, delegate to
services/, and format responses. Contains zero business logic.

Allowed imports: services/ only.

Documented exceptions:
  - transport/rest/dependencies.py imports storage/ types for FastAPI
    dependency injection (store type hints). Acceptable as long as it
    does not contain business logic.
  - transport/rest/routers/smart.py imports intelligence/ directly for
    /smart/* endpoints that are thin LLM operation pass-throughs.
"""
