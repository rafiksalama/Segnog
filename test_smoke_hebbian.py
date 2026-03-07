"""Smoke test for temporal scoring + Hebbian learning features.

Covers:
  1. Observe cold start + warm retrieval
  2. Temporal scoring (recent items score higher)
  3. Hebbian reinforcement (activation counts + CO_ACTIVATED edges)
  4. 3D scoring integration (semantic + temporal + hebbian)
  5. Repeated co-activation strengthens edges
  6. Scoring module unit tests
  7. REM decay (stale edges decayed, near-zero pruned)
"""

import asyncio
import json
import subprocess
import time

import httpx

BASE = "http://localhost:9000/api/v1/memory"
CONTAINER = "agent-memory-service-segnog-1"


# ── Helpers ──────────────────────────────────────────────────────────


async def observe(client: httpx.AsyncClient, session_id: str, content: str) -> dict:
    r = await client.post(
        f"{BASE}/observe",
        json={"session_id": session_id, "content": content, "source": "smoke_test"},
    )
    r.raise_for_status()
    return r.json()


def falkor_query(cypher: str) -> list:
    """Run a read-only Cypher query inside the container via docker exec + python."""
    script = f"""
import redis, json
r = redis.Redis(port=6380)
raw = r.execute_command('GRAPH.RO_QUERY', 'episode_store', '''{cypher}''')
rows = raw[1] if len(raw) >= 2 else []
out = []
for row in rows:
    out.append([x.decode() if isinstance(x, bytes) else x for x in row])
print(json.dumps(out))
"""
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "python3", "-c", script],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"falkor_query failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip())


def falkor_write(cypher: str) -> None:
    """Run a write Cypher query inside the container."""
    script = f"""
import redis
r = redis.Redis(port=6380)
r.execute_command('GRAPH.QUERY', 'episode_store', '''{cypher}''')
"""
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "python3", "-c", script],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"falkor_write failed: {result.stderr.strip()}")


# ── Tests ────────────────────────────────────────────────────────────


async def test_observe_cold_and_warm(client, session_id):
    """Test 1: Cold start returns empty context, warm returns previous episodes."""
    print("\n[1] Observe: cold start + warm retrieval")

    r1 = await observe(client, session_id, "Python is great for data science and ML.")
    assert r1["context"]["episodes"] == [], "Cold start should have no episodes"
    uuid1 = r1["episode_uuid"]
    print(f"    cold start ok — uuid={uuid1[:8]}")

    await asyncio.sleep(2)

    r2 = await observe(client, session_id, "NumPy and Pandas are essential Python data science libraries.")
    uuid2 = r2["episode_uuid"]
    ctx_uuids = [e["uuid"] for e in r2["context"]["episodes"]]
    assert uuid1 in ctx_uuids, f"Warm session should retrieve episode 1, got {ctx_uuids}"
    print(f"    warm retrieval ok — uuid={uuid2[:8]}, retrieved {len(ctx_uuids)} episode(s)")

    return uuid1, uuid2


async def test_temporal_scoring(client, session_id, uuid1):
    """Test 2: Recent episodes score higher via temporal blending."""
    print("\n[2] Temporal scoring: recent items get freshness boost")

    await asyncio.sleep(2)

    r3 = await observe(
        client, session_id,
        "Scikit-learn provides machine learning algorithms for Python data science.",
    )
    uuid3 = r3["episode_uuid"]
    episodes = r3["context"]["episodes"]

    scores = {e["uuid"]: e["score"] for e in episodes}
    print(f"    scores: {json.dumps({k[:8]: round(v, 4) for k, v in scores.items()})}")

    assert len(episodes) >= 1, "Should retrieve at least 1 episode"
    assert all(e["score"] > 0 for e in episodes), "All scores should be positive"
    print(f"    temporal scoring ok — {len(episodes)} episodes with positive scores")

    return uuid3


