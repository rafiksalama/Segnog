"""Hebbian reinforcement — background co-activation tracking.

Fires after observe searches return results. All operations are
fire-and-forget via asyncio.create_task() so the hot path is unaffected.

"Neurons that fire together, wire together" — co-retrieved episodes
strengthen their CO_ACTIVATED edge with asymptotic weight growth:
    new_weight = old_weight + lr * (1 - old_weight)
"""

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def reinforce_co_activations(
    graph,
    trigger_uuid: str,
    result_uuids: List[str],
    learning_rate: float = 0.1,
    max_pairs: int = 15,
    activation_cap: int = 1000,
) -> None:
    """Hebbian reinforcement for a single observation.

    1. Increment activation_count on the trigger episode.
    2. For each result episode (up to max_pairs):
       a. Increment activation_count on the result.
       b. MERGE a CO_ACTIVATED edge from trigger to result.
    """
    now = time.time()

    # 1. Increment trigger activation_count
    try:
        await graph.query(
            """MATCH (e:Episode {uuid: $uuid})
            SET e.activation_count = CASE
                WHEN COALESCE(e.activation_count, 0) < $cap
                THEN COALESCE(e.activation_count, 0) + 1
                ELSE $cap
            END,
            e.last_activated_at = $now""",
            params={"uuid": trigger_uuid, "cap": activation_cap, "now": now},
        )
    except Exception as e:
        logger.debug(f"Hebbian: trigger activation failed for {trigger_uuid[:8]}: {e}")

    # 2. For each co-retrieved result, update activation + CO_ACTIVATED edge
    reinforced = 0
    for result_uuid in result_uuids[:max_pairs]:
        if result_uuid == trigger_uuid:
            continue
        try:
            # Increment result activation_count
            await graph.query(
                """MATCH (e:Episode {uuid: $uuid})
                SET e.activation_count = CASE
                    WHEN COALESCE(e.activation_count, 0) < $cap
                    THEN COALESCE(e.activation_count, 0) + 1
                    ELSE $cap
                END,
                e.last_activated_at = $now""",
                params={"uuid": result_uuid, "cap": activation_cap, "now": now},
            )

            # MERGE CO_ACTIVATED edge with asymptotic weight update
            await graph.query(
                """MATCH (trigger:Episode {uuid: $trigger_uuid})
                MATCH (result:Episode {uuid: $result_uuid})
                MERGE (trigger)-[r:CO_ACTIVATED]->(result)
                ON CREATE SET
                    r.weight = $lr,
                    r.co_activation_count = 1,
                    r.created_at = $now,
                    r.last_activated_at = $now
                ON MATCH SET
                    r.weight = r.weight + $lr * (1.0 - r.weight),
                    r.co_activation_count = r.co_activation_count + 1,
                    r.last_activated_at = $now""",
                params={
                    "trigger_uuid": trigger_uuid,
                    "result_uuid": result_uuid,
                    "lr": learning_rate,
                    "now": now,
                },
            )
            reinforced += 1
        except Exception as e:
            logger.debug(
                f"Hebbian: co-activation failed for "
                f"{trigger_uuid[:8]}->{result_uuid[:8]}: {e}"
            )

    if reinforced:
        logger.info(
            f"Hebbian: trigger={trigger_uuid[:8]}, "
            f"co-activated={reinforced} episodes"
        )


async def reinforce_knowledge_activations(
    graph,
    result_uuids: List[str],
    activation_cap: int = 1000,
) -> None:
    """Increment activation_count on retrieved Knowledge nodes."""
    now = time.time()
    activated = 0
    for uuid in result_uuids:
        try:
            await graph.query(
                """MATCH (k:Knowledge {uuid: $uuid})
                SET k.activation_count = CASE
                    WHEN COALESCE(k.activation_count, 0) < $cap
                    THEN COALESCE(k.activation_count, 0) + 1
                    ELSE $cap
                END,
                k.last_activated_at = $now""",
                params={"uuid": uuid, "cap": activation_cap, "now": now},
            )
            activated += 1
        except Exception as e:
            logger.debug(f"Hebbian: knowledge activation failed for {uuid[:8]}: {e}")

    if activated:
        logger.info(f"Hebbian: activated {activated} knowledge entries")


async def get_co_activation_weights(
    graph,
    trigger_uuid: str,
    result_uuids: List[str],
) -> Dict[str, float]:
    """Fetch existing CO_ACTIVATED edge weights from trigger to results.

    Returns dict mapping result_uuid -> weight (missing = 0.0).
    """
    if not trigger_uuid or not result_uuids:
        return {}

    try:
        result = await graph.ro_query(
            """MATCH (trigger:Episode {uuid: $trigger_uuid})
               -[r:CO_ACTIVATED]->(result:Episode)
            WHERE result.uuid IN $result_uuids
            RETURN result.uuid AS uuid, r.weight AS weight""",
            params={
                "trigger_uuid": trigger_uuid,
                "result_uuids": result_uuids,
            },
        )
        weights: Dict[str, float] = {}
        if result.result_set:
            for row in result.result_set:
                weights[row[0]] = float(row[1])
        return weights
    except Exception as e:
        logger.debug(f"Hebbian: co-activation weight fetch failed: {e}")
        return {}
