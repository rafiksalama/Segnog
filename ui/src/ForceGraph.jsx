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

export default function ForceGraphView({ nodes, edges, cooccur, width, height, theme }) {
  const fgRef = useRef();
  const isDark = theme === "dark";
  const [search, setSearch] = useState("");
  const [highlightNode, setHighlightNode] = useState(null);

  // Build graph data: nodes + links
  const graphData = useMemo(() => {
    if (!nodes || nodes.length === 0) return { nodes: [], links: [] };

    // Build index and degree
    // Use name as node ID (deduped across groups by backend)
    const idxMap = {};
    const degree = {};
    nodes.forEach((n, i) => { idxMap[n.name] = i; degree[n.name] = 0; });

    const links = [];
    const seen = new Set();

    // Semantic RELATES edges
    (edges || []).forEach(e => {
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
    const graphNodes = nodes
      .filter(n => (degree[n.name] || 0) > 0) // hide isolates
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
          // Size: log scale so high-degree nodes don't dominate
          val: isHub ? 6 + Math.log2(1 + deg) * 4 : 2 + Math.log2(1 + deg) * 2,
          sourceCount: sc,
        };
      });

    return { nodes: graphNodes, links };
  }, [nodes, edges, cooccur]);

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

  // Configure forces and fit after data loads
  useEffect(() => {
    if (fgRef.current && graphData.nodes.length > 0) {
      // Tune forces: moderate charge, short link distance
      fgRef.current.d3Force("charge").strength(-40).distanceMax(200);
      fgRef.current.d3Force("link").distance(link => {
        const srcHub = link.source?.isHub || false;
        const tgtHub = link.target?.isHub || false;
        return (srcHub && tgtHub) ? 120 : 50; // hubs spread, spokes close
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
      {/* Search box */}
      <div style={{
        position: "absolute", top: 14, left: 14, zIndex: 20,
        display: "flex", gap: 6, alignItems: "center",
      }}>
        <input
          type="text"
          value={search}
          onChange={e => handleSearch(e.target.value)}
          placeholder="Search entity..."
          style={{
            width: 220, padding: "8px 12px", fontSize: 13,
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
        }}
        enableNodeDrag={true}
        enableZoomPanInteraction={true}
      />
    </div>
  );
}