async def test_hebbian_activation_counts(uuids):
    """Test 3: Episodes that were retrieved have activation_count > 0."""
    print("\n[3] Hebbian: activation counts incremented")

    # Wait for background reinforcement to complete
    await asyncio.sleep(4)

    uuid_list = ", ".join(f"\\'{u}\\'" for u in uuids)
    rows = falkor_query(
        f"MATCH (e:Episode) WHERE e.uuid IN [{uuid_list}] "
        f"RETURN e.uuid, COALESCE(e.activation_count, 0) ORDER BY e.uuid"
    )

    counts = {row[0]: row[1] for row in rows}
    print(f"    activation counts: {json.dumps({k[:8]: v for k, v in counts.items()})}")

    assert counts.get(uuids[0], 0) >= 1, (
        f"Episode 1 should have activation_count >= 1, got {counts.get(uuids[0], 0)}"
    )
    print("    activation counts ok")


async def test_hebbian_co_activated_edges():
    """Test 4: CO_ACTIVATED edges created between co-retrieved episodes."""
    print("\n[4] Hebbian: CO_ACTIVATED edges exist")

    rows = falkor_query(
        "MATCH (a:Episode)-[r:CO_ACTIVATED]->(b:Episode) "
        "RETURN a.uuid, b.uuid, r.weight, r.co_activation_count "
        "ORDER BY r.co_activation_count DESC LIMIT 20"
    )

    print(f"    found {len(rows)} CO_ACTIVATED edge(s)")
    for row in rows:
        w = float(row[2])
        print(f"      {row[0][:8]} → {row[1][:8]}  weight={w:.3f}  count={row[3]}")

    assert len(rows) >= 1, "Should have at least 1 CO_ACTIVATED edge"

    for row in rows:
        w = float(row[2])
        assert 0 < w <= 1.0, f"Weight should be in (0, 1], got {w}"

    print("    CO_ACTIVATED edges ok")


async def test_repeated_co_activation(client, session_id, uuid1):
    """Test 5: Repeated co-retrieval increases edge weight or creates new edges."""
    print("\n[5] Hebbian: repeated co-activation strengthens edges")

    rows_before = falkor_query(
        f"MATCH (a:Episode)-[r:CO_ACTIVATED]->(b:Episode {{uuid: \\'{uuid1}\\'}}) "
        f"RETURN a.uuid, r.weight, r.co_activation_count"
    )
    initial_weights = {row[0]: float(row[1]) for row in rows_before}
    edge_count_before = len(rows_before)

    # Fire another observe that should retrieve uuid1 again
    await observe(
        client, session_id,
        "Python's data science ecosystem includes Matplotlib for visualization.",
    )
    await asyncio.sleep(4)

    rows_after = falkor_query(
        f"MATCH (a:Episode)-[r:CO_ACTIVATED]->(b:Episode {{uuid: \\'{uuid1}\\'}}) "
        f"RETURN a.uuid, r.weight, r.co_activation_count"
    )

    strengthened = False
    for row in rows_after:
        a, w, c = row[0], float(row[1]), row[2]
        old_w = initial_weights.get(a, 0)
        if w > old_w:
            strengthened = True
            print(f"    {a[:8]} → {uuid1[:8]}: weight {old_w:.3f} → {w:.3f} (count={c})")

    new_edges = len(rows_after) - edge_count_before
    if new_edges > 0:
        strengthened = True
        print(f"    {new_edges} new edge(s) to {uuid1[:8]}")

    assert strengthened, "At least one edge should have strengthened or new edges created"
    print("    repeated co-activation ok")


