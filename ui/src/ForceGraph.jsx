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

import { useRef, useCallback, useMemo, useEffect } from "react";
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

  // Build graph data: nodes + links
  const graphData = useMemo(() => {
    if (!nodes || nodes.length === 0) return { nodes: [], links: [] };

    // Build index and degree
    const idxMap = {};
    const degree = {};
    nodes.forEach((n, i) => { idxMap[n.uuid] = i; degree[n.uuid] = 0; });

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

    // Co-occurrence edges
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
      .filter(n => (degree[n.uuid] || 0) > 0) // hide isolates
      .map(n => {
        const deg = degree[n.uuid] || 0;
        const isHub = deg >= hubThreshold;
        const sc = n.source_count || 1;
        return {
          id: n.uuid,
          name: n.display_name || n.name,
          type: n.schema_type || "Thing",
          category: n.category || n.schema_type || "Thing",
          color: typeColor(n.category || n.schema_type || "Thing"),
          deg,
          isHub,
          // Size: hubs are bigger
          val: isHub ? 8 + deg * 2 : 2 + Math.min(deg, 5),
          sourceCount: sc,
        };
      });

    return { nodes: graphNodes, links };
  }, [nodes, edges, cooccur]);

  // Fit graph after data loads
  useEffect(() => {
    if (fgRef.current && graphData.nodes.length > 0) {
      setTimeout(() => fgRef.current.zoomToFit(400, 60), 500);
    }
  }, [graphData]);

  // Custom node painting
  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = Math.sqrt(node.val) * 1.8;
    const fontSize = node.isHub ? Math.max(3, 12 / globalScale) : Math.max(2, 8 / globalScale);

    // Glow for hubs
    if (node.isHub) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2);
      ctx.fillStyle = node.color + "20";
      ctx.fill();
    }

    // Main circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.fillStyle = node.isHub ? node.color + "cc" : node.color + "60";
    ctx.fill();
    ctx.strokeStyle = node.color;
    ctx.lineWidth = node.isHub ? 2 / globalScale : 0.5 / globalScale;
    ctx.stroke();

    // Label: hubs always, spokes only when zoomed
    const showLabel = node.isHub || (globalScale > 2 && node.deg >= 2);
    if (showLabel) {
      ctx.fillStyle = isDark ? "#e2e4ea" : "#1c1c1a";
      ctx.font = `${node.isHub ? "bold" : ""} ${fontSize}px Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(node.name, node.x, node.y + r + 2);
    }
  }, [isDark]);

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
      d3VelocityDecay={0.3}
      d3AlphaDecay={0.02}
      warmupTicks={80}
      cooldownTicks={200}
      backgroundColor={isDark ? "#0a0b0f" : "#f4f3ef"}
      onNodeClick={(node) => {
        // Could emit event to parent for popup
      }}
      enableNodeDrag={true}
      enableZoomPanInteraction={true}
    />
  );
}
