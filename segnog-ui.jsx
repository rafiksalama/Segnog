import { useState, useEffect, useRef, useCallback } from "react";

// ─── Mock Data ─────────────────────────────────────────────────────────
const MOCK_SESSIONS = [
  { id: "agent-session-42", entries: 47, age: "2h 14m", status: "warm", group: "locomo-conv-0" },
  { id: "agent-session-88", entries: 12, age: "18m", status: "warm", group: "locomo-conv-0" },
  { id: "deploy-monitor-3", entries: 204, age: "6h 02m", status: "warm", group: "ops-team" },
  { id: "onboarding-flow-7", entries: 3, age: "34s", status: "cold", group: "hr-bot" },
  { id: "customer-support-19", entries: 89, age: "1h 47m", status: "warm", group: "support-v2" },
];

const MOCK_EPISODES = [
  { uuid: "550e8400-e29b-41d4", content: "The user asked about last quarter's deployment incident.", source: "chat", created: "14:30:00", score: 0.94, consolidated: true, knowledgeExtracted: true },
  { uuid: "6ba7b810-9dad-11d1", content: "Caroline identified the root cause as a memory leak in the worker pool from the v2.3 release.", source: "chat", created: "14:31:12", score: 0.91, consolidated: true, knowledgeExtracted: true },
  { uuid: "7c9e6679-7425-40de", content: "The patch was deployed as v2.3.1 the following morning. Downtime was approximately 4 hours.", source: "system", created: "14:32:45", score: 0.87, consolidated: false, knowledgeExtracted: false },
  { uuid: "a0eebc99-9c0b-4ef8", content: "User wants to understand what monitoring was in place and why it wasn't caught earlier.", source: "chat", created: "14:34:01", score: 0.82, consolidated: false, knowledgeExtracted: false },
  { uuid: "b5d6e7f8-1234-5678", content: "The Prometheus alerting rules for memory thresholds were set too high — 95% instead of the recommended 80%.", source: "tool", created: "14:35:22", score: 0.79, consolidated: false, knowledgeExtracted: false },
];

const MOCK_KNOWLEDGE = [
  { content: "Caroline identified the memory leak in the worker pool", type: "fact", confidence: 0.91, labels: ["deployment", "infrastructure"], date: "2025-10-15" },
  { content: "v2.3 deployment on Oct 14 caused a memory leak that was patched in v2.3.1", type: "fact", confidence: 0.95, labels: ["deployment", "incident"], date: "2025-10-14" },
  { content: "Prometheus alerting thresholds should be set to 80% for memory, not 95%", type: "procedure", confidence: 0.88, labels: ["monitoring", "best-practice"], date: "2025-10-16" },
  { content: "Post-incident reviews should include monitoring gap analysis", type: "pattern", confidence: 0.84, labels: ["process", "incident-response"], date: "2025-10-20" },
  { content: "Worker pool memory leaks correlate with high connection churn during deployments", type: "insight", confidence: 0.77, labels: ["infrastructure", "pattern"], date: "2025-10-18" },
];

const MOCK_ONTOLOGY = [
  { name: "Caroline Zhao", type: "Person", summary: "Software engineer at Meridian Labs. Deployed v2.3 in October and identified the memory leak.", sources: 7, connections: 4 },
  { name: "Meridian Labs", type: "Organization", summary: "Technology company. Caroline Zhao and Marcus Chen are engineers here.", sources: 12, connections: 6 },
  { name: "v2.3 Deployment", type: "Event", summary: "October 14th release that caused a memory leak in the worker pool.", sources: 5, connections: 3 },
  { name: "Marcus Chen", type: "Person", summary: "Site reliability engineer. Set up the original Prometheus alerting rules.", sources: 3, connections: 2 },
  { name: "Worker Pool", type: "SoftwareApplication", summary: "Core infrastructure component that processes async jobs.", sources: 8, connections: 5 },
];

const MOCK_BENCHMARK = [
  { category: "1. Single-hop", n: 32, f1: 0.777, judge: 0.758 },
  { category: "2. Temporal", n: 37, f1: 0.946, judge: 0.912 },
  { category: "3. Multi-hop", n: 13, f1: 0.673, judge: 0.673 },
  { category: "4. Open-domain", n: 70, f1: 0.873, judge: 0.871 },
  { category: "5. Adversarial", n: 47, f1: 0.872, judge: null },
];

const MOCK_REM_LOG = [
  { time: "14:36:01", group: "locomo-conv-0", action: "Dedup check", detail: "2 unique / 0 duplicates", status: "ok" },
  { time: "14:36:02", group: "locomo-conv-0", action: "Knowledge extraction", detail: "3 facts, 1 pattern extracted", status: "ok" },
  { time: "14:36:04", group: "locomo-conv-0", action: "Ontology update", detail: "2 entities updated, 1 new relationship", status: "ok" },
  { time: "14:36:05", group: "locomo-conv-0", action: "Temporal compression", detail: "2 episodes → 1 summary", status: "ok" },
  { time: "14:36:06", group: "ops-team", action: "Hebbian decay", detail: "14 edges decayed, 2 pruned (<0.01)", status: "ok" },
  { time: "14:35:01", group: "support-v2", action: "Dedup check", detail: "5 unique / 1 duplicate", status: "ok" },
  { time: "14:35:03", group: "support-v2", action: "Knowledge extraction", detail: "2 facts, 1 insight extracted", status: "ok" },
];

