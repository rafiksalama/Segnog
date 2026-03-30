/**
 * ForceGraph — React wrapper around react-force-graph-2d for the knowledge graph.
 *
 * Renders OntologyNodes as a force-directed graph with:
 *   - Node size proportional to source_count (importance)
 *   - Node color by Schema.org type
 *   - Edge thickness: semantic RELATES (thick) vs co-occurrence (thin)
 *   - Hub nodes get labels, leaves don't until zoomed
 *   - d3-force handles all layout physics
 */

import { useRef, useCallback, useMemo, useEffect, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

const TYPE_PALETTE = [
  "#5de4c7","#82aaff","#c792ea","#ffd580","#ff6b8a","#22c55e",
  "#f97316","#06b6d4","#a78bfa","#fb923c","#34d399","#f472b6",
  "#60a5fa","#facc15","#4ade80","#e879f9","#38bdf8","#fb7185",
];

function typeColor(t) {
  let h = 0;
  for (let i = 0; i < (t || "").length; i++) h = (h * 31 + (t || "").charCodeAt(i)) >>> 0;
  return TYPE_PALETTE[h % TYPE_PALETTE.length];
}

const API = "/api/v1/memory";

// Simple fetch hook
function useJsonFetch(url) {
  const [data, setData] = useState(null);
  const urlRef = useRef("");
  useEffect(() => {
    if (url === urlRef.current) return;
    urlRef.current = url;
    fetch(url).then(r => r.json()).then(setData).catch(() => {});
  }, [url]);
  return data;
}

export default function ForceGraphView({ nodes, edges, cooccur, width, height, theme, sessions }) {
  const fgRef = useRef();
  const isDark = theme === "dark";
  const [search, setSearch] = useState("");
  const [highlightNode, setHighlightNode] = useState(null);
  const [selectedSession, setSelectedSession] = useState("__all__");
  const [nodeDetail, setNodeDetail] = useState(null); // {name, type, summary, ...}

  // When a session is selected, fetch session-specific data
  const sessionParam = selectedSession === "__all__" ? "" : `?group_id=${selectedSession}`;
  const sessionNodes = useJsonFetch(selectedSession !== "__all__" ? `${API}/ui/ontology?group_id=${selectedSession}` : null);
  const sessionEdges = useJsonFetch(selectedSession !== "__all__" ? `${API}/ui/ontology/edges?group_id=${selectedSession}&limit=2000` : null);

  // Use session-specific data if a session is selected, otherwise use global data
  const activeNodes = selectedSession === "__all__" ? nodes : (sessionNodes?.nodes || []);
  const activeEdges = selectedSession === "__all__" ? edges : (sessionEdges?.edges || []);

  // Stabilize inputs: only recompute when counts actually change
  const stableKey = `${selectedSession}-${activeNodes?.length || 0}-${activeEdges?.length || 0}-${cooccur?.length || 0}`;
  const prevKeyRef = useRef("");
  const prevDataRef = useRef({ nodes: [], links: [] });

  // Build graph data: nodes + links
  const graphData = useMemo(() => {
    // Skip recompute if data hasn't changed
    if (stableKey === prevKeyRef.current && prevDataRef.current.nodes.length > 0) {
      return prevDataRef.current;
    }
    prevKeyRef.current = stableKey;
    if (!activeNodes || activeNodes.length === 0) return { nodes: [], links: [] };

    const idxMap = {};
    const degree = {};
    activeNodes.forEach((n, i) => { idxMap[n.name] = i; degree[n.name] = 0; });

    const links = [];
    const seen = new Set();

    // Semantic RELATES edges
    (activeEdges || []).forEach(e => {
      if (!e.source || !e.target) return;
      if (!(e.source in idxMap) || !(e.target in idxMap)) return;
      const key = [e.source, e.target].sort().join("-");
      if (seen.has(key)) return;
      seen.add(key);
      links.push({
        source: e.source, target: e.target,
        type: "semantic", predicate: e.predicate || "",
      });
      degree[e.source] = (degree[e.source] || 0) + 1;
      degree[e.target] = (degree[e.target] || 0) + 1;
    });

    // Co-occurrence edges (source/target are names now)
    (cooccur || []).forEach(e => {
      if (!e.source || !e.target) return;
      if (!(e.source in idxMap) || !(e.target in idxMap)) return;
      const key = [e.source, e.target].sort().join("-");
      if (seen.has(key)) return;
      seen.add(key);
      links.push({
        source: e.source, target: e.target,
        type: "cooccur",
      });
      degree[e.source] = (degree[e.source] || 0) + 1;
      degree[e.target] = (degree[e.target] || 0) + 1;
    });

    // Determine hub threshold (top 5% by degree)
    const degrees = Object.values(degree).sort((a, b) => b - a);
    const hubThreshold = degrees[Math.min(Math.floor(degrees.length * 0.03), 30)] || 3;

    // Enrich nodes
    // Cap total nodes for performance (keep all connected + top isolated by source_count)
    const connected = activeNodes.filter(n => (degree[n.name] || 0) > 0);
    const isolated = activeNodes.filter(n => (degree[n.name] || 0) === 0)
      .sort((a, b) => (b.source_count || 0) - (a.source_count || 0))
      .slice(0, Math.max(0, 2000 - connected.length));
    const visibleNodes = [...connected, ...isolated];

    const graphNodes = visibleNodes
      .map(n => {
        const deg = degree[n.name] || 0;
        const isHub = deg >= hubThreshold;
        const sc = n.source_count || 1;
        return {
          id: n.name,  // name is unique after backend dedup
          name: n.display_name || n.name,
          type: n.schema_type || "Thing",
          category: n.category || n.schema_type || "Thing",
          color: typeColor(n.category || n.schema_type || "Thing"),
          deg,
          isHub,
          // Size: hubs large, spokes medium, isolates tiny
          val: isHub ? 6 + Math.log2(1 + deg) * 4
             : deg > 0 ? 2 + Math.log2(1 + deg) * 2
             : 0.5,  // isolated: tiny dot
          sourceCount: sc,
        };
      });

    const result = { nodes: graphNodes, links };
    prevDataRef.current = result;
    return result;
  }, [stableKey]);

  // Search: find node by name and zoom to it
  const handleSearch = useCallback((query) => {
    setSearch(query);
    if (!query || !fgRef.current || !graphData.nodes.length) {
      setHighlightNode(null);
      return;
    }
    const q = query.toLowerCase();
    const match = graphData.nodes.find(n =>
      n.name.toLowerCase().includes(q)
    );
    if (match) {
      setHighlightNode(match);
      fgRef.current.centerAt(match.x, match.y, 600);
      fgRef.current.zoom(3, 600);
    } else {
      setHighlightNode(null);
    }
  }, [graphData]);

  // Configure forces and fit — once per session change
  const didFit = useRef(false);
  const prevSession = useRef(selectedSession);
  if (prevSession.current !== selectedSession) {
    didFit.current = false;
    prevSession.current = selectedSession;
  }
  useEffect(() => {
    if (fgRef.current && graphData.nodes.length > 0 && !didFit.current) {
      didFit.current = true;
      fgRef.current.d3Force("charge").strength(-40).distanceMax(200);
      fgRef.current.d3Force("link").distance(link => {
        const srcHub = link.source?.isHub || false;
        const tgtHub = link.target?.isHub || false;
        return (srcHub && tgtHub) ? 120 : 50;
      });
      fgRef.current.d3ReheatSimulation();
      setTimeout(() => fgRef.current.zoomToFit(400, 60), 1000);
    }
  }, [graphData]);

  // Custom node painting
  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = Math.sqrt(node.val) * 2;
    const screenR = r * globalScale;
    const isHighlighted = highlightNode && highlightNode.id === node.id;

    // Highlight ring for search result
    if (isHighlighted) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 8, 0, Math.PI * 2);
      ctx.fillStyle = "#ff6b8a40";
      ctx.fill();
      ctx.strokeStyle = "#ff6b8a";
      ctx.lineWidth = 3 / globalScale;
      ctx.stroke();
    }

    // Glow for hubs
    if (node.isHub) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 5, 0, Math.PI * 2);
      ctx.fillStyle = node.color + "15";
      ctx.fill();
    }

    // Main circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.fillStyle = node.isHub ? node.color + "bb" : node.color + "70";
    ctx.fill();
    ctx.strokeStyle = isHighlighted ? "#ff6b8a" : node.color;
    ctx.lineWidth = (isHighlighted ? 3 : node.isHub ? 2 : 1) / globalScale;
    ctx.stroke();

    // Labels — show when node is big enough on screen
    // Hubs: always show. Spokes: show when zoomed enough
    const showLabel = node.isHub || screenR > 6;
    if (showLabel) {
      const fontSize = node.isHub
        ? Math.max(3.5, Math.min(14, 13 / globalScale))
        : Math.max(2.5, Math.min(10, 9 / globalScale));
      ctx.fillStyle = isDark ? "#e2e4ea" : "#1c1c1a";
      ctx.font = `${node.isHub ? "bold " : ""}${fontSize}px Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(node.name, node.x, node.y + r + 1.5);
    }
  }, [isDark, highlightNode]);

  // Link styling
  const linkWidth = useCallback(link => {
    if (link.type === "semantic") {
      // Check if both ends are hubs
      const srcHub = link.source?.isHub || false;
      const tgtHub = link.target?.isHub || false;
      return (srcHub && tgtHub) ? 3 : 1;
    }
    return 0.3; // co-occurrence: very thin
  }, []);

  const linkColor = useCallback(link => {
    if (link.type === "semantic") {
      const srcHub = link.source?.isHub || false;
      const tgtHub = link.target?.isHub || false;
      if (srcHub && tgtHub) return isDark ? "#7a7f94" : "#5a5a52";
      return isDark ? "#7a7f9440" : "#5a5a5240";
    }
    return isDark ? "#7a7f9418" : "#5a5a5218";
  }, [isDark]);

  if (graphData.nodes.length === 0) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
        width, height, color: isDark ? "#4a4f62" : "#9a9a90", fontSize: 14 }}>
        No connected entities yet
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width, height }}>
      {/* Controls: session dropdown + search */}
      <div style={{
        position: "absolute", top: 14, left: 14, zIndex: 20,
        display: "flex", gap: 8, alignItems: "center",
      }}>
        <select
          value={selectedSession}
          onChange={e => { setSelectedSession(e.target.value); didFit.current = false; }}
          style={{
            padding: "8px 10px", fontSize: 12, borderRadius: 8,
            background: isDark ? "#181b24" : "#ffffff",
            color: isDark ? "#e2e4ea" : "#1c1c1a",
            border: `1px solid ${isDark ? "#282d3e" : "#dddbd5"}`,
            fontFamily: "Inter, sans-serif", maxWidth: 200,
          }}
        >
          <option value="__all__">All sessions ({(sessions || []).length})</option>
          {(sessions || [])
            .sort((a, b) => (b.latest_at || 0) - (a.latest_at || 0))
            .map(s => {
              const date = s.latest_at ? new Date(s.latest_at * 1000).toLocaleDateString() : "";
              return (
                <option key={s.group_id} value={s.group_id}>
                  {s.group_id.slice(0, 8)}… · {s.episode_count} eps · {date}
                </option>
              );
            })}
        </select>
        <input
          type="text"
          value={search}
          onChange={e => handleSearch(e.target.value)}
          placeholder="Search entity..."
          style={{
            width: 180, padding: "8px 12px", fontSize: 13,
            background: isDark ? "#181b24" : "#ffffff",
            color: isDark ? "#e2e4ea" : "#1c1c1a",
            border: `1px solid ${isDark ? "#282d3e" : "#dddbd5"}`,
            borderRadius: 8, outline: "none",
            fontFamily: "Inter, sans-serif",
          }}
        />
        {highlightNode && (
          <span style={{
            fontSize: 11, padding: "4px 10px", borderRadius: 6,
            background: "#ff6b8a30", color: "#ff6b8a", fontWeight: 600,
            whiteSpace: "nowrap",
          }}>
            {highlightNode.name}
          </span>
        )}
        {search && !highlightNode && (
          <span style={{ fontSize: 11, color: isDark ? "#4a4f62" : "#9a9a90" }}>
            No match
          </span>
        )}
      </div>

      <ForceGraph2D
        ref={fgRef}
        width={width}
        height={height}
        graphData={graphData}
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => "replace"}
        linkWidth={linkWidth}
        linkColor={linkColor}
        linkDirectionalParticles={0}
        nodeRelSize={4}
        d3VelocityDecay={0.4}
        d3AlphaDecay={0.015}
        warmupTicks={100}
        cooldownTicks={300}
        d3AlphaMin={0.001}
        backgroundColor={isDark ? "#0a0b0f" : "#f4f3ef"}
        onNodeClick={(node) => {
          setHighlightNode(node);
          setSearch(node.name);
          // Fetch full details (summary) for popup
          setNodeDetail({ name: node.name, type: node.type, category: node.category, deg: node.deg, loading: true });
          fetch(`${API}/ui/ontology/${encodeURIComponent(node.id)}`)
            .then(r => r.json())
            .then(data => {
              if (data.summary) setNodeDetail(prev => prev ? { ...prev, summary: data.summary, loading: false } : null);
              else setNodeDetail(prev => prev ? { ...prev, loading: false } : null);
            })
            .catch(() => setNodeDetail(prev => prev ? { ...prev, loading: false } : null));
        }}
        onBackgroundClick={() => setNodeDetail(null)}
        enableNodeDrag={true}
        enableZoomPanInteraction={true}
      />

      {/* Node detail popup */}
      {nodeDetail && (
        <div style={{
          position: "absolute", bottom: 16, left: 16, right: 16, maxHeight: 220,
          background: isDark ? "#12141af0" : "#ffffffee",
          border: `1px solid ${isDark ? "#282d3e" : "#dddbd5"}`,
          borderRadius: 12, padding: "14px 18px", zIndex: 20,
          boxShadow: "0 -4px 20px rgba(0,0,0,0.2)", overflowY: "auto",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <div>
              <span style={{ fontSize: 16, fontWeight: 700, color: isDark ? "#e2e4ea" : "#1c1c1a" }}>
                {nodeDetail.name}
              </span>
              <span style={{
                marginLeft: 10, fontSize: 11, padding: "2px 8px", borderRadius: 4,
                background: typeColor(nodeDetail.category) + "30",
                color: typeColor(nodeDetail.category),
                fontWeight: 600,
              }}>
                {nodeDetail.type}
              </span>
              <span style={{ marginLeft: 8, fontSize: 11, color: isDark ? "#7a7f94" : "#5a5a52" }}>
                {nodeDetail.deg} connections
              </span>
            </div>
            <button onClick={() => setNodeDetail(null)} style={{
              background: "none", border: "none", cursor: "pointer",
              color: isDark ? "#7a7f94" : "#9a9a90", fontSize: 18, lineHeight: 1,
            }}>×</button>
          </div>
          {nodeDetail.loading && <div style={{ color: isDark ? "#4a4f62" : "#9a9a90", fontSize: 12 }}>Loading summary...</div>}
          {nodeDetail.summary && (
            <div style={{ fontSize: 13, lineHeight: 1.6, color: isDark ? "#b0b3c0" : "#3a3a38" }}>
              {nodeDetail.summary}
            </div>
          )}
          {!nodeDetail.loading && !nodeDetail.summary && (
            <div style={{ color: isDark ? "#4a4f62" : "#9a9a90", fontSize: 12, fontStyle: "italic" }}>No summary available</div>
          )}
        </div>
      )}
    </div>
  );
}
