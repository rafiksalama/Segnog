"""
gRPC server setup.

Since proto compilation requires grpcio-tools and generates code,
we use a lightweight approach: gRPC servicers are implemented as
plain Python classes with a generic JSON-over-gRPC transport.

This gives us typed proto definitions for documentation/client-gen
while keeping the server implementation simple for Phase 1.

Phase 2+ will compile protos and use generated stubs.
"""

import json
import logging
from typing import Any, Dict

import grpc
from grpc import aio as grpc_aio

from .service_handler import MemoryServiceHandler

logger = logging.getLogger(__name__)

# Service name for the generic handler
SERVICE_NAME = "memory.v1.MemoryService"

# Generic request/response uses grpc.unary_unary with JSON payloads
# Method routing: "/memory.v1.MemoryService/MethodName"


class GenericServicer(grpc.GenericRpcHandler):
    """
    Generic gRPC handler that routes method calls to MemoryServiceHandler.

    Uses JSON serialization for request/response bodies.
    Each method name maps to a handler method.
    """

    def __init__(self, handler: MemoryServiceHandler):
        self._handler = handler
        self._methods = {
            # Events
            f"/{SERVICE_NAME}/LogEvent": handler.log_event,
            f"/{SERVICE_NAME}/GetRecentEvents": handler.get_recent_events,
            f"/{SERVICE_NAME}/SearchEvents": handler.search_events,
            # Episodes
            f"/{SERVICE_NAME}/StoreEpisode": handler.store_episode,
            f"/{SERVICE_NAME}/SearchEpisodes": handler.search_episodes,
            f"/{SERVICE_NAME}/LinkEpisodes": handler.link_episodes,
            # Knowledge
            f"/{SERVICE_NAME}/StoreKnowledge": handler.store_knowledge,
            f"/{SERVICE_NAME}/SearchKnowledge": handler.search_knowledge,
            f"/{SERVICE_NAME}/SearchByLabels": handler.search_by_labels,
            # Artifacts
            f"/{SERVICE_NAME}/StoreArtifacts": handler.store_artifacts,
            f"/{SERVICE_NAME}/SearchArtifacts": handler.search_artifacts,
            f"/{SERVICE_NAME}/GetArtifact": handler.get_artifact,
            f"/{SERVICE_NAME}/ListRecent": handler.list_recent_artifacts,
            f"/{SERVICE_NAME}/DeleteArtifact": handler.delete_artifact,
            # State
            f"/{SERVICE_NAME}/PersistExecutionState": handler.persist_execution_state,
            f"/{SERVICE_NAME}/GetExecutionState": handler.get_execution_state,
            f"/{SERVICE_NAME}/UpdateToolStats": handler.update_tool_stats,
            f"/{SERVICE_NAME}/GetToolStats": handler.get_tool_stats,
            f"/{SERVICE_NAME}/GetMemoryContext": handler.get_memory_context,
            # Smart Operations
            f"/{SERVICE_NAME}/ReinterpretTask": handler.reinterpret_task,
            f"/{SERVICE_NAME}/FilterMemoryResults": handler.filter_memory,
            f"/{SERVICE_NAME}/InferState": handler.infer_state_op,
            f"/{SERVICE_NAME}/SynthesizeBackground": handler.synthesize_background_op,
            f"/{SERVICE_NAME}/GenerateReflection": handler.generate_reflection_op,
            f"/{SERVICE_NAME}/ExtractKnowledge": handler.extract_knowledge_op,
            f"/{SERVICE_NAME}/ExtractArtifacts": handler.extract_artifacts_op,
            f"/{SERVICE_NAME}/CompressEvents": handler.compress_events_op,
            # Observe (unified write + read)
            f"/{SERVICE_NAME}/Observe": handler.observe,
            # Pipelines
            f"/{SERVICE_NAME}/StartupPipeline": handler.startup_pipeline,
            f"/{SERVICE_NAME}/RunCuration": handler.run_curation,
        }

    def service(self, handler_call_details):
        method = handler_call_details.method
        if method in self._methods:
            return grpc.unary_unary_rpc_method_handler(
                self._create_handler(self._methods[method]),
                request_deserializer=lambda data: json.loads(data),
                response_serializer=lambda resp: json.dumps(resp).encode("utf-8"),
            )
        return None

    def _create_handler(self, method):
        async def handler(request, context):
            try:
                return await method(request)
            except Exception as e:
                logger.error(f"gRPC handler error: {e}", exc_info=True)
                await context.abort(grpc.StatusCode.INTERNAL, str(e))
        return handler


async def create_grpc_server(
    handler: MemoryServiceHandler,
    port: int = 50051,
) -> grpc_aio.Server:
    """Create and configure the gRPC server."""
    server = grpc_aio.server()
    server.add_generic_rpc_handlers([GenericServicer(handler)])
    server.add_insecure_port(f"[::]:{port}")
    logger.info(f"gRPC server configured on port {port}")
    return server