// ─── Icon Components ───────────────────────────────────────────────────
const Icon = ({ d, size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const icons = {
  dashboard: "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z M9 22V12h6v10",
  sessions: "M21 12a9 9 0 11-18 0 9 9 0 0118 0z M12 6v6l4 2",
  graph: "M12 2a3 3 0 00-3 3c0 1.1.6 2 1.5 2.6L6 12l-3-1v6l3-1 4.5 4.4c-.9.6-1.5 1.5-1.5 2.6a3 3 0 106 0c0-1.1-.6-2-1.5-2.6L18 17l3 1v-6l-3 1-4.5-4.4c.9-.6 1.5-1.5 1.5-2.6a3 3 0 00-3-3z",
  observe: "M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z M12 9a3 3 0 110 6 3 3 0 010-6z",
  rem: "M17 10.5V7a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h12a1 1 0 001-1v-3.5l4 4v-11l-4 4z",
  config: "M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001.08 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1.08z",
  benchmark: "M18 20V10 M12 20V4 M6 20v-6",
  chevron: "M9 18l6-6-6-6",
  check: "M20 6L9 17l-5-5",
  x: "M18 6L6 18 M6 6l12 12",
  copy: "M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2v-2 M16 2h2a2 2 0 012 2v8a2 2 0 01-2 2h-8a2 2 0 01-2-2V4a2 2 0 012-2z",
  send: "M22 2L11 13 M22 2l-7 20-4-9-9-4 20-7z",
  play: "M5 3l14 9-14 9V3z",
  brain: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z M12 6v6l4.5 2.5",
  zap: "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
};

// ─── Styles ────────────────────────────────────────────────────────────
const FONT = `'DM Sans', 'Satoshi', system-ui, -apple-system, sans-serif`;
const MONO = `'JetBrains Mono', 'SF Mono', 'Fira Code', monospace`;

const palette = {
  bg: "#0a0b0f",
  surface: "#12141a",
  surfaceAlt: "#181b24",
  border: "#1e2230",
  borderLight: "#282d3e",
  text: "#e2e4ea",
  textMuted: "#7a7f94",
  textDim: "#4a4f62",
  accent: "#5de4c7",       // segno green
  accentDim: "#5de4c720",
  accentMid: "#5de4c750",
  warm: "#ffd580",
  warmDim: "#ffd58020",
  coral: "#ff6b8a",
  coralDim: "#ff6b8a20",
  blue: "#82aaff",
  blueDim: "#82aaff20",
  purple: "#c792ea",
  purpleDim: "#c792ea20",
};

// ─── Reusable Components ───────────────────────────────────────────────
const Badge = ({ children, color = palette.accent, bg }) => (
  <span style={{
    fontSize: 10, fontWeight: 600, fontFamily: MONO,
    padding: "2px 8px", borderRadius: 4,
    color, background: bg || color + "18",
    letterSpacing: "0.03em", textTransform: "uppercase",
  }}>{children}</span>
);

const StatCard = ({ label, value, sub, color = palette.accent, icon }) => (
  <div style={{
    background: palette.surface, border: `1px solid ${palette.border}`,
    borderRadius: 12, padding: "20px 22px", flex: 1, minWidth: 160,
    position: "relative", overflow: "hidden",
  }}>
    <div style={{ position: "absolute", top: -8, right: -8, opacity: 0.06, color }}>
      <svg width="80" height="80" viewBox="0 0 24 24" fill="currentColor"><path d={icon || icons.zap} /></svg>
    </div>
    <div style={{ fontSize: 11, color: palette.textMuted, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8, fontFamily: MONO }}>{label}</div>
    <div style={{ fontSize: 32, fontWeight: 700, color, lineHeight: 1, fontFamily: MONO }}>{value}</div>
    {sub && <div style={{ fontSize: 12, color: palette.textMuted, marginTop: 6 }}>{sub}</div>}
  </div>
);

const SectionTitle = ({ children, right }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
    <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: palette.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: MONO }}>{children}</h3>
    {right}
  </div>
);