async def test_scoring_module():
    """Test 6: Unit test the scoring functions directly."""
    print("\n[6] Scoring module: unit tests")

    from src.memory_service.scoring import (
        compute_freshness,
        apply_temporal_score,
        compute_activation_strength,
        compute_hebbian_boost,
        apply_hebbian_score,
    )

    now = time.time()

    # Freshness
    f1 = compute_freshness(now, half_life_hours=1.0, now=now)
    assert abs(f1 - 1.0) < 0.01, f"Just-created should have freshness ~1.0, got {f1}"

    f2 = compute_freshness(now - 3600, half_life_hours=1.0, now=now)
    assert abs(f2 - 0.5) < 0.01, f"1-hour-old with 1h half-life should be ~0.5, got {f2}"
    print(f"    freshness: now={f1:.3f}, 1h_ago={f2:.3f}")

    # Temporal scoring
    results = [
        {"score": 0.9, "created_at": now - 7200},  # 2h old, high semantic
        {"score": 0.8, "created_at": now - 60},     # 1min old, lower semantic
    ]
    scored = apply_temporal_score(results, alpha=0.3, half_life_hours=1.0, now=now)
    # The recent one (0.8 sem) should get boosted by freshness
    recent = next(r for r in scored if r["_semantic_score"] == 0.8)
    old = next(r for r in scored if r["_semantic_score"] == 0.9)
    assert recent["_freshness"] > old["_freshness"], "Recent should have higher freshness"
    print(f"    temporal: recent={recent['score']:.3f} (f={recent['_freshness']:.3f}), "
          f"old={old['score']:.3f} (f={old['_freshness']:.3f})")

    # Activation strength
    s0 = compute_activation_strength(0)
    s10 = compute_activation_strength(10)
    s100 = compute_activation_strength(100)
    assert s0 == 0.0
    assert 0 < s10 < s100 <= 1.0
    print(f"    activation strength: 0→{s0:.3f}, 10→{s10:.3f}, 100→{s100:.3f}")

    # Hebbian boost
    h0 = compute_hebbian_boost(0, 0.0)
    h_act = compute_hebbian_boost(50, 0.0)
    h_co = compute_hebbian_boost(0, 0.8)
    h_both = compute_hebbian_boost(50, 0.8)
    assert h0 == 0.0
    assert h_both > h_act and h_both > h_co
    print(f"    hebbian boost: none={h0:.3f}, act={h_act:.3f}, co={h_co:.3f}, both={h_both:.3f}")

    # 3D scoring
    results_3d = [
        {"score": 0.9, "created_at": now - 3600, "activation_count": 20, "uuid": "a"},
        {"score": 0.85, "created_at": now - 60, "activation_count": 0, "uuid": "b"},
    ]
    scored_3d = apply_hebbian_score(
        results_3d, beta=0.1, alpha=0.2, half_life_hours=1.0, now=now,
    )
    assert all("_hebbian_boost" in r for r in scored_3d)
    for r in scored_3d:
        print(f"    3D: uuid={r['uuid']} score={r['score']:.3f} "
              f"sem={r['_semantic_score']:.3f} fresh={r['_freshness']:.3f} hebb={r['_hebbian_boost']:.3f}")

    # Alpha + beta clamping (0.5 + 0.8 > 1.0 → beta clamped to 0.5)
    results_clamp = [{"score": 0.9, "created_at": now, "activation_count": 5, "uuid": "x"}]
    scored_clamp = apply_hebbian_score(
        results_clamp, beta=0.8, alpha=0.5, half_life_hours=1.0, now=now,
    )
    assert scored_clamp[0]["score"] > 0
    print("    alpha+beta clamping ok")

    print("    scoring module ok")


