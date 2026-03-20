"""
Workers — background job scheduling and execution.

Responsibility: Periodic memory consolidation (REM sleep cycle), event-driven
curation, and sweep publishing. Orchestrate services and storage backends on a
background schedule or in response to NATS events.

Allowed imports: services/, storage/, intelligence/, messaging/.
Must NOT import from: transport/.
"""