const Table = ({ columns, rows, onRowClick }) => (
  <div style={{ borderRadius: 10, border: `1px solid ${palette.border}`, overflow: "hidden" }}>
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontFamily: FONT }}>
      <thead>
        <tr style={{ background: palette.surfaceAlt }}>
          {columns.map((col, i) => (
            <th key={i} style={{
              padding: "10px 14px", textAlign: "left", fontSize: 10, fontWeight: 700,
              color: palette.textMuted, letterSpacing: "0.1em", textTransform: "uppercase",
              fontFamily: MONO, borderBottom: `1px solid ${palette.border}`,
            }}>{col.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, ri) => (
          <tr key={ri} onClick={() => onRowClick?.(row)} style={{
            cursor: onRowClick ? "pointer" : "default",
            borderBottom: ri < rows.length - 1 ? `1px solid ${palette.border}` : "none",
            transition: "background 0.15s",
          }}
            onMouseEnter={e => e.currentTarget.style.background = palette.surfaceAlt}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          >
            {columns.map((col, ci) => (
              <td key={ci} style={{
                padding: "11px 14px", color: palette.text,
                fontFamily: col.mono ? MONO : FONT,
                fontSize: col.mono ? 12 : 13,
              }}>{col.render ? col.render(row) : row[col.key]}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

// ─── Page: Dashboard ───────────────────────────────────────────────────
const DashboardPage = () => {
  const [pulse, setPulse] = useState(true);
  useEffect(() => { const t = setInterval(() => setPulse(p => !p), 2000); return () => clearInterval(t); }, []);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: palette.text }}>System Overview</h2>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "#22c55e15", padding: "4px 12px", borderRadius: 20,
        }}>
          <div style={{
            width: 7, height: 7, borderRadius: "50%", background: "#22c55e",
            boxShadow: pulse ? "0 0 8px #22c55e" : "none", transition: "box-shadow 0.8s",
          }} />
          <span style={{ fontSize: 11, color: "#22c55e", fontWeight: 600, fontFamily: MONO }}>HEALTHY</span>
        </div>
      </div>
      <p style={{ color: palette.textMuted, fontSize: 14, marginTop: 4, marginBottom: 28 }}>All services operational · Container uptime 14h 32m</p>

      {/* Stat Cards */}
      <div style={{ display: "flex", gap: 14, marginBottom: 28, flexWrap: "wrap" }}>
        <StatCard label="Active Sessions" value="5" sub="3 warm · 1 cold · 1 expiring" color={palette.accent} icon={icons.sessions} />
        <StatCard label="Episodes Stored" value="1,247" sub="+38 today" color={palette.blue} icon={icons.brain} />
        <StatCard label="Knowledge Nodes" value="312" sub="89 facts · 41 patterns" color={palette.warm} icon={icons.zap} />
        <StatCard label="Ontology Entities" value="67" sub="34 Person · 18 Org" color={palette.purple} icon={icons.graph} />
      </div>

      {/* Services Grid */}
      <SectionTitle>Infrastructure Services</SectionTitle>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 28 }}>
        {[
          { name: "DragonflyDB", port: 6381, role: "Session Cache", mem: "48 MB", status: "running" },
          { name: "FalkorDB", port: 6380, role: "Graph Store", mem: "312 MB", status: "running" },
          { name: "NATS", port: 4222, role: "Event Bus", msg: "2.4k/min", status: "running" },
          { name: "REST Server", port: 9000, role: "HTTP API", rps: "~140 rps", status: "running" },
          { name: "gRPC Server", port: 50051, role: "RPC API", rps: "~85 rps", status: "running" },
          { name: "REM Worker", port: "—", role: "Consolidation", cycle: "60s", status: "running" },
        ].map((s, i) => (
          <div key={i} style={{
            background: palette.surface, border: `1px solid ${palette.border}`,
            borderRadius: 10, padding: "16px 18px",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: palette.text, marginBottom: 2 }}>{s.name}</div>
                <div style={{ fontSize: 11, color: palette.textMuted }}>{s.role}</div>
              </div>
              <Badge color="#22c55e">Running</Badge>
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 16 }}>
              <div style={{ fontSize: 11, color: palette.textDim, fontFamily: MONO }}>
                <span style={{ color: palette.textMuted }}>port</span> {s.port}
              </div>
              <div style={{ fontSize: 11, color: palette.textDim, fontFamily: MONO }}>
                {s.mem || s.msg || s.rps || s.cycle}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Activity */}
      <SectionTitle>Recent REM Consolidation Activity</SectionTitle>
      <Table
        columns={[
          { label: "Time", key: "time", mono: true },
          { label: "Group", key: "group", mono: true },
          { label: "Action", key: "action" },
          { label: "Detail", key: "detail" },
          { label: "Status", render: r => <Badge color="#22c55e">OK</Badge> },
        ]}
        rows={MOCK_REM_LOG}
      />
    </div>
  );
};