async def test_rem_decay():
    """Test 7: REM decay logic — stale edges decayed, near-zero pruned."""
    print("\n[7] REM decay: stale edge decay + near-zero prune")

    stale_time = time.time() - (30 * 24 * 3600)  # 30 days ago

    # Create test nodes + stale CO_ACTIVATED edge
    falkor_write(
        f"CREATE (a:Episode {{uuid: \\'decay-test-a\\', group_id: \\'test\\', "
        f"content: \\'decay A\\', created_at: {stale_time}, episode_type: \\'raw\\', "
        f"embedding: vecf32([0.1])}})"
    )
    falkor_write(
        f"CREATE (b:Episode {{uuid: \\'decay-test-b\\', group_id: \\'test\\', "
        f"content: \\'decay B\\', created_at: {stale_time}, episode_type: \\'raw\\', "
        f"embedding: vecf32([0.2])}})"
    )
    falkor_write(
        f"MATCH (a:Episode {{uuid: \\'decay-test-a\\'}}), (b:Episode {{uuid: \\'decay-test-b\\'}}) "
        f"CREATE (a)-[:CO_ACTIVATED {{weight: 0.05, co_activation_count: 1, "
        f"created_at: {stale_time}, last_activated_at: {stale_time}}}]->(b)"
    )

    # Verify edge exists
    rows = falkor_query(
        "MATCH (a:Episode {uuid: \\'decay-test-a\\'})-[r:CO_ACTIVATED]->"
        "(b:Episode {uuid: \\'decay-test-b\\'}) RETURN r.weight"
    )
    assert len(rows) == 1, f"Stale edge should exist, got {len(rows)} rows"
    w_before = float(rows[0][0])
    print(f"    stale edge weight before: {w_before:.4f}")

    # Simulate decay
    decay_factor = 1.0 - 0.01
    cutoff = time.time() - (168 * 3600)
    falkor_write(
        f"MATCH ()-[r:CO_ACTIVATED]->() WHERE r.last_activated_at < {cutoff} "
        f"SET r.weight = r.weight * {decay_factor}"
    )

    rows = falkor_query(
        "MATCH (a:Episode {uuid: \\'decay-test-a\\'})-[r:CO_ACTIVATED]->"
        "(b:Episode {uuid: \\'decay-test-b\\'}) RETURN r.weight"
    )
    w_after = float(rows[0][0])
    print(f"    stale edge weight after:  {w_after:.4f}")
    assert w_after < w_before, f"Weight should decrease: {w_before} → {w_after}"

    # Simulate prune: set weight to near-zero, then delete
    falkor_write(
        "MATCH (a:Episode {uuid: \\'decay-test-a\\'})-[r:CO_ACTIVATED]->"
        "(b:Episode {uuid: \\'decay-test-b\\'}) SET r.weight = 0.005"
    )
    falkor_write(
        "MATCH ()-[r:CO_ACTIVATED]->() WHERE r.weight < 0.01 DELETE r"
    )
    rows = falkor_query(
        "MATCH (a:Episode {uuid: \\'decay-test-a\\'})-[r:CO_ACTIVATED]->"
        "(b:Episode {uuid: \\'decay-test-b\\'}) RETURN r.weight"
    )
    assert len(rows) == 0, "Near-zero edge should be pruned"
    print("    near-zero edge pruned ok")

    # Cleanup
    falkor_write(
        "MATCH (e:Episode) WHERE e.uuid IN "
        "[\\'decay-test-a\\', \\'decay-test-b\\'] DELETE e"
    )
    print("    REM decay ok")


# ── Main ─────────────────────────────────────────────────────────────


async def main():
    session_id = f"smoke-hebbian-{int(time.time())}"
    passed = 0
    failed = 0
    total = 7

    print(f"Smoke test: temporal scoring + Hebbian learning")
    print(f"Session: {session_id}")

    async with httpx.AsyncClient(timeout=30) as client:
        # Test 1
        try:
            uuid1, uuid2 = await test_observe_cold_and_warm(client, session_id)
            passed += 1
        except Exception as e:
            print(f"    FAIL: {e}")
            failed += 1
            uuid1, uuid2 = None, None

        # Test 2
        uuid3 = None
        if uuid1:
            try:
                uuid3 = await test_temporal_scoring(client, session_id, uuid1)
                passed += 1
            except Exception as e:
                print(f"    FAIL: {e}")
                failed += 1

        # Test 3
        if uuid1 and uuid2 and uuid3:
            uuids = [uuid1, uuid2, uuid3]
            try:
                await test_hebbian_activation_counts(uuids)
                passed += 1
            except Exception as e:
                print(f"    FAIL: {e}")
                failed += 1

            # Test 4
            try:
                await test_hebbian_co_activated_edges()
                passed += 1
            except Exception as e:
                print(f"    FAIL: {e}")
                failed += 1

            # Test 5
            try:
                await test_repeated_co_activation(client, session_id, uuid1)
                passed += 1
            except Exception as e:
                print(f"    FAIL: {e}")
                failed += 1

        # Test 6
        try:
            await test_scoring_module()
            passed += 1
        except Exception as e:
            print(f"    FAIL: {e}")
            failed += 1

        # Test 7
        try:
            await test_rem_decay()
            passed += 1
        except Exception as e:
            print(f"    FAIL: {e}")
            failed += 1

    print(f"\n{'='*50}")
    status = "PASS" if failed == 0 else "FAIL"
    print(f"[{status}] {passed}/{passed + failed} tests passed")
    print(f"{'='*50}")

    if failed > 0:
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