// ─── Page: Sessions ────────────────────────────────────────────────────
const SessionsPage = () => {
  const [selected, setSelected] = useState(MOCK_SESSIONS[0]);

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: palette.text }}>Session Explorer</h2>
      <p style={{ color: palette.textMuted, fontSize: 14, marginTop: 4, marginBottom: 24 }}>DragonflyDB session cache · TTL 24h</p>

      <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 20 }}>
        {/* Session List */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {MOCK_SESSIONS.map(s => (
            <div key={s.id} onClick={() => setSelected(s)} style={{
              background: selected?.id === s.id ? palette.surfaceAlt : palette.surface,
              border: `1px solid ${selected?.id === s.id ? palette.accentMid : palette.border}`,
              borderRadius: 10, padding: "14px 16px", cursor: "pointer",
              transition: "all 0.15s",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: palette.text, fontFamily: MONO }}>{s.id}</span>
                <Badge color={s.status === "warm" ? palette.warm : palette.blue} bg={s.status === "warm" ? palette.warmDim : palette.blueDim}>{s.status}</Badge>
              </div>
              <div style={{ display: "flex", gap: 16, fontSize: 11, color: palette.textMuted, fontFamily: MONO }}>
                <span>{s.entries} entries</span>
                <span>age {s.age}</span>
                <span>{s.group}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Session Detail */}
        <div style={{ background: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 12, padding: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: palette.text, fontFamily: MONO }}>{selected.id}</div>
              <div style={{ fontSize: 12, color: palette.textMuted, marginTop: 2 }}>group: {selected.group}</div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <Badge color={palette.accent}>Entries: {selected.entries}</Badge>
              <Badge color={palette.warm} bg={palette.warmDim}>{selected.status}</Badge>
            </div>
          </div>

          <SectionTitle>Session Entries (latest 5)</SectionTitle>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {MOCK_EPISODES.map((ep, i) => (
              <div key={i} style={{
                background: palette.surfaceAlt, borderRadius: 8, padding: "12px 16px",
                borderLeft: `3px solid ${ep.consolidated ? palette.accent : palette.textDim}`,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ fontSize: 11, fontFamily: MONO, color: palette.textDim }}>{ep.uuid}</span>
                    <Badge color={ep.source === "chat" ? palette.blue : ep.source === "system" ? palette.warm : palette.purple}>
                      {ep.source}
                    </Badge>
                  </div>
                  <span style={{ fontSize: 11, fontFamily: MONO, color: palette.textMuted }}>{ep.created}</span>
                </div>
                <div style={{ fontSize: 13, color: palette.text, lineHeight: 1.5, marginBottom: 8 }}>{ep.content}</div>
                <div style={{ display: "flex", gap: 12, fontSize: 11, fontFamily: MONO, color: palette.textMuted }}>
                  <span>score <span style={{ color: palette.accent }}>{ep.score}</span></span>
                  <span style={{ color: ep.consolidated ? "#22c55e" : palette.textDim }}>
                    {ep.consolidated ? "✓ consolidated" : "○ pending"}
                  </span>
                  <span style={{ color: ep.knowledgeExtracted ? "#22c55e" : palette.textDim }}>
                    {ep.knowledgeExtracted ? "✓ knowledge" : "○ no knowledge"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page: Memory Graph ────────────────────────────────────────────────
const GraphPage = () => {
  const [tab, setTab] = useState("episodes");
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = canvas.offsetHeight * 2;
    ctx.scale(2, 2);
    const w = W / 2, h = H / 2;

    // Draw a mini graph visualization
    const nodes = [
      { x: w * 0.5, y: h * 0.22, r: 22, color: palette.accent, label: "Caroline" },
      { x: w * 0.25, y: h * 0.48, r: 18, color: palette.blue, label: "v2.3 Deploy" },
      { x: w * 0.75, y: h * 0.42, r: 20, color: palette.purple, label: "Meridian Labs" },
      { x: w * 0.38, y: h * 0.75, r: 15, color: palette.warm, label: "Worker Pool" },
      { x: w * 0.68, y: h * 0.72, r: 16, color: palette.coral, label: "Marcus" },
      { x: w * 0.12, y: h * 0.28, r: 12, color: palette.textMuted, label: "Prometheus" },
      { x: w * 0.88, y: h * 0.6, r: 12, color: palette.textMuted, label: "Oct 14" },
    ];

    const edges = [
      [0, 1], [0, 2], [1, 3], [2, 4], [0, 4], [1, 5], [1, 6], [3, 4], [2, 0],
    ];

    ctx.clearRect(0, 0, w, h);

    // Draw edges
    edges.forEach(([a, b]) => {
      ctx.beginPath();
      ctx.moveTo(nodes[a].x, nodes[a].y);
      ctx.lineTo(nodes[b].x, nodes[b].y);
      ctx.strokeStyle = palette.border;
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    // Draw nodes
    nodes.forEach(n => {
      // Glow
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + 6, 0, Math.PI * 2);
      ctx.fillStyle = n.color + "15";
      ctx.fill();
      // Circle
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = n.color + "30";
      ctx.strokeStyle = n.color;
      ctx.lineWidth = 1.5;
      ctx.fill();
      ctx.stroke();
      // Label
      ctx.fillStyle = palette.text;
      ctx.font = `600 11px ${FONT}`;
      ctx.textAlign = "center";
      ctx.fillText(n.label, n.x, n.y + n.r + 16);
    });
  }, []);

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: palette.text }}>Memory Graph</h2>
      <p style={{ color: palette.textMuted, fontSize: 14, marginTop: 4, marginBottom: 24 }}>FalkorDB persistent store · Episodes, Knowledge, Ontology</p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20 }}>
        {/* Graph Canvas */}
        <div style={{
          background: palette.surface, border: `1px solid ${palette.border}`,
          borderRadius: 12, overflow: "hidden", position: "relative",
        }}>
          <div style={{
            position: "absolute", top: 12, left: 14, zIndex: 2,
            display: "flex", gap: 6,
          }}>
            {[
              { c: palette.accent, l: "Person" }, { c: palette.blue, l: "Event" },
              { c: palette.purple, l: "Organization" }, { c: palette.warm, l: "Software" },
              { c: palette.coral, l: "Person" },
            ].map((x, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: palette.textMuted, fontFamily: MONO }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: x.c }} />
                {x.l}
              </div>
            ))}
          </div>
          <canvas ref={canvasRef} style={{ width: "100%", height: 380, display: "block" }} />
          <div style={{
            position: "absolute", bottom: 0, left: 0, right: 0, height: 50,
            background: `linear-gradient(transparent, ${palette.surface})`,
            display: "flex", alignItems: "flex-end", justifyContent: "center", paddingBottom: 10,
          }}>
            <span style={{ fontSize: 11, color: palette.textDim, fontFamily: MONO }}>Ontology subgraph · locomo-conv-0 · 67 nodes · 142 edges</span>
          </div>
        </div>

        {/* Right Panel Tabs */}
        <div>
          <div style={{ display: "flex", gap: 2, marginBottom: 14 }}>
            {["episodes", "knowledge", "ontology"].map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex: 1, padding: "8px 0", fontSize: 11, fontWeight: 700,
                fontFamily: MONO, textTransform: "uppercase", letterSpacing: "0.06em",
                border: "none", borderRadius: 6, cursor: "pointer",
                background: tab === t ? palette.accentDim : "transparent",
                color: tab === t ? palette.accent : palette.textMuted,
                transition: "all 0.15s",
              }}>{t}</button>
            ))}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 340, overflowY: "auto" }}>
            {tab === "episodes" && MOCK_EPISODES.map((ep, i) => (
              <div key={i} style={{ background: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ fontSize: 12, color: palette.text, lineHeight: 1.4, marginBottom: 6 }}>{ep.content}</div>
                <div style={{ display: "flex", gap: 8, fontSize: 10, fontFamily: MONO, color: palette.textMuted }}>
                  <Badge color={palette.blue}>{ep.source}</Badge>
                  <span>score {ep.score}</span>
                </div>
              </div>
            ))}
            {tab === "knowledge" && MOCK_KNOWLEDGE.map((k, i) => (
              <div key={i} style={{ background: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <Badge color={k.type === "fact" ? palette.accent : k.type === "pattern" ? palette.warm : k.type === "procedure" ? palette.blue : palette.purple}>{k.type}</Badge>
                  <span style={{ fontSize: 10, fontFamily: MONO, color: palette.textMuted }}>{k.confidence.toFixed(2)}</span>
                </div>
                <div style={{ fontSize: 12, color: palette.text, lineHeight: 1.4, marginBottom: 6 }}>{k.content}</div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {k.labels.map((l, j) => <span key={j} style={{ fontSize: 10, fontFamily: MONO, color: palette.textDim, background: palette.surfaceAlt, padding: "1px 6px", borderRadius: 3 }}>{l}</span>)}
                </div>
              </div>
            ))}
            {tab === "ontology" && MOCK_ONTOLOGY.map((o, i) => (
              <div key={i} style={{ background: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: palette.text }}>{o.name}</span>
                  <Badge color={palette.purple}>{o.type}</Badge>
                </div>
                <div style={{ fontSize: 12, color: palette.textMuted, lineHeight: 1.4, marginBottom: 6 }}>{o.summary}</div>
                <div style={{ display: "flex", gap: 12, fontSize: 10, fontFamily: MONO, color: palette.textDim }}>
                  <span>{o.sources} sources</span>
                  <span>{o.connections} connections</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page: Observe Playground ──────────────────────────────────────────
const ObservePage = () => {
  const [content, setContent] = useState("The user asked about last quarter's deployment incident.");
  const [sessionId, setSessionId] = useState("agent-session-42");
  const [readOnly, setReadOnly] = useState(false);
  const [summarize, setSummarize] = useState(false);
  const [sent, setSent] = useState(false);
  const [response, setResponse] = useState(null);

  const handleSend = () => {
    setSent(true);
    setTimeout(() => {
      setResponse({
        episode_uuid: "550e8400-e29b-41d4-a716-446655440000",
        context: "In Q3, the v2.3 deployment on October 14th caused a memory leak in the worker pool. It was patched in v2.3.1 the following morning after Caroline identified the root cause in the session logs. The Prometheus alerting thresholds were set at 95% — above the recommended 80% — which delayed detection. Marcus Chen, the SRE who configured the original alerts, has since updated the threshold. Post-incident review recommended mandatory monitoring gap analysis for all future deployments.",
      });
      setSent(false);
    }, 800);
  };

  const requestObj = {
    session_id: sessionId,
    content: content,
    timestamp: new Date().toISOString(),
    source: "chat",
    ...(readOnly && { read_only: true }),
    ...(summarize && { summarize: true }),
  };

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: palette.text }}>Observe Playground</h2>
      <p style={{ color: palette.textMuted, fontSize: 14, marginTop: 4, marginBottom: 24 }}>Test the <code style={{ fontFamily: MONO, color: palette.accent, background: palette.accentDim, padding: "1px 6px", borderRadius: 4 }}>POST /observe</code> endpoint</p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {/* Request */}
        <div>
          <SectionTitle>Request</SectionTitle>
          <div style={{ background: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 12, padding: 20 }}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: palette.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Session ID</label>
              <input value={sessionId} onChange={e => setSessionId(e.target.value)} style={{
                width: "100%", boxSizing: "border-box", padding: "10px 14px", borderRadius: 8,
                border: `1px solid ${palette.borderLight}`, background: palette.surfaceAlt,
                color: palette.text, fontFamily: MONO, fontSize: 13, outline: "none",
              }} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: palette.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Content</label>
              <textarea value={content} onChange={e => setContent(e.target.value)} rows={3} style={{
                width: "100%", boxSizing: "border-box", padding: "10px 14px", borderRadius: 8,
                border: `1px solid ${palette.borderLight}`, background: palette.surfaceAlt,
                color: palette.text, fontFamily: FONT, fontSize: 13, outline: "none", resize: "vertical",
              }} />
            </div>
            <div style={{ display: "flex", gap: 20, marginBottom: 20 }}>
              {[
                { label: "read_only", val: readOnly, set: setReadOnly },
                { label: "summarize", val: summarize, set: setSummarize },
              ].map(f => (
                <label key={f.label} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <div onClick={() => f.set(!f.val)} style={{
                    width: 18, height: 18, borderRadius: 4, border: `1.5px solid ${f.val ? palette.accent : palette.borderLight}`,
                    background: f.val ? palette.accentDim : "transparent", display: "flex", alignItems: "center", justifyContent: "center",
                    transition: "all 0.15s", cursor: "pointer",
                  }}>
                    {f.val && <Icon d={icons.check} size={12} />}
                  </div>
                  <span style={{ fontSize: 12, fontFamily: MONO, color: palette.textMuted }}>{f.label}</span>
                </label>
              ))}
            </div>

            {/* JSON Preview */}
            <div style={{
              background: palette.bg, borderRadius: 8, padding: 14, fontFamily: MONO, fontSize: 11,
              color: palette.textMuted, lineHeight: 1.7, whiteSpace: "pre-wrap", marginBottom: 16,
              border: `1px solid ${palette.border}`,
            }}>
              <span style={{ color: palette.textDim }}>POST /observe</span>{"\n"}{JSON.stringify(requestObj, null, 2)}
            </div>

            <button onClick={handleSend} disabled={sent} style={{
              width: "100%", padding: "12px 0", borderRadius: 8, border: "none",
              background: sent ? palette.surfaceAlt : `linear-gradient(135deg, ${palette.accent}, #4dd4b0)`,
              color: sent ? palette.textMuted : palette.bg, fontWeight: 700, fontSize: 14,
              fontFamily: FONT, cursor: sent ? "wait" : "pointer",
              transition: "all 0.2s", display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
            }}>
              {sent ? "Observing..." : <>Send Observation <Icon d={icons.send} size={14} /></>}
            </button>
          </div>
        </div>

        {/* Response */}
        <div>
          <SectionTitle>Response</SectionTitle>
          <div style={{
            background: palette.surface, border: `1px solid ${response ? palette.accent + "40" : palette.border}`,
            borderRadius: 12, padding: 20, minHeight: 380,
            transition: "border-color 0.3s",
          }}>
            {response ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                  <Badge color="#22c55e">200 OK</Badge>
                  <span style={{ fontSize: 11, fontFamily: MONO, color: palette.textDim }}>~340ms</span>
                </div>
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: palette.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>episode_uuid</div>
                  <div style={{
                    background: palette.surfaceAlt, borderRadius: 6, padding: "8px 12px",
                    fontFamily: MONO, fontSize: 12, color: palette.accent,
                  }}>{response.episode_uuid}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: palette.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>context</div>
                  <div style={{
                    background: palette.surfaceAlt, borderRadius: 8, padding: "14px 16px",
                    fontSize: 13, color: palette.text, lineHeight: 1.6,
                    borderLeft: `3px solid ${palette.accent}`,
                  }}>{response.context}</div>
                </div>

                <div style={{ marginTop: 20, padding: 14, background: palette.bg, borderRadius: 8, border: `1px solid ${palette.border}` }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: palette.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Background Tasks Fired</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {["Store episode → FalkorDB", "Extract knowledge (DSPy)", "Hebbian reinforcement", "Judge observation type"].map((t, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, fontFamily: MONO }}>
                        <span style={{ color: "#22c55e" }}>✓</span>
                        <span style={{ color: palette.textMuted }}>{t}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div style={{
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                height: 340, color: palette.textDim,
              }}>
                <div style={{ fontSize: 48, marginBottom: 12, opacity: 0.3 }}>𝄋</div>
                <div style={{ fontSize: 13 }}>Send an observation to see the response</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page: Benchmark ───────────────────────────────────────────────────
const BenchmarkPage = () => (
  <div>
    <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: palette.text }}>LoCoMo Benchmark</h2>
    <p style={{ color: palette.textMuted, fontSize: 14, marginTop: 4, marginBottom: 28 }}>Long Conversation Modeling · episodes_knowledge retrieval · top-25 + top-10</p>

    <div style={{ display: "flex", gap: 14, marginBottom: 28 }}>
      <StatCard label="Overall F1" value="0.853" sub="Categories 1–4 (n=152)" color={palette.accent} />
      <StatCard label="LLM Judge" value="0.840" sub="Binary CORRECT/WRONG" color={palette.blue} />
      <StatCard label="Best Category" value="Temporal" sub="F1: 0.946 · n=37" color={palette.warm} />
    </div>

    <SectionTitle>Results by Category</SectionTitle>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 20 }}>
      <Table
        columns={[
          { label: "Category", key: "category" },
          { label: "n", key: "n", mono: true },
          { label: "F1", render: r => (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 120, height: 6, background: palette.surfaceAlt, borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${r.f1 * 100}%`, height: "100%", borderRadius: 3, background: r.f1 > 0.9 ? palette.accent : r.f1 > 0.8 ? palette.blue : palette.warm }} />
              </div>
              <span style={{ fontFamily: MONO, fontSize: 13, color: palette.text, fontWeight: 600, minWidth: 45 }}>{r.f1.toFixed(3)}</span>
            </div>
          )},
          { label: "LLM Judge", render: r => r.judge !== null ? (
            <span style={{ fontFamily: MONO, fontSize: 13, color: palette.text }}>{r.judge.toFixed(3)}</span>
          ) : <span style={{ fontFamily: MONO, fontSize: 11, color: palette.textDim }}>—</span>},
        ]}
        rows={MOCK_BENCHMARK}
      />

      {/* Scoring Formula */}
      <div style={{ background: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 12, padding: 20 }}>
        <SectionTitle>3D Scoring Formula</SectionTitle>
        <div style={{
          fontFamily: MONO, fontSize: 12, color: palette.textMuted, lineHeight: 2,
          background: palette.bg, borderRadius: 8, padding: 16,
          border: `1px solid ${palette.border}`,
        }}>
          <div><span style={{ color: palette.accent }}>score</span> = (1−α−β) × <span style={{ color: palette.blue }}>semantic</span></div>
          <div style={{ paddingLeft: 42 }}>+ α × <span style={{ color: palette.warm }}>freshness</span></div>
          <div style={{ paddingLeft: 42 }}>+ β × <span style={{ color: palette.purple }}>hebbian</span></div>
          <div style={{ marginTop: 12, borderTop: `1px solid ${palette.border}`, paddingTop: 12 }}>
            <div>α = <span style={{ color: palette.warm }}>0.30</span> (temporal)</div>
            <div>β = <span style={{ color: palette.purple }}>0.20</span> (hebbian)</div>
          </div>
          <div style={{ marginTop: 12, borderTop: `1px solid ${palette.border}`, paddingTop: 12, fontSize: 11 }}>
            <div><span style={{ color: palette.warm }}>freshness</span> = 1/(1 + age/halflife)</div>
            <div style={{ marginTop: 4 }}>Episode halflife: 168h</div>
            <div>Knowledge halflife: 720h</div>
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <SectionTitle>Interpretation</SectionTitle>
          <div style={{ fontSize: 12, color: palette.textMuted, lineHeight: 1.6 }}>
            Temporal reasoning scores highest because episodes carry explicit timestamps and <code style={{ fontFamily: MONO, fontSize: 11, color: palette.accent }}>expand_adjacent</code> pulls surrounding turns. Multi-hop is hardest — requires linking facts across sessions.
          </div>
        </div>
      </div>
    </div>
  </div>
);

// ─── Page: Configuration ───────────────────────────────────────────────
const ConfigPage = () => {
  const sections = [
    { title: "Scoring", items: [
      { key: "episode_half_life_hours", val: "168.0", desc: "1 week" },
      { key: "episode_alpha", val: "0.3", desc: "temporal weight" },
      { key: "knowledge_half_life_hours", val: "720.0", desc: "30 days" },
      { key: "knowledge_alpha", val: "0.2", desc: "knowledge temporal weight" },
    ]},
    { title: "Hebbian", items: [
      { key: "learning_rate", val: "0.1", desc: "co-activation learning rate" },
      { key: "beta_episode", val: "0.2", desc: "Hebbian weight in 3D score" },
      { key: "decay_rate", val: "0.01", desc: "per-cycle decay multiplier" },
      { key: "decay_interval_hours", val: "168", desc: "1 week" },
      { key: "activation_cap", val: "1000", desc: "max activation count" },
    ]},
    { title: "Background", items: [
      { key: "interval_seconds", val: "60", desc: "REM sweep interval" },
      { key: "batch_size", val: "5", desc: "episodes per batch" },
      { key: "min_episodes_for_processing", val: "3", desc: "trigger threshold" },
    ]},
    { title: "Session", items: [
      { key: "ttl_seconds", val: "86400", desc: "24 hours" },
    ]},
    { title: "NATS", items: [
      { key: "enabled", val: "true", desc: "event-driven curation" },
      { key: "url", val: "nats://localhost:4222", desc: "NATS server" },
      { key: "curation_min_episodes", val: "3", desc: "trigger threshold" },
      { key: "curation_max_wait_seconds", val: "30.0", desc: "max wait before forced curation" },
      { key: "curation_max_concurrent", val: "2", desc: "parallel curation workers" },
    ]},
  ];

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: palette.text }}>Configuration</h2>
      <p style={{ color: palette.textMuted, fontSize: 14, marginTop: 4, marginBottom: 28 }}>settings.toml · All values are live-editable</p>

      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {sections.map((sec, i) => (
          <div key={i} style={{ background: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: palette.accent, fontFamily: MONO, marginBottom: 14, letterSpacing: "0.04em" }}>[default.{sec.title.toLowerCase()}]</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {sec.items.map((item, j) => (
                <div key={j} style={{ display: "grid", gridTemplateColumns: "240px 120px 1fr", gap: 12, alignItems: "center" }}>
                  <span style={{ fontSize: 12, fontFamily: MONO, color: palette.text }}>{item.key}</span>
                  <input defaultValue={item.val} style={{
                    padding: "6px 10px", borderRadius: 6, border: `1px solid ${palette.borderLight}`,
                    background: palette.surfaceAlt, color: palette.accent, fontFamily: MONO, fontSize: 12,
                    outline: "none", textAlign: "right",
                  }} />
                  <span style={{ fontSize: 11, color: palette.textDim }}>#{" "}{item.desc}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── Page: REM Monitor ─────────────────────────────────────────────────
const REMPage = () => {
  const [cycle, setCycle] = useState(47);
  useEffect(() => { const t = setInterval(() => setCycle(c => c + 1), 4000); return () => clearInterval(t); }, []);

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: palette.text }}>REM Consolidation</h2>
      <p style={{ color: palette.textMuted, fontSize: 14, marginTop: 4, marginBottom: 28 }}>Background memory consolidation · Like biological REM sleep</p>

      <div style={{ display: "flex", gap: 14, marginBottom: 28 }}>
        <StatCard label="Sweep Cycles" value={cycle} sub="Every 60s" color={palette.purple} />
        <StatCard label="Pending Episodes" value="8" sub="Across 3 groups" color={palette.warm} />
        <StatCard label="Duplicates Caught" value="23" sub="≥0.90 cosine threshold" color={palette.coral} />
        <StatCard label="Hebbian Edges" value="412" sub="14 decayed this cycle" color={palette.blue} />
      </div>

      {/* Pipeline Visualization */}
      <SectionTitle>Consolidation Pipeline</SectionTitle>
      <div style={{
        background: palette.surface, border: `1px solid ${palette.border}`,
        borderRadius: 12, padding: "24px 28px", marginBottom: 24,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 0 }}>
          {[
            { label: "Find Groups", detail: "≥3 pending episodes", color: palette.textMuted, active: true },
            { label: "Dedup Check", detail: "cosine ≥ 0.90", color: palette.warm, active: true },
            { label: "Knowledge Extraction", detail: "DSPy pipeline", color: palette.accent, active: true },
            { label: "Ontology Update", detail: "Schema.org entities", color: palette.purple, active: false },
            { label: "Temporal Compress", detail: "≥2 unique → summary", color: palette.blue, active: false },
            { label: "Hebbian Decay", detail: "×(1 − 0.01) per cycle", color: palette.coral, active: false },
          ].map((step, i, arr) => (
            <div key={i} style={{ display: "flex", alignItems: "center", flex: 1 }}>
              <div style={{ textAlign: "center", flex: 1 }}>
                <div style={{
                  width: 38, height: 38, borderRadius: "50%", margin: "0 auto 8px",
                  border: `2px solid ${step.active ? step.color : palette.border}`,
                  background: step.active ? step.color + "20" : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 14, fontWeight: 700, color: step.active ? step.color : palette.textDim,
                  fontFamily: MONO, transition: "all 0.3s",
                }}>{i + 1}</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: step.active ? palette.text : palette.textDim, marginBottom: 2 }}>{step.label}</div>
                <div style={{ fontSize: 10, color: palette.textDim, fontFamily: MONO }}>{step.detail}</div>
              </div>
              {i < arr.length - 1 && (
                <div style={{ width: 24, height: 1, background: palette.border, flexShrink: 0, marginBottom: 24 }} />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* NATS Events + REM Log */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div>
          <SectionTitle>NATS Event Stream</SectionTitle>
          <div style={{
            background: palette.bg, border: `1px solid ${palette.border}`, borderRadius: 10,
            padding: 14, fontFamily: MONO, fontSize: 11, lineHeight: 1.8, color: palette.textMuted,
            height: 220, overflowY: "auto",
          }}>
            {[
              { subj: "memory.episode.stored.locomo-conv-0", time: "14:36:01.234" },
              { subj: "memory.episode.stored.locomo-conv-0", time: "14:36:01.456" },
              { subj: "memory.episode.stored.ops-team", time: "14:35:58.112" },
              { subj: "memory.curation.triggered.locomo-conv-0", time: "14:36:02.001" },
              { subj: "memory.curation.complete.locomo-conv-0", time: "14:36:06.445" },
              { subj: "memory.hebbian.decay.all", time: "14:36:06.500" },
              { subj: "memory.episode.stored.support-v2", time: "14:35:55.887" },
              { subj: "memory.curation.triggered.support-v2", time: "14:35:56.012" },
            ].map((ev, i) => (
              <div key={i}>
                <span style={{ color: palette.textDim }}>{ev.time}</span>{" "}
                <span style={{ color: ev.subj.includes("triggered") ? palette.warm : ev.subj.includes("complete") ? palette.accent : ev.subj.includes("decay") ? palette.coral : palette.blue }}>{ev.subj}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <SectionTitle>Consolidation Log</SectionTitle>
          <Table
            columns={[
              { label: "Time", key: "time", mono: true },
              { label: "Group", key: "group", mono: true },
              { label: "Action", key: "action" },
              { label: "", render: r => <Badge color="#22c55e">OK</Badge> },
            ]}
            rows={MOCK_REM_LOG}
          />
        </div>
      </div>
    </div>
  );
};

// ─── Main App ──────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: icons.dashboard },
  { id: "sessions", label: "Sessions", icon: icons.sessions },
  { id: "graph", label: "Memory Graph", icon: icons.graph },
  { id: "observe", label: "Observe", icon: icons.observe },
  { id: "rem", label: "REM Monitor", icon: icons.rem },
  { id: "benchmark", label: "Benchmark", icon: icons.benchmark },
  { id: "config", label: "Configuration", icon: icons.config },
];

export default function SegnogUI() {
  const [page, setPage] = useState("dashboard");

  const renderPage = () => {
    switch (page) {
      case "dashboard": return <DashboardPage />;
      case "sessions": return <SessionsPage />;
      case "graph": return <GraphPage />;
      case "observe": return <ObservePage />;
      case "rem": return <REMPage />;
      case "benchmark": return <BenchmarkPage />;
      case "config": return <ConfigPage />;
      default: return <DashboardPage />;
    }
  };

  return (
    <div style={{
      display: "flex", height: "100vh", fontFamily: FONT,
      background: palette.bg, color: palette.text, overflow: "hidden",
    }}>
      {/* Sidebar */}
      <div style={{
        width: 220, background: palette.surface, borderRight: `1px solid ${palette.border}`,
        display: "flex", flexDirection: "column", flexShrink: 0,
      }}>
        {/* Logo */}
        <div style={{ padding: "20px 18px 16px", borderBottom: `1px solid ${palette.border}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 34, height: 34, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center",
              background: `linear-gradient(135deg, ${palette.accent}25, ${palette.purple}25)`,
              border: `1px solid ${palette.accent}30`,
              fontSize: 18,
            }}>𝄋</div>
            <div>
              <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "-0.02em", color: palette.text }}>Segnog</div>
              <div style={{ fontSize: 10, color: palette.textDim, fontFamily: MONO, letterSpacing: "0.04em" }}>dal segno</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <div style={{ padding: "12px 10px", flex: 1 }}>
          {NAV_ITEMS.map(item => (
            <button key={item.id} onClick={() => setPage(item.id)} style={{
              display: "flex", alignItems: "center", gap: 10, width: "100%",
              padding: "9px 12px", borderRadius: 8, border: "none", cursor: "pointer",
              background: page === item.id ? palette.accentDim : "transparent",
              color: page === item.id ? palette.accent : palette.textMuted,
              fontSize: 13, fontWeight: page === item.id ? 600 : 500,
              fontFamily: FONT, textAlign: "left",
              transition: "all 0.15s", marginBottom: 2,
            }}>
              <Icon d={item.icon} size={16} />
              {item.label}
            </button>
          ))}
        </div>

        {/* Footer */}
        <div style={{ padding: "14px 18px", borderTop: `1px solid ${palette.border}`, fontSize: 11, color: palette.textDim, fontFamily: MONO }}>
          <div>localhost:9000</div>
          <div style={{ marginTop: 2, display: "flex", gap: 4, alignItems: "center" }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e" }} />
            container up 14h 32m
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, overflow: "auto", padding: "28px 36px" }}>
        {renderPage()}
      </div>
    </div>
  );
}
