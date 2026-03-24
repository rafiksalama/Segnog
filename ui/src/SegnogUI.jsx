import { useState, useEffect, useRef, createContext, useContext } from "react";

const API = "/api/v1/memory";

// ─── Deterministic type → color ────────────────────────────────────────
const TYPE_PALETTE = [
  "#5de4c7","#82aaff","#c792ea","#ffd580","#ff6b8a","#22c55e",
  "#f97316","#06b6d4","#a78bfa","#fb923c","#34d399","#f472b6",
  "#60a5fa","#facc15","#4ade80","#e879f9","#38bdf8","#fb7185",
];
const typeColor = t => {
  let h = 0;
  for (let i = 0; i < (t || "").length; i++) h = (h * 31 + (t || "").charCodeAt(i)) >>> 0;
  return TYPE_PALETTE[h % TYPE_PALETTE.length];
};

// ─── Theme Palettes ────────────────────────────────────────────────────
const DARK = {
  bg: "#0a0b0f",
  surface: "#12141a",
  surfaceAlt: "#181b24",
  border: "#1e2230",
  borderLight: "#282d3e",
  text: "#e2e4ea",
  textMuted: "#7a7f94",
  textDim: "#4a4f62",
  accent: "#5de4c7",
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
  green: "#22c55e",
  inputBg: "#181b24",
};

const LIGHT = {
  bg: "#f4f3ef",
  surface: "#ffffff",
  surfaceAlt: "#eeecea",
  border: "#dddbd5",
  borderLight: "#d0cec8",
  text: "#1c1c1a",
  textMuted: "#5a5a52",
  textDim: "#9a9a90",
  accent: "#1a9a84",
  accentDim: "#1a9a8420",
  accentMid: "#1a9a8460",
  warm: "#c17f24",
  warmDim: "#c17f2420",
  coral: "#c94060",
  coralDim: "#c9406020",
  blue: "#2c5faa",
  blueDim: "#2c5faa20",
  purple: "#7c4daa",
  purpleDim: "#7c4daa20",
  green: "#16a34a",
  inputBg: "#f0efeb",
};

const ThemeCtx = createContext(DARK);
const useP = () => useContext(ThemeCtx);

// ─── Fonts / Icons ─────────────────────────────────────────────────────
const FONT = `'DM Sans', 'Satoshi', system-ui, -apple-system, sans-serif`;
const MONO = `'JetBrains Mono', 'SF Mono', 'Fira Code', monospace`;

const Icon = ({ d, size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const icons = {
  dashboard: "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z M9 22V12h6v10",
  sessions:  "M21 12a9 9 0 11-18 0 9 9 0 0118 0z M12 6v6l4 2",
  graph:     "M12 2a3 3 0 00-3 3c0 1.1.6 2 1.5 2.6L6 12l-3-1v6l3-1 4.5 4.4c-.9.6-1.5 1.5-1.5 2.6a3 3 0 106 0c0-1.1-.6-2-1.5-2.6L18 17l3 1v-6l-3 1-4.5-4.4c.9-.6 1.5-1.5 1.5-2.6a3 3 0 00-3-3z",
  observe:   "M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z M12 9a3 3 0 110 6 3 3 0 010-6z",
  rem:       "M17 10.5V7a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h12a1 1 0 001-1v-3.5l4 4v-11l-4 4z",
  config:    "M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001.08 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1.08z",
  reporting: "M18 20V10 M12 20V4 M6 20v-6",
  check:     "M20 6L9 17l-5-5",
  send:      "M22 2L11 13 M22 2l-7 20-4-9-9-4 20-7z",
  brain:     "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z M12 6v6l4.5 2.5",
  zap:       "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  sun:       "M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42M12 5a7 7 0 100 14A7 7 0 0012 5z",
  moon:      "M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z",
};

// ─── Reusable Components ───────────────────────────────────────────────
const Badge = ({ children, color, bg }) => {
  const p = useP();
  const c = color || p.accent;
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, fontFamily: MONO, padding: "2px 8px",
      borderRadius: 4, color: c, background: bg || c + "18",
      letterSpacing: "0.03em", textTransform: "uppercase",
    }}>{children}</span>
  );
};

const StatCard = ({ label, value, sub, color, icon }) => {
  const p = useP();
  const c = color || p.accent;
  return (
    <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: "20px 22px", flex: 1, minWidth: 160, position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: -8, right: -8, opacity: 0.06, color: c }}>
        <svg width="80" height="80" viewBox="0 0 24 24" fill="currentColor"><path d={icon || icons.zap} /></svg>
      </div>
      <div style={{ fontSize: 11, color: p.textMuted, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8, fontFamily: MONO }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 700, color: c, lineHeight: 1, fontFamily: MONO }}>{value ?? "—"}</div>
      {sub && <div style={{ fontSize: 12, color: p.textMuted, marginTop: 6 }}>{sub}</div>}
    </div>
  );
};

const SectionTitle = ({ children, right }) => {
  const p = useP();
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
      <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: p.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: MONO }}>{children}</h3>
      {right}
    </div>
  );
};

const Table = ({ columns, rows, onRowClick }) => {
  const p = useP();
  return (
    <div style={{ borderRadius: 10, border: `1px solid ${p.border}`, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontFamily: FONT }}>
        <thead>
          <tr style={{ background: p.surfaceAlt }}>
            {columns.map((col, i) => (
              <th key={i} style={{ padding: "10px 14px", textAlign: "left", fontSize: 10, fontWeight: 700, color: p.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: MONO, borderBottom: `1px solid ${p.border}` }}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} onClick={() => onRowClick?.(row)} style={{ cursor: onRowClick ? "pointer" : "default", borderBottom: ri < rows.length - 1 ? `1px solid ${p.border}` : "none", transition: "background 0.15s" }}
              onMouseEnter={e => e.currentTarget.style.background = p.surfaceAlt}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              {columns.map((col, ci) => (
                <td key={ci} style={{ padding: "11px 14px", color: p.text, fontFamily: col.mono ? MONO : FONT, fontSize: col.mono ? 12 : 13 }}>{col.render ? col.render(row) : row[col.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const Empty = ({ msg }) => {
  const p = useP();
  return <div style={{ color: p.textDim, fontFamily: MONO, fontSize: 12, padding: "12px 0" }}>{msg}</div>;
};

// ─── Data hook (with optional auto-poll) ───────────────────────────────
function useFetch(url, deps = [], interval = 0) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(!!url);
  const [updatedAt, setUpdatedAt] = useState(null);
  useEffect(() => {
    if (!url) { setLoading(false); return; }
    let cancelled = false;
    const doFetch = () => {
      fetch(url)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (!cancelled) { setData(d); setLoading(false); setUpdatedAt(Date.now()); } })
        .catch(() => { if (!cancelled) setLoading(false); });
    };
    setLoading(true);
    doFetch();
    const id = interval > 0 ? setInterval(doFetch, interval) : null;
    return () => { cancelled = true; if (id) clearInterval(id); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, interval, ...deps]);
  return { data, loading, updatedAt };
}

// ─── Latency Chart ─────────────────────────────────────────────────────
const LatencyChart = ({ data }) => {
  const p = useP();
  const [sel, setSel] = useState(0);

  if (!data || data.length === 0) {
    return (
      <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: "20px 24px", marginBottom: 28 }}>
        <SectionTitle>API Latency</SectionTitle>
        <Empty msg="No latency data yet — make a few API requests first." />
      </div>
    );
  }

  const idx = Math.min(sel, data.length - 1);
  const entry = data[idx] || data[0];
  const samples = entry?.samples || [];

  const W = 560, H = 160;
  const PAD = { top: 14, right: 62, bottom: 26, left: 48 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top - PAD.bottom;

  const maxMs = samples.length > 0
    ? Math.max(...samples.map(s => s.ms), entry.p99 || 10, 10)
    : 100;
  const yScale = v => PAD.top + cH - Math.min((v / maxMs) * cH, cH);
  const xScale = i => PAD.left + (samples.length > 1 ? (i / (samples.length - 1)) * cW : cW / 2);

  const pts = samples.map((s, i) => `${xScale(i)},${yScale(s.ms)}`).join(" ");
  const lineColor = entry.p95 < 100 ? p.green : entry.p95 < 500 ? p.warm : p.coral;

  const yTicks = [0, Math.round(maxMs * 0.5), Math.round(maxMs)];
  const t0 = samples.length > 0 ? samples[0].ts : 0;
  const tLast = samples.length > 0 ? samples[samples.length - 1].ts : 0;
  const elapsed = Math.round(tLast - t0);

  // Percentile reference lines with labels
  const refLines = [
    { val: entry.p50, color: p.green,  label: `p50 ${entry.p50}ms` },
    { val: entry.p95, color: p.warm,   label: `p95 ${entry.p95}ms` },
    { val: entry.p99, color: p.coral,  label: `p99 ${entry.p99}ms` },
  ];

  return (
    <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: "20px 24px", marginBottom: 28 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: p.textMuted, letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: MONO }}>API Latency</div>
          <div style={{ fontSize: 11, color: p.textDim, marginTop: 2, fontFamily: MONO }}>realtime · 3s refresh · last 200 samples per endpoint</div>
        </div>
        {/* Big stat pills for selected endpoint */}
        <div style={{ display: "flex", gap: 10 }}>
          {[
            { label: "p50", val: entry.p50, color: p.green },
            { label: "p95", val: entry.p95, color: p.warm },
            { label: "p99", val: entry.p99, color: p.coral },
            { label: "max", val: entry.max,  color: p.textMuted },
          ].map(({ label, val, color }) => (
            <div key={label} style={{ textAlign: "center", background: color + "12", border: `1px solid ${color}30`, borderRadius: 8, padding: "6px 12px", minWidth: 54 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color, fontFamily: MONO, lineHeight: 1 }}>{val}</div>
              <div style={{ fontSize: 9, color: p.textDim, fontFamily: MONO, marginTop: 3 }}>{label} ms</div>
            </div>
          ))}
          <div style={{ textAlign: "center", background: p.surfaceAlt, border: `1px solid ${p.border}`, borderRadius: 8, padding: "6px 12px", minWidth: 54 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: p.text, fontFamily: MONO, lineHeight: 1 }}>{entry.count}</div>
            <div style={{ fontSize: 9, color: p.textDim, fontFamily: MONO, marginTop: 3 }}>calls</div>
          </div>
        </div>
      </div>

      {/* Endpoint selector tabs */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {data.map((d, i) => {
          const active = i === idx;
          const lc = d.p95 < 100 ? p.green : d.p95 < 500 ? p.warm : p.coral;
          return (
            <button key={i} onClick={() => setSel(i)} style={{
              fontSize: 10, fontFamily: MONO, fontWeight: 600, padding: "3px 10px",
              borderRadius: 6, cursor: "pointer", border: "1px solid",
              borderColor: active ? lc : p.border,
              background: active ? lc + "18" : "transparent",
              color: active ? lc : p.textMuted, transition: "all 0.15s",
            }}>
              <span style={{ opacity: 0.7, marginRight: 3, fontSize: 9 }}>{d.endpoint.startsWith("BG:") ? "BG" : d.endpoint.split(":")[0]}</span>
              {d.endpoint.replace(/^(GET|POST|PUT|DELETE|PATCH|BG):/, "")}{" "}
              <span style={{ opacity: 0.5 }}>{d.count}</span>
            </button>
          );
        })}
      </div>

      {/* Time-series SVG */}
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: H, display: "block" }}>
        {/* Y-axis grid + labels */}
        {yTicks.map((v, i) => (
          <g key={i}>
            <line x1={PAD.left} x2={PAD.left + cW} y1={yScale(v)} y2={yScale(v)}
              stroke={p.border} strokeWidth="1" />
            <text x={PAD.left - 5} y={yScale(v) + 4} textAnchor="end"
              fill={p.textDim} fontSize="9" fontFamily={MONO}>{v}ms</text>
          </g>
        ))}
        {/* Reference lines with value labels on the right */}
        {refLines.map(({ val, color, label }) => val > 0 && (
          <g key={label}>
            <line x1={PAD.left} x2={PAD.left + cW} y1={yScale(val)} y2={yScale(val)}
              stroke={color} strokeWidth="1" strokeDasharray="4,3" opacity="0.7" />
            <text x={PAD.left + cW + 5} y={yScale(val) + 3} textAnchor="start"
              fill={color} fontSize="8" fontFamily={MONO} opacity="0.9">{label}</text>
          </g>
        ))}
        {/* Fill + line */}
        {samples.length > 1 && (
          <>
            <polygon
              points={`${PAD.left},${yScale(0)} ${pts} ${xScale(samples.length - 1)},${yScale(0)}`}
              fill={lineColor} opacity="0.07" />
            <polyline points={pts} fill="none" stroke={lineColor} strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}
        {/* Latest point dot */}
        {samples.length > 0 && (
          <circle cx={xScale(samples.length - 1)} cy={yScale(samples[samples.length - 1].ms)}
            r="3.5" fill={lineColor} />
        )}
        {/* X-axis labels */}
        {elapsed > 0 && [
          { x: PAD.left,         label: "0s" },
          { x: PAD.left + cW/2,  label: `+${Math.round(elapsed / 2)}s` },
          { x: PAD.left + cW,    label: `+${elapsed}s` },
        ].map((l, i) => (
          <text key={i} x={l.x} y={H - 4} textAnchor="middle"
            fill={p.textDim} fontSize="9" fontFamily={MONO}>{l.label}</text>
        ))}
        {/* Axes */}
        <line x1={PAD.left} x2={PAD.left + cW} y1={PAD.top + cH} y2={PAD.top + cH} stroke={p.border} strokeWidth="1" />
        <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={PAD.top + cH} stroke={p.border} strokeWidth="1" />
      </svg>

      {/* Summary table — all endpoints */}
      <div style={{ marginTop: 16, borderTop: `1px solid ${p.border}`, paddingTop: 12 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: MONO }}>
          <thead>
            <tr>
              {["Endpoint", "Calls", "avg", "p50", "p95", "p99", "max"].map(h => (
                <th key={h} style={{ fontSize: 9, color: p.textDim, fontWeight: 700, textTransform: "uppercase",
                  letterSpacing: "0.08em", padding: "0 8px 6px 0", textAlign: h === "Endpoint" ? "left" : "right" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((d, i) => {
              const badge = d.endpoint.startsWith("BG:") ? p.purple : p.blue;
              const lc = d.p95 < 100 ? p.green : d.p95 < 500 ? p.warm : p.coral;
              const active = i === idx;
              return (
                <tr key={i} onClick={() => setSel(i)} style={{ cursor: "pointer", background: active ? lc + "08" : "transparent" }}>
                  <td style={{ padding: "4px 8px 4px 0", maxWidth: 240 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                      <span style={{ fontSize: 8, fontWeight: 700, padding: "1px 4px", borderRadius: 3, background: badge + "20", color: badge, flexShrink: 0 }}>
                        {d.endpoint.startsWith("BG:") ? "BG" : d.endpoint.split(":")[0]}
                      </span>
                      <span style={{ fontSize: 11, color: active ? p.text : p.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {d.endpoint.replace(/^(GET|POST|PUT|DELETE|PATCH|BG):/, "")}
                      </span>
                    </div>
                  </td>
                  <td style={{ fontSize: 11, color: p.textMuted, textAlign: "right", padding: "4px 8px 4px 0" }}>{d.count}</td>
                  <td style={{ fontSize: 11, color: p.textDim,   textAlign: "right", padding: "4px 8px 4px 0" }}>{d.mean}ms</td>
                  <td style={{ fontSize: 11, color: p.green,     textAlign: "right", padding: "4px 8px 4px 0", fontWeight: 600 }}>{d.p50}ms</td>
                  <td style={{ fontSize: 11, color: p.warm,      textAlign: "right", padding: "4px 8px 4px 0", fontWeight: 600 }}>{d.p95}ms</td>
                  <td style={{ fontSize: 11, color: lc,          textAlign: "right", padding: "4px 8px 4px 0", fontWeight: 600 }}>{d.p99}ms</td>
                  <td style={{ fontSize: 11, color: p.textMuted, textAlign: "right", padding: "4px 8px 4px 0" }}>{d.max}ms</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ─── Dashboard sub-components (module-level to avoid remount on re-render) ──
const DashCardTitle = ({ title, sub }) => {
  const p = useP();
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: p.textMuted, letterSpacing: "0.09em", textTransform: "uppercase", fontFamily: MONO }}>{title}</div>
      {sub && <div style={{ fontSize: 10, color: p.textDim, fontFamily: MONO, marginTop: 2 }}>{sub}</div>}
    </div>
  );
};

const DashMetricRow = ({ label, entry }) => {
  const p = useP();
  const lc = !entry ? p.textDim : entry.p95 < 100 ? p.green : entry.p95 < 500 ? p.warm : p.coral;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: `1px solid ${p.border}` }}>
      <span style={{ fontSize: 11, color: p.textMuted, fontFamily: MONO }}>{label}</span>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {entry?.count != null && <span style={{ fontSize: 10, color: p.textDim, fontFamily: MONO }}>{entry.count}×</span>}
        <span style={{ fontSize: 11, fontFamily: MONO, color: p.green, fontWeight: 600 }}>{entry?.p50 ?? "—"}<span style={{ fontSize: 9, color: p.textDim }}>ms</span></span>
        <span style={{ fontSize: 11, fontFamily: MONO, color: lc, fontWeight: 600 }}>{entry?.p95 ?? "—"}<span style={{ fontSize: 9, color: p.textDim }}>ms</span></span>
      </div>
    </div>
  );
};

const DashMiniStat = ({ value, label, color }) => {
  const p = useP();
  return (
    <div style={{ flex: 1, background: p.surfaceAlt, borderRadius: 8, padding: "10px 12px", minWidth: 0 }}>
      <div style={{ fontSize: 20, fontWeight: 700, color, fontFamily: MONO, lineHeight: 1 }}>{value ?? "—"}</div>
      <div style={{ fontSize: 10, color: p.textMuted, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</div>
    </div>
  );
};

// ─── Page: Dashboard ───────────────────────────────────────────────────
const DashboardPage = () => {
  const p = useP();
  const [pulse, setPulse] = useState(true);
  const { data: stats, updatedAt: statsAt } = useFetch(`${API}/ui/stats`,  [], 8000);
  const { data: latency }                   = useFetch(`${API}/ui/latency`, [], 5000);
  const ago = statsAt ? Math.round((Date.now() - statsAt) / 1000) : null;

  useEffect(() => { const t = setInterval(() => setPulse(v => !v), 2000); return () => clearInterval(t); }, []);

  const lat = key => latency?.find(d => d.endpoint === key);
  const card = { background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: "18px 20px" };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: p.text }}>Dashboard</h2>
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: p.green + "15", padding: "4px 12px", borderRadius: 20 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: p.green, boxShadow: pulse ? `0 0 8px ${p.green}` : "none", transition: "box-shadow 0.8s" }} />
          <span style={{ fontSize: 11, color: p.green, fontWeight: 600, fontFamily: MONO }}>LIVE</span>
        </div>
        {ago !== null && <span style={{ fontSize: 11, color: p.textDim, fontFamily: MONO }}>updated {ago === 0 ? "just now" : `${ago}s ago`}</span>}
      </div>
      <p style={{ color: p.textMuted, fontSize: 14, marginTop: 4, marginBottom: 24 }}>Latency refreshes every 5s · localhost:9000</p>

      {/* Row 1: Health | Observe | Search */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>

        {/* Health */}
        <div style={card}>
          <DashCardTitle title="Health" />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {[
              { name: "DragonflyDB", port: 6381 },
              { name: "FalkorDB",    port: 6380 },
              { name: "NATS",        port: 4222 },
              { name: "REST Server", port: 9000 },
              { name: "gRPC Server", port: 50051 },
              { name: "REM Worker",  port: "—"  },
            ].map((s, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 9px", background: p.surfaceAlt, borderRadius: 7 }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: p.green, flexShrink: 0, boxShadow: `0 0 4px ${p.green}` }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: p.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</div>
                  <div style={{ fontSize: 9, color: p.textDim, fontFamily: MONO }}>{s.port}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Observe */}
        <div style={card}>
          <DashCardTitle title="Observe" sub="p50 · p95" />
          <DashMetricRow label="POST /observe"  entry={lat("POST:observe")} />
          <DashMetricRow label="embed"          entry={lat("observe:embed")} />
          <DashMetricRow label="session_add"    entry={lat("observe:session_add")} />
          <DashMetricRow label="session_search" entry={lat("observe:session_search")} />
          <DashMetricRow label="score_3dim"     entry={lat("observe:score_3dim")} />
        </div>

        {/* Search */}
        <div style={card}>
          <DashCardTitle title="Search" sub="p50 · p95" />
          <DashMetricRow label="episodes/search"  entry={lat("POST:episodes/search")} />
          <DashMetricRow label="knowledge/search" entry={lat("POST:knowledge/search")} />
          <DashMetricRow label="knowledge store"  entry={lat("POST:knowledge")} />
          <DashMetricRow label="artifacts"        entry={lat("POST:artifacts")} />
          <DashMetricRow label="artifacts/search" entry={lat("POST:artifacts/search")} />
        </div>
      </div>

      {/* Row 2: Hydrate | REM */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>

        {/* Hydrate */}
        <div style={card}>
          <DashCardTitle title="Hydrate" sub="Background session hydration from FalkorDB" />
          <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
            <DashMiniStat value={stats?.episodes?.toLocaleString()} label="Episodes in FalkorDB" color={p.blue}   />
            <DashMiniStat value={stats?.knowledge_nodes}            label="Knowledge Nodes"       color={p.warm}   />
            <DashMiniStat value={stats?.active_groups}              label="Active Sessions"        color={p.accent} />
          </div>
          <DashMetricRow label="embed"  entry={lat("observe:embed")} />
          <DashMetricRow label="format" entry={lat("observe:format")} />
        </div>

        {/* REM */}
        <div style={card}>
          <DashCardTitle title="REM" sub="Memory consolidation · 60s cycle" />
          <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
            <DashMiniStat value={stats?.pending_episodes}  label="Pending"       color={p.warm}   />
            <DashMiniStat value={stats?.hebbian_edges}     label="Hebbian Edges" color={p.coral}  />
            <DashMiniStat value={stats?.ontology_entities} label="Ontology"      color={p.purple} />
          </div>
          <DashMetricRow label="sweep/cycle" entry={lat("BG:sweep/cycle")} />
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 12, flexWrap: "wrap" }}>
            {[
              { label: "Find Groups",       active: true  },
              { label: "Dedup",             active: true  },
              { label: "Knowledge Extract", active: true  },
              { label: "Ontology Update",   active: false },
              { label: "Compress",          active: false },
              { label: "Hebbian Decay",     active: false },
            ].map((step, i, arr) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 3 }}>
                <div style={{ width: 20, height: 20, borderRadius: "50%", border: `1.5px solid ${step.active ? p.accent : p.border}`, background: step.active ? p.accent + "20" : "transparent", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: step.active ? p.accent : p.textDim, fontFamily: MONO }}>{i + 1}</div>
                <span style={{ fontSize: 10, color: step.active ? p.text : p.textDim, whiteSpace: "nowrap" }}>{step.label}</span>
                {i < arr.length - 1 && <span style={{ fontSize: 10, color: p.textDim, margin: "0 2px" }}>›</span>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page: Reporting ───────────────────────────────────────────────────
const ReportingPage = () => {
  const p = useP();
  const { data: stats }   = useFetch(`${API}/ui/stats`,           [], 10000);
  const { data: latency } = useFetch(`${API}/ui/latency`,          [], 3000);
  const { data: evData }  = useFetch(`${API}/ui/events?count=30`,  [], 5000);
  const events = evData?.events || [];

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: p.text }}>Reporting</h2>
      <p style={{ color: p.textMuted, fontSize: 14, marginTop: 4, marginBottom: 28 }}>System metrics · API latency · Event history</p>

      <div style={{ display: "flex", gap: 14, marginBottom: 28, flexWrap: "wrap" }}>
        <StatCard label="Active Groups"     value={stats?.active_groups}                           sub="distinct group IDs"        color={p.accent} icon={icons.sessions} />
        <StatCard label="Episodes Stored"   value={stats ? stats.episodes.toLocaleString() : null} sub="in FalkorDB"               color={p.blue}   icon={icons.brain}   />
        <StatCard label="Knowledge Nodes"   value={stats?.knowledge_nodes}                         sub="facts, patterns, insights" color={p.warm}   icon={icons.zap}     />
        <StatCard label="Ontology Entities" value={stats?.ontology_entities}                       sub="Schema.org typed"          color={p.purple} icon={icons.graph}   />
      </div>

      <LatencyChart data={latency || []} />

      <SectionTitle>Event History</SectionTitle>
      {events.length === 0
        ? <Empty msg="No events yet. Send some observations." />
        : (
          <div style={{ background: p.bg, border: `1px solid ${p.border}`, borderRadius: 10, padding: 14, fontFamily: MONO, fontSize: 11, lineHeight: 1.9, color: p.textMuted, maxHeight: 320, overflowY: "auto" }}>
            {events.map((ev, i) => (
              <div key={i}>
                <span style={{ color: p.textDim }}>{ev.time}</span>{" "}
                <span style={{ color: ev.subject?.includes("curation") ? p.warm : ev.subject?.includes("stored") ? p.blue : ev.subject?.includes("decay") ? p.coral : p.accent }}>{ev.subject}</span>
              </div>
            ))}
          </div>
        )}
    </div>
  );
};

// ─── Page: Sessions ────────────────────────────────────────────────────
const EPISODE_PREVIEW_LEN = 200;

const EpisodeCard = ({ ep }) => {
  const p = useP();
  const [expanded, setExpanded] = useState(false);
  const content = ep.content || "";
  const truncated = content.length > EPISODE_PREVIEW_LEN && !expanded;
  return (
    <div style={{ background: p.surfaceAlt, borderRadius: 8, padding: "12px 16px", borderLeft: `3px solid ${ep.consolidated ? p.accent : p.textDim}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontFamily: MONO, color: p.textDim }}>{ep.uuid?.slice(0, 18)}…</span>
          <Badge color={ep.episode_type === "raw" ? p.blue : p.warm}>{ep.episode_type || "raw"}</Badge>
        </div>
        <span style={{ fontSize: 11, fontFamily: MONO, color: p.textMuted }}>{ep.created_at_iso?.slice(11, 19) || ""}</span>
      </div>
      <div style={{ fontSize: 13, color: p.text, lineHeight: 1.5, marginBottom: 6 }}>
        {truncated ? content.slice(0, EPISODE_PREVIEW_LEN) + "…" : content}
      </div>
      {content.length > EPISODE_PREVIEW_LEN && (
        <button onClick={() => setExpanded(v => !v)} style={{
          background: "none", border: "none", padding: 0, cursor: "pointer",
          fontSize: 11, fontFamily: MONO, color: p.accent, marginBottom: 6,
        }}>{expanded ? "show less" : "show more"}</button>
      )}
      <div style={{ display: "flex", gap: 12, fontSize: 11, fontFamily: MONO, color: p.textMuted }}>
        <span style={{ color: ep.consolidated ? p.green : p.textDim }}>{ep.consolidated ? "✓ consolidated" : "○ pending"}</span>
        <span style={{ color: ep.knowledge_extracted ? p.green : p.textDim }}>{ep.knowledge_extracted ? "✓ knowledge" : "○ no knowledge"}</span>
      </div>
    </div>
  );
};

function buildSessionTree(sessions) {
  const map = {};
  sessions.forEach(s => { map[s.group_id] = { ...s, children: [] }; });
  const roots = [];
  sessions.forEach(s => {
    if (s.parent_session_id && map[s.parent_session_id]) {
      map[s.parent_session_id].children.push(map[s.group_id]);
    } else {
      roots.push(map[s.group_id]);
    }
  });
  return { roots, map };
}

const SessionTreeNode = ({ node, depth, selectedId, onSelect, expandedIds, onToggle, formatAge, p }) => {
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expandedIds.has(node.group_id);
  const isActive = node.group_id === selectedId;
  const ageSecs = Date.now() / 1000 - (node.latest_at || 0);
  const freshLabel = ageSecs < 3600 ? "recent" : ageSecs < 86400 ? "today" : null;

  return (
    <div>
      <div
        onClick={() => onSelect(node.group_id)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          paddingLeft: depth * 18 + 6, paddingRight: 10, paddingTop: 9, paddingBottom: 9,
          borderRadius: 8, cursor: "pointer",
          background: isActive ? p.surfaceAlt : "transparent",
          border: `1px solid ${isActive ? p.accentMid : "transparent"}`,
          transition: "background 0.12s, border-color 0.12s",
          marginBottom: 2,
        }}
      >
        <span
          onClick={e => { if (hasChildren) { e.stopPropagation(); onToggle(node.group_id); } }}
          style={{
            width: 14, textAlign: "center", fontSize: 11, color: p.textDim,
            cursor: hasChildren ? "pointer" : "default", userSelect: "none", flexShrink: 0,
          }}
        >
          {hasChildren ? (isExpanded ? "▼" : "▶") : "·"}
        </span>
        <span style={{
          fontSize: 13, fontWeight: isActive ? 600 : 400, color: p.text, fontFamily: MONO,
          flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {node.group_id}
        </span>
        {freshLabel
          ? <Badge color={p.green} bg={p.green + "18"}>{freshLabel}</Badge>
          : <span style={{ fontSize: 11, fontFamily: MONO, color: p.textDim, flexShrink: 0 }}>{node.episode_count} eps</span>
        }
      </div>
      {hasChildren && isExpanded && node.children.map(child => (
        <SessionTreeNode key={child.group_id} node={child} depth={depth + 1}
          selectedId={selectedId} onSelect={onSelect}
          expandedIds={expandedIds} onToggle={onToggle}
          formatAge={formatAge} p={p} />
      ))}
    </div>
  );
};

const SessionsPage = () => {
  const p = useP();
  const { data: sessData, loading } = useFetch(`${API}/ui/sessions`, [], 10000);
  const sessions = sessData?.sessions || [];
  const { roots, map: sessMap } = buildSessionTree(sessions);

  const [selectedId, setSelectedId] = useState(null);
  const [expandedIds, setExpandedIds] = useState(new Set());

  // Auto-select newest session and auto-expand root nodes on first load
  const prevTopRef = useRef(null);
  useEffect(() => {
    if (sessions.length === 0) return;
    const topId = sessions[0].group_id;
    if (!selectedId || topId !== prevTopRef.current) {
      setSelectedId(topId);
    }
    prevTopRef.current = topId;
    // Auto-expand root nodes
    setExpandedIds(prev => {
      const next = new Set(prev);
      roots.forEach(r => { if (r.children.length > 0) next.add(r.group_id); });
      return next;
    });
  }, [sessions.length]);

  const toggleExpand = id => setExpandedIds(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const selected = selectedId ? sessMap[selectedId] : null;

  const { data: epData } = useFetch(
    selectedId ? `${API}/ui/episodes?group_id=${encodeURIComponent(selectedId)}&limit=20` : null,
    [selectedId], 10000
  );
  const episodes = epData?.episodes || [];

  const formatAge = ts => {
    if (!ts) return "—";
    const mins = Math.floor((Date.now() / 1000 - ts) / 60);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    return hrs < 24 ? `${hrs}h ${mins % 60}m` : `${Math.floor(hrs / 24)}d`;
  };

  // Build breadcrumb by walking parent_session_id chain upward
  const breadcrumb = [];
  if (selectedId && sessMap[selectedId]) {
    let cur = sessMap[selectedId];
    while (cur) {
      breadcrumb.unshift(cur.group_id);
      cur = cur.parent_session_id ? sessMap[cur.parent_session_id] : null;
    }
  }

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: p.text }}>Session Explorer</h2>
      <p style={{ color: p.textMuted, fontSize: 14, marginTop: 4, marginBottom: 24 }}>FalkorDB episode groups · live data</p>

      {loading && <Empty msg="Loading sessions…" />}
      {!loading && sessions.length === 0 && <Empty msg="No sessions found. Send some observations first." />}

      {sessions.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 20, height: "calc(100vh - 200px)" }}>
          {/* Tree panel */}
          <div style={{
            background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12,
            padding: "12px 8px", overflowY: "auto", height: "100%", boxSizing: "border-box",
          }}>
            <div style={{ fontSize: 11, fontFamily: MONO, color: p.textDim, paddingLeft: 6, marginBottom: 8 }}>
              {sessions.length} session{sessions.length !== 1 ? "s" : ""}
            </div>
            {roots.map(root => (
              <SessionTreeNode key={root.group_id} node={root} depth={0}
                selectedId={selectedId} onSelect={setSelectedId}
                expandedIds={expandedIds} onToggle={toggleExpand}
                formatAge={formatAge} p={p} />
            ))}
          </div>

          {/* Detail panel */}
          <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: 20, overflowY: "auto", height: "100%", boxSizing: "border-box" }}>
            {selected ? (
              <>
                {/* Breadcrumb */}
                {breadcrumb.length > 1 && (
                  <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
                    {breadcrumb.map((id, i) => (
                      <span key={id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span
                          onClick={() => setSelectedId(id)}
                          style={{
                            fontSize: 12, fontFamily: MONO, cursor: "pointer",
                            color: i === breadcrumb.length - 1 ? p.accent : p.textDim,
                            fontWeight: i === breadcrumb.length - 1 ? 600 : 400,
                          }}
                        >{id}</span>
                        {i < breadcrumb.length - 1 && <span style={{ fontSize: 12, color: p.textDim }}>›</span>}
                      </span>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: p.text, fontFamily: MONO }}>{selected.group_id}</div>
                    <div style={{ fontSize: 12, color: p.textMuted, marginTop: 2 }}>
                      {selected.parent_session_id
                        ? <>child of <span style={{ fontFamily: MONO, color: p.textDim }}>{selected.parent_session_id}</span> · </>
                        : "root session · "
                      }
                      {formatAge(selected.latest_at)} ago
                    </div>
                  </div>
                  <Badge color={p.accent}>Episodes: {selected.episode_count}</Badge>
                </div>
                <SectionTitle>Latest Episodes</SectionTitle>
                {episodes.length === 0
                  ? <Empty msg="No episodes yet." />
                  : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {episodes.map(ep => <EpisodeCard key={ep.uuid} ep={ep} />)}
                    </div>
                  )}
              </>
            ) : (
              <Empty msg="Select a session to view episodes." />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Layout options ────────────────────────────────────────────────────
const LAYOUT_OPTS = [
  { id: "hub",          label: "Hub"          },
  { id: "force",        label: "Force"        },
  { id: "spiral",       label: "Spiral"       },
  { id: "circular",     label: "Circular"     },
  { id: "hierarchical", label: "Hierarchical" },
  { id: "radial",       label: "Radial"       },
  { id: "grid",         label: "Grid"         },
  { id: "matrix",       label: "Matrix"       },
  { id: "fabric",       label: "Fabric"       },
];

// ─── Page: Memory Graph ────────────────────────────────────────────────
const GraphPage = () => {
  const p = useP();
  const [tab, setTab]       = useState("ontology");
  const [layout, setLayout] = useState("hub");
  const { data: epData }       = useFetch(`${API}/ui/episodes?limit=50`,              [], 20000);
  const { data: knData }       = useFetch(`${API}/ui/knowledge?limit=50`,              [], 20000);
  const { data: ontoData }     = useFetch(`${API}/ui/ontology`,                        [], 20000);
  const { data: ontoEdgeData }    = useFetch(`${API}/ui/ontology/edges?limit=2000`,        [], 20000);
  const { data: ontoCooccurData } = useFetch(`${API}/ui/ontology/cooccurrence?limit=2000`, [], 20000);
  const canvasRef        = useRef(null);
  const nodesRef         = useRef([]);
  const edgesRef         = useRef([]);
  const panRef           = useRef({x: 0, y: 0});
  const zoomRef          = useRef({z: 1});
  const drawRef          = useRef(null);      // shared so edge-effect can redraw
  const prevLayoutRef    = useRef(null);
  const prevNodeCountRef = useRef(0);
  const prevEdgeCountRef = useRef(-1);  // -1 forces first layout run
  // Debounce: coalesce node + edge data so the layout fires once with everything
  const stableRef   = useRef({ nodes: [], edges: [], cooccur: [] });
  const debounceRef = useRef(null);
  const [layoutKey, setLayoutKey] = useState(0);
  const [showSingletons, setShowSingletons] = useState(false);
  const [singletonCount, setSingletonCount] = useState(0);
  const [selectedNode, setSelectedNode] = useState(null);
  const [popupPos, setPopupPos]         = useState({ x: 0, y: 0 });
  const [showLabels, setShowLabels]     = useState(true);
  const [sidebarOpen, setSidebarOpen]   = useState(true);
  const [legendOpen, setLegendOpen]     = useState(false);
  const [typeFilter, setTypeFilter]     = useState(null);       // null = all types
  const [showRelates, setShowRelates]   = useState(true);       // type 0 edges
  const [showCooccur, setShowCooccur]   = useState(true);       // type 1 edges
  const setSelectedNodeRef = useRef(setSelectedNode);
  const setPopupPosRef     = useRef(setPopupPos);

  // Debounce: wait 120ms after the last data change before triggering layout.
  // Ensures nodes + edges arrive together so hub community detection has full graph.
  useEffect(() => {
    if (!ontoData) return;
    stableRef.current = {
      nodes:   ontoData?.nodes           || [],
      edges:   ontoEdgeData?.edges       || [],
      cooccur: ontoCooccurData?.edges    || [],
    };
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setLayoutKey(k => k + 1), 120);
    return () => clearTimeout(debounceRef.current);
  }, [ontoData, ontoEdgeData, ontoCooccurData]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const container = canvas.parentElement;
    const W = canvas.width  = container.clientWidth  * 2;
    const H = canvas.height = container.clientHeight * 2;
    const ctx = canvas.getContext("2d");
    ctx.scale(2, 2);
    const w = W / 2, h = H / 2;

    const ontology = stableRef.current.nodes;

    // Only reset pan/zoom + restart animation when something structural changes
    const nodeCountChanged = ontology.length !== prevNodeCountRef.current;
    const layoutChanged    = layout !== prevLayoutRef.current;
    if (nodeCountChanged) prevNodeCountRef.current = ontology.length;
    if (layoutChanged)    prevLayoutRef.current    = layout;
    if (nodeCountChanged || layoutChanged) {
      panRef.current  = {x: 0, y: 0};
      zoomRef.current = {z: 1};
    }
    const pan  = panRef.current;
    const zoom = zoomRef.current;
    // Build nodes when ontology data changes
    const rawEdges   = stableRef.current.edges;
    const rawCooccur = stableRef.current.cooccur;
    if (nodesRef.current.length !== ontology.length) {
      const sorted = [...ontology].sort((a, b) =>
        (a.schema_type || "Thing").localeCompare(b.schema_type || "Thing")
      );
      nodesRef.current = sorted.map(n => ({
        x: w / 2, y: h / 2, vx: 0, vy: 0,
        r: Math.min(28, 11 + (n.source_count || 1) * 2.5),
        color: typeColor(n.category || n.schema_type),
        label: (n.display_name || n.name || "").slice(0, 14),
        data: n, fixed: false, isHub: false,
      }));
    }
    // Rebuild edges: RELATES (type=0, solid) + co-occurrence (type=1, dashed)
    // Dedup by canonical pair so a RELATES edge isn't doubled by co-occurrence
    const uuidIdx = {};
    nodesRef.current.forEach((n, i) => { uuidIdx[n.data.uuid] = i; });
    const hasEdge = new Set();
    if (rawEdges.length > 0 || rawCooccur.length > 0) {
      const merged = [];
      // rawEdges   = semantic RELATES edges (knows, worksFor, memberOf…) — solid, always shown
      // rawCooccur = co-occurrence edges (shared episode context) — dashed, shown only between communities in hub
      // Process semantic edges first so they take dedup precedence
      rawEdges.forEach(e => {
        const a = uuidIdx[e.source], b = uuidIdx[e.target];
        if (a === undefined || b === undefined || a === b) return;
        const key = `${Math.min(a,b)},${Math.max(a,b)}`;
        if (hasEdge.has(key)) return;
        hasEdge.add(key);
        merged.push([a, b, 0]);   // 0 = RELATES semantic (solid)
      });
      rawCooccur.forEach(e => {
        const a = uuidIdx[e.source], b = uuidIdx[e.target];
        if (a === undefined || b === undefined || a === b) return;
        const key = `${Math.min(a,b)},${Math.max(a,b)}`;
        if (hasEdge.has(key)) return;
        hasEdge.add(key);
        merged.push([a, b, 1]);   // 1 = co-occurrence (dashed, inter-community only in hub)
      });
      edgesRef.current = merged;
    } else if (edgesRef.current.length === 0) {
      // Fallback: same-type chains while data is loading
      const byType = {};
      nodesRef.current.forEach((n, i) => {
        const t = n.data.schema_type || "Thing";
        if (!byType[t]) byType[t] = [];
        if (byType[t].length > 0) edgesRef.current.push([byType[t].at(-1), i, 1]);
        byType[t].push(i);
      });
    }

    // Gate hub repositioning: only reposition when structure changed, not on every poll
    const newEdgeCount = edgesRef.current.length;
    const edgeCountChanged = newEdgeCount !== prevEdgeCountRef.current;
    if (edgeCountChanged) prevEdgeCountRef.current = newEdgeCount;
    const needsReposition = nodeCountChanged || layoutChanged || edgeCountChanged;

    const nodes = nodesRef.current;
    const edges = edgesRef.current;
    const types = [...new Set(nodes.map(n => n.data.schema_type || "Thing"))].sort();
    const nodesByType = {};
    nodes.forEach(n => {
      const t = n.data.schema_type || "Thing";
      if (!nodesByType[t]) nodesByType[t] = [];
      nodesByType[t].push(n);
    });

    // ── Layout positioning ───────────────────────────────────────────────
    nodes.forEach(n => { n.vx = 0; n.vy = 0; n.fixed = false; });

    if (layout === "hub" && needsReposition) {
      nodes.forEach(n => { n.isHub = false; n.community = -1; n.isSingleton = false; });

      // ── Group nodes by category (top-level Schema.org superclass) ──────
      const catMap = {};  // category → { nodes: [], subTypes: { type → [nodes] } }
      nodes.forEach(n => {
        const cat = n.data.category || n.data.schema_type || "Thing";
        const stype = n.data.schema_type || "Thing";
        if (!catMap[cat]) catMap[cat] = { nodes: [], subTypes: {} };
        catMap[cat].nodes.push(n);
        if (!catMap[cat].subTypes[stype]) catMap[cat].subTypes[stype] = [];
        catMap[cat].subTypes[stype].push(n);
      });
      // Sort categories by node count (largest first)
      const categories = Object.entries(catMap)
        .sort((a, b) => b[1].nodes.length - a[1].nodes.length);

      // Mark singletons: categories with only 1 node and no edges
      const deg = new Array(nodes.length).fill(0);
      edges.forEach(([a, b]) => { if (a != null && b != null && a !== b) { deg[a]++; deg[b]++; } });
      const singletonNodes = [];
      categories.forEach(([, catData]) => {
        catData.nodes.forEach(n => {
          const idx = nodes.indexOf(n);
          if (catData.nodes.length === 1 && idx >= 0 && deg[idx] === 0) {
            n.isSingleton = true;
            singletonNodes.push(n);
          }
        });
      });
      setSingletonCount(singletonNodes.length);

      // Filter to non-singleton categories for layout
      const realCats = categories.filter(([, d]) =>
        d.nodes.some(n => !n.isSingleton)
      ).map(([cat, d]) => [cat, { ...d, nodes: d.nodes.filter(n => !n.isSingleton) }]);

      const nC = realCats.length;
      if (nC === 0) {
        // All singletons — centered grid
        const cellSize = 50;
        const cols = Math.ceil(Math.sqrt(nodes.length * 1.5));
        const gridW = cols * cellSize, gridH = Math.ceil(nodes.length / cols) * cellSize;
        nodes.forEach((n, i) => {
          const col = i % cols, row = Math.floor(i / cols);
          n.x = w / 2 - gridW / 2 + col * cellSize + cellSize / 2;
          n.y = h / 2 - gridH / 2 + row * cellSize + cellSize / 2;
          n.vx = 0; n.vy = 0;
        });
      } else {
        // Assign community IDs by category (for edge rendering)
        realCats.forEach(([, catData], cid) => {
          catData.nodes.forEach(n => { n.community = cid; });
        });

        // ── Position categories on ring ─────────────────────────────────
        const maxCluster = Math.min(w, h) * 0.08;
        const clusterR = ([, d]) => Math.min(maxCluster, 14 + Math.sqrt(d.nodes.length) * 7);
        let maxPairSep = 0;
        if (nC >= 2) {
          const byCR = [...realCats].sort((a, b) => clusterR(b) - clusterR(a));
          for (let i = 0; i < nC; i++)
            maxPairSep = Math.max(maxPairSep, clusterR(byCR[i]) + clusterR(byCR[(i + 1) % nC]) + 40);
        }
        const minRing = nC >= 2 ? (maxPairSep / 2) / Math.sin(Math.PI / nC) : 0;
        const catRing = nC <= 1 ? 0 : Math.min(Math.min(w, h) * 0.34, Math.max(minRing, 50));

        // Category center positions
        const catCenters = [];
        realCats.forEach(([cat, catData], ci) => {
          let cx, cy;
          if (nC === 1) { cx = w / 2; cy = h / 2; }
          else {
            const a = (ci / nC) * Math.PI * 2 - Math.PI / 2;
            cx = w / 2 + catRing * Math.cos(a);
            cy = h / 2 + catRing * Math.sin(a);
          }
          catCenters.push({ cat, cx, cy, data: catData });
        });

        // ── Position nodes within each category cluster ──────────────────
        catCenters.forEach(({ cx, cy, data: catData }) => {
          const subTypeEntries = Object.entries(catData.subTypes)
            .map(([t, ns]) => [t, ns.filter(n => !n.isSingleton)])
            .filter(([, ns]) => ns.length > 0)
            .sort((a, b) => b[1].length - a[1].length);

          if (subTypeEntries.length === 0) return;

          if (subTypeEntries.length === 1) {
            // Single sub-type: arrange nodes in a circle around center
            const ns = subTypeEntries[0][1];
            if (ns.length === 1) {
              ns[0].x = cx; ns[0].y = cy; ns[0].vx = 0; ns[0].vy = 0;
            } else {
              const r = Math.min(maxCluster, 10 + ns.length * 5);
              ns.forEach((n, i) => {
                const a = (i / ns.length) * Math.PI * 2;
                n.x = cx + r * Math.cos(a); n.y = cy + r * Math.sin(a);
                n.vx = 0; n.vy = 0;
              });
            }
          } else {
            // Multiple sub-types: arrange sub-type clusters around category center
            const stR = Math.min(maxCluster * 0.7, 12 + subTypeEntries.length * 5);
            subTypeEntries.forEach(([, ns], si) => {
              const sa = (si / subTypeEntries.length) * Math.PI * 2 - Math.PI / 2;
              const stCx = cx + stR * Math.cos(sa);
              const stCy = cy + stR * Math.sin(sa);
              if (ns.length === 1) {
                ns[0].x = stCx; ns[0].y = stCy; ns[0].vx = 0; ns[0].vy = 0;
              } else {
                const nr = Math.min(maxCluster * 0.4, 8 + ns.length * 3);
                ns.forEach((n, i) => {
                  const a = (i / ns.length) * Math.PI * 2;
                  n.x = stCx + nr * Math.cos(a); n.y = stCy + nr * Math.sin(a);
                  n.vx = 0; n.vy = 0;
                });
              }
            });
          }
        });

        // Store category centers for label rendering
        nodesRef._catCenters = catCenters;

        // Singletons: compact grid below clusters (only when shown)
        if (showSingletons && singletonNodes.length > 0) {
          let maxRealY = 0;
          catCenters.forEach(({ cy }) => { maxRealY = Math.max(maxRealY, cy + maxCluster + 30); });
          const cellSize = 50;
          const cols = Math.ceil(Math.sqrt(singletonNodes.length * 2));
          const gridW = cols * cellSize;
          singletonNodes.forEach((n, si) => {
            const col = si % cols, row = Math.floor(si / cols);
            n.x = w / 2 - gridW / 2 + col * cellSize + cellSize / 2;
            n.y = maxRealY + 40 + row * cellSize;
            n.vx = 0; n.vy = 0;
          });
        }
      }
    } else if (layout === "force") {
      // Random seed only when layout or node count changes; otherwise keep positions
      if (nodeCountChanged || layoutChanged) {
        nodes.forEach(n => {
          n.x = w * 0.15 + Math.random() * w * 0.70;
          n.y = h * 0.15 + Math.random() * h * 0.70;
        });
      }
    } else if (layout === "spiral") {
      const B = 16, STEP = 0.42;
      nodes.forEach((n, i) => {
        const theta = i * STEP, r = B * theta / (2 * Math.PI) + 28;
        n.x = w / 2 + r * Math.cos(theta); n.y = h / 2 + r * Math.sin(theta);
      });
    } else if (layout === "circular") {
      // Cytoscape "Group Attributes" style: each type in its own sub-circle,
      // sub-circles arranged around a large outer ring
      const outerR = Math.min(w, h) * 0.30;
      types.forEach((t, ti) => {
        const group = nodesByType[t] || [];
        const ca = (ti / types.length) * Math.PI * 2 - Math.PI / 2;
        const cx = w / 2 + outerR * Math.cos(ca);
        const cy = h / 2 + outerR * Math.sin(ca);
        const innerR = Math.max(20, Math.min(65, group.length * 16 / Math.PI));
        group.forEach((n, gi) => {
          if (group.length === 1) { n.x = cx; n.y = cy; }
          else {
            const a = (gi / group.length) * Math.PI * 2;
            n.x = cx + innerR * Math.cos(a); n.y = cy + innerR * Math.sin(a);
          }
        });
      });
    } else if (layout === "grid") {
      // nodes array is already type-sorted from nodesRef init
      const cols = Math.ceil(Math.sqrt(nodes.length * (w / h)));
      const cellW = w * 0.88 / cols, cellH = h * 0.82 / Math.ceil(nodes.length / cols);
      nodes.forEach((n, i) => {
        n.x = w * 0.06 + (i % cols) * cellW + cellW / 2;
        n.y = h * 0.1 + Math.floor(i / cols) * cellH + cellH / 2;
      });
    } else if (layout === "hierarchical") {
      // Horizontal lanes per type — nodes centered within each lane
      const rowH = h * 0.76 / types.length;
      types.forEach((t, ti) => {
        const group = nodesByType[t] || [];
        const y = h * 0.14 + ti * rowH + rowH / 2;
        const spacing = group.length <= 1 ? 0 : Math.min(90, w * 0.80 / (group.length - 1));
        const totalW = spacing * (group.length - 1);
        group.forEach((n, gi) => {
          n.x = w / 2 - totalW / 2 + gi * spacing;
          n.y = y;
        });
      });
    } else if (layout === "radial") {
      // Most-connected node at center; rest distributed in concentric rings
      const byCount = [...nodes].sort((a, b) => (b.data.source_count || 0) - (a.data.source_count || 0));
      byCount[0].x = w / 2; byCount[0].y = h / 2;
      const rest = byCount.slice(1), maxR = Math.min(w, h) * 0.42;
      const nRings = Math.max(1, Math.ceil(Math.sqrt(rest.length)));
      const perRing = Math.ceil(rest.length / nRings);
      rest.forEach((n, i) => {
        const ring = Math.floor(i / perRing) + 1;
        const inRing = i % perRing, ringN = Math.min(perRing, rest.length - (ring - 1) * perRing);
        const r = (ring / (nRings + 0.5)) * maxR;
        const a = (inRing / ringN) * Math.PI * 2 - Math.PI / 2;
        n.x = w / 2 + r * Math.cos(a); n.y = h / 2 + r * Math.sin(a);
      });
    } else if (layout === "matrix") {
      // Block-per-type: each type gets a rectangular tile in a grid of tiles
      const typeCols = Math.ceil(Math.sqrt(types.length));
      const typeRows = Math.ceil(types.length / typeCols);
      const blockW = w * 0.88 / typeCols, blockH = h * 0.82 / typeRows;
      types.forEach((t, ti) => {
        const tc = ti % typeCols, tr = Math.floor(ti / typeCols);
        const bx = w * 0.06 + tc * blockW, by = h * 0.09 + tr * blockH;
        const group = [...(nodesByType[t] || [])].sort((a, b) => (b.data.source_count || 0) - (a.data.source_count || 0));
        const nc = Math.max(1, Math.ceil(Math.sqrt(group.length)));
        const nr = Math.ceil(group.length / nc);
        const sx = Math.min(52, blockW * 0.68 / nc);
        const sy = Math.min(52, blockH * 0.52 / Math.max(nr, 1));
        group.forEach((n, gi) => {
          const gc = gi % nc, gr = Math.floor(gi / nc);
          n.x = bx + blockW / 2 + (gc - (nc - 1) / 2) * sx;
          n.y = by + blockH * 0.42 + (gr - (nr - 1) / 2) * sy;
        });
      });
    } else if (layout === "fabric") {
      // Vertical strands — one column per type, nodes evenly spaced vertically
      const colW = w * 0.84 / Math.max(types.length, 1);
      types.forEach((t, ti) => {
        const group = nodesByType[t] || [];
        const x = w * 0.08 + ti * colW + colW / 2;
        group.forEach((n, gi) => {
          const frac = group.length === 1 ? 0.5 : gi / (group.length - 1);
          n.x = x; n.y = h * 0.12 + frac * h * 0.76;
        });
      });
    }

    // ── Auto-fit: zoom + pan to fill viewport after layout ───────────────
    if (needsReposition && layout !== "force" && layout !== "spiral" && nodes.length > 0) {
      // In hub layout: fit only to real-community nodes so the singleton
      // grid below doesn't force the camera to zoom way out
      const fitNodes = (layout === "hub")
        ? nodes.filter(n => !n.isSingleton)
        : nodes;
      const ref = fitNodes.length > 0 ? fitNodes : nodes;
      const pad = 60;
      const xs = ref.map(n => n.x), ys = ref.map(n => n.y);
      const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
      const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
      const fz = Math.min(w / (maxX - minX), h / (maxY - minY), 3.5);
      zoom.z = fz;
      pan.x  = w / 2 - ((minX + maxX) / 2) * fz;
      pan.y  = h / 2 - ((minY + maxY) / 2) * fz;
    }

    // ── Draw ─────────────────────────────────────────────────────────────
    const draw = () => {
      // Always read fresh edges so edge-only polls are reflected without restarting layout
      const edges = edgesRef.current;
      ctx.clearRect(0, 0, w, h);
      if (nodes.length === 0) {
        ctx.fillStyle = p.textDim; ctx.font = `14px ${FONT}`; ctx.textAlign = "center";
        ctx.fillText("No ontology entities yet", w / 2, h / 2); return;
      }

      ctx.save();
      ctx.translate(pan.x, pan.y);
      ctx.scale(zoom.z, zoom.z);

      // Layout background decorations
      // Semantic zoom levels for hub:
      //   < 1.6  → cloud: category blobs with name + count
      //   1.6–3  → sub-type circles inside category boundaries
      //   > 3    → individual nodes with labels
      const zLvl = zoom.z;
      if (layout === "hub") {
        const catCenters = nodesRef._catCenters || [];
        catCenters.forEach(({ cat, cx, cy, data: catData }) => {
          const visNodes = catData.nodes.filter(n => !n.isSingleton);
          if (visNodes.length === 0) return;
          let maxDist = 0;
          visNodes.forEach(n => {
            const d = Math.hypot(n.x - cx, n.y - cy);
            maxDist = Math.max(maxDist, d + n.r);
          });
          const bgR = maxDist + 20;
          const col = typeColor(cat);

          // Gather sub-type clusters with center + radius
          const stClusters = Object.entries(catData.subTypes)
            .map(([st, ns]) => {
              const vis = ns.filter(n => !n.isSingleton);
              if (vis.length === 0) return null;
              const sx = vis.reduce((s, n) => s + n.x, 0) / vis.length;
              const sy = vis.reduce((s, n) => s + n.y, 0) / vis.length;
              let sr = 0;
              vis.forEach(n => { sr = Math.max(sr, Math.hypot(n.x - sx, n.y - sy) + n.r); });
              return { st, sx, sy, sr: sr + 8, count: vis.length, col: typeColor(st) };
            }).filter(Boolean);

          if (zLvl < 1.6) {
            // ── Level 1: Cloud — category blobs ──
            ctx.beginPath(); ctx.arc(cx, cy, bgR, 0, Math.PI * 2);
            ctx.fillStyle = col + "25"; ctx.fill();
            ctx.strokeStyle = col + "50"; ctx.lineWidth = 1.5; ctx.stroke();
            const fontSize = Math.max(10, Math.min(18, bgR * 0.35));
            ctx.fillStyle = col; ctx.font = `700 ${fontSize}px ${FONT}`; ctx.textAlign = "center";
            ctx.fillText(cat, cx, cy - 4);
            ctx.fillStyle = col + "99"; ctx.font = `600 ${Math.max(8, fontSize * 0.6)}px ${MONO}`;
            ctx.fillText(`${visNodes.length}`, cx, cy + fontSize * 0.7);

          } else if (zLvl < 3) {
            // ── Level 2: Sub-type circles inside category boundary ──
            // Category boundary (light)
            ctx.beginPath(); ctx.arc(cx, cy, bgR, 0, Math.PI * 2);
            ctx.fillStyle = col + "08"; ctx.fill();
            ctx.setLineDash([4, 8]);
            ctx.strokeStyle = col + "25"; ctx.lineWidth = 0.8; ctx.stroke();
            ctx.setLineDash([]);
            // Category label above
            ctx.fillStyle = col + "bb"; ctx.font = `700 11px ${FONT}`; ctx.textAlign = "center";
            ctx.fillText(cat, cx, cy - bgR - 5);
            // Sub-type bubbles
            stClusters.forEach(({ st, sx, sy, sr, count, col: stCol }) => {
              ctx.beginPath(); ctx.arc(sx, sy, sr, 0, Math.PI * 2);
              ctx.fillStyle = stCol + "20"; ctx.fill();
              ctx.strokeStyle = stCol + "55"; ctx.lineWidth = 1.2; ctx.stroke();
              const stFontSize = Math.max(7, Math.min(12, sr * 0.4));
              ctx.fillStyle = stCol; ctx.font = `700 ${stFontSize}px ${FONT}`; ctx.textAlign = "center";
              ctx.fillText(st, sx, sy - 2);
              ctx.fillStyle = stCol + "88"; ctx.font = `600 ${Math.max(6, stFontSize * 0.7)}px ${MONO}`;
              ctx.fillText(`${count}`, sx, sy + stFontSize * 0.65);
            });

          } else {
            // ── Level 3: Detail — soft boundaries + sub-type labels ──
            ctx.beginPath(); ctx.arc(cx, cy, bgR, 0, Math.PI * 2);
            ctx.fillStyle = col + "06"; ctx.fill();
            ctx.setLineDash([4, 8]);
            ctx.strokeStyle = col + "20"; ctx.lineWidth = 0.6; ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = col + "bb"; ctx.font = `700 10px ${FONT}`; ctx.textAlign = "center";
            ctx.fillText(cat, cx, cy - bgR - 4);
            // Faint sub-type boundaries
            stClusters.forEach(({ st, sx, sy, sr, col: stCol }) => {
              ctx.beginPath(); ctx.arc(sx, sy, sr, 0, Math.PI * 2);
              ctx.strokeStyle = stCol + "20"; ctx.lineWidth = 0.6; ctx.stroke();
              const minY = sy - sr;
              ctx.fillStyle = stCol + "88"; ctx.font = `600 7px ${MONO}`; ctx.textAlign = "center";
              ctx.fillText(st, sx, minY - 3);
            });
          }
        });
      } else if (layout === "spiral") {
        const B = 16, STEP = 0.42, tMax = (nodes.length - 1) * STEP + 0.01;
        ctx.beginPath();
        for (let s = 0; s <= 300; s++) {
          const theta = (tMax / 300) * s, r = B * theta / (2 * Math.PI) + 28;
          const x = w / 2 + r * Math.cos(theta), y = h / 2 + r * Math.sin(theta);
          s === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = p.border + "40"; ctx.lineWidth = 0.8; ctx.stroke();
      } else if (layout === "circular") {
        // Outer dashed ring + colored sub-circle outlines per type
        const outerR = Math.min(w, h) * 0.30;
        ctx.beginPath(); ctx.arc(w / 2, h / 2, outerR, 0, Math.PI * 2);
        ctx.setLineDash([4, 7]); ctx.strokeStyle = p.border + "30"; ctx.lineWidth = 0.8; ctx.stroke();
        ctx.setLineDash([]);
        types.forEach((t, ti) => {
          const group = nodesByType[t] || [];
          const ca = (ti / types.length) * Math.PI * 2 - Math.PI / 2;
          const cx = w / 2 + outerR * Math.cos(ca), cy = h / 2 + outerR * Math.sin(ca);
          const innerR = Math.max(20, Math.min(65, group.length * 16 / Math.PI)) + 14;
          ctx.beginPath(); ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
          ctx.strokeStyle = typeColor(t) + "28"; ctx.lineWidth = 0.9; ctx.stroke();
          ctx.fillStyle = typeColor(t) + "cc"; ctx.font = `600 9px ${MONO}`; ctx.textAlign = "center";
          ctx.fillText(t, cx, cy + innerR + 12);
        });
      } else if (layout === "radial") {
        const maxR = Math.min(w, h) * 0.42, nRings = Math.max(1, Math.ceil(Math.sqrt(nodes.length - 1)));
        for (let ri = 1; ri <= nRings; ri++) {
          ctx.beginPath(); ctx.arc(w / 2, h / 2, (ri / (nRings + 0.5)) * maxR, 0, Math.PI * 2);
          ctx.strokeStyle = p.border + "40"; ctx.lineWidth = 0.7; ctx.stroke();
        }
      } else if (layout === "hierarchical") {
        const rowH = h * 0.76 / types.length;
        types.forEach((t, ti) => {
          const y = h * 0.14 + ti * rowH;
          // Faint type-colored band
          ctx.fillStyle = typeColor(t) + "09";
          ctx.fillRect(0, y, w, rowH);
          // Bottom separator
          ctx.beginPath(); ctx.moveTo(w * 0.02, y + rowH); ctx.lineTo(w * 0.98, y + rowH);
          ctx.strokeStyle = p.border + "28"; ctx.lineWidth = 0.5; ctx.stroke();
          // Type label left-aligned
          ctx.fillStyle = typeColor(t) + "cc"; ctx.font = `600 9px ${MONO}`; ctx.textAlign = "left";
          ctx.fillText(t, w * 0.02, y + rowH / 2 + 4);
        });
      } else if (layout === "matrix") {
        const typeCols = Math.ceil(Math.sqrt(types.length));
        const typeRows = Math.ceil(types.length / typeCols);
        const blockW = w * 0.88 / typeCols, blockH = h * 0.82 / typeRows;
        types.forEach((t, ti) => {
          const tc = ti % typeCols, tr = Math.floor(ti / typeCols);
          const bx = w * 0.06 + tc * blockW, by = h * 0.09 + tr * blockH;
          // Tinted block background
          ctx.fillStyle = typeColor(t) + "0c";
          ctx.fillRect(bx + 2, by + 2, blockW - 4, blockH - 4);
          // Block border
          ctx.strokeStyle = typeColor(t) + "40"; ctx.lineWidth = 0.8;
          ctx.strokeRect(bx + 2, by + 2, blockW - 4, blockH - 4);
          // Type label top-left
          ctx.fillStyle = typeColor(t) + "dd"; ctx.font = `600 9px ${MONO}`; ctx.textAlign = "left";
          ctx.fillText(t, bx + 6, by + 14);
        });
      } else if (layout === "grid") {
        // Subtle grid lines
        const cols = Math.ceil(Math.sqrt(nodes.length * (w / h)));
        const numRows = Math.ceil(nodes.length / cols);
        const cellW = w * 0.88 / cols, cellH = h * 0.82 / numRows;
        for (let r = 0; r <= numRows; r++) {
          ctx.beginPath(); ctx.moveTo(w * 0.06, h * 0.1 + r * cellH); ctx.lineTo(w * 0.94, h * 0.1 + r * cellH);
          ctx.strokeStyle = p.border + "22"; ctx.lineWidth = 0.5; ctx.stroke();
        }
        for (let c = 0; c <= cols; c++) {
          ctx.beginPath(); ctx.moveTo(w * 0.06 + c * cellW, h * 0.1); ctx.lineTo(w * 0.06 + c * cellW, h * 0.1 + numRows * cellH);
          ctx.strokeStyle = p.border + "22"; ctx.lineWidth = 0.5; ctx.stroke();
        }
      } else if (layout === "fabric") {
        const colW = w * 0.84 / Math.max(types.length, 1);
        const WAVE_AMP = 18, WAVE_FREQ = (Math.PI * 2) / Math.max(types.length, 4);
        types.forEach((t, ti) => {
          const x = w * 0.08 + ti * colW + colW / 2;
          const labelY = h * 0.055 + Math.sin(ti * WAVE_FREQ) * WAVE_AMP;
          ctx.beginPath(); ctx.moveTo(x, labelY + 6); ctx.lineTo(x, h * 0.94);
          ctx.strokeStyle = typeColor(t) + "30"; ctx.lineWidth = 1.2; ctx.stroke();
          ctx.fillStyle = typeColor(t) + "cc"; ctx.font = `600 9px ${MONO}`; ctx.textAlign = "center";
          ctx.fillText(t, x, labelY);
        });
      }

      // ── Edges (hidden in hub cloud/sub-type view, visible at detail zoom) ──
      const hubCloud = layout === "hub" && zLvl < 3;
      if (!hubCloud) {
        edges.forEach(([a, b, etype]) => {
          if (!nodes[a] || !nodes[b]) return;
          if (layout === "hub" && !showSingletons && (nodes[a].isSingleton || nodes[b].isSingleton)) return;
          if (etype === 0 && !showRelates) return;
          if (etype === 1 && !showCooccur) return;
          if (typeFilter && (nodes[a].data.schema_type || "Thing") !== typeFilter && (nodes[b].data.schema_type || "Thing") !== typeFilter) return;
          if (layout === "hub" && etype === 1) {
            if (nodes[a].community !== undefined && nodes[a].community === nodes[b].community) return;
          }
          const interComm = layout === "hub" && nodes[a].community !== undefined && nodes[a].community !== nodes[b].community;
          ctx.beginPath(); ctx.moveTo(nodes[a].x, nodes[a].y); ctx.lineTo(nodes[b].x, nodes[b].y);
          if (etype === 1) {
            ctx.setLineDash([3, 6]);
            ctx.strokeStyle = p.textMuted + (interComm ? "70" : "30");
            ctx.lineWidth = interComm ? 1.4 : 0.8;
          } else {
            ctx.setLineDash([]);
            ctx.strokeStyle = p.accent + (interComm ? "aa" : "60");
            ctx.lineWidth = interComm ? 2 : 1.2;
          }
          ctx.stroke();
          ctx.setLineDash([]);
        });
      }

      // ── Nodes (hidden in hub cloud/sub-type view, visible at detail zoom) ──
      if (!hubCloud) {
        nodes.forEach(n => {
          if (layout === "hub" && n.isSingleton && !showSingletons) return;
          const nodeType = n.data.schema_type || "Thing";
          const dimmed = typeFilter && nodeType !== typeFilter;
          const alpha = dimmed ? 0.15 : 1;
          ctx.globalAlpha = alpha;
          // At medium zoom (1.6-2.5): small dots, no labels
          // At high zoom (>2.5): full detail with labels
          const screenR = n.r * zLvl;
          ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
          ctx.fillStyle = n.fixed ? n.color + "70" : n.color + "40";
          ctx.strokeStyle = n.color; ctx.lineWidth = 1.5;
          ctx.fill(); ctx.stroke();
          // Labels only at detail zoom
          if (showLabels && !dimmed && screenR >= 12) {
            ctx.fillStyle = p.text; ctx.font = `600 10px ${FONT}`; ctx.textAlign = "center";
            ctx.fillText(n.label, n.x, n.y + n.r + 15);
          }
          ctx.globalAlpha = 1;
        });
      }

      ctx.restore();
    };

    // ── Simple step (spiral overlap-fix only) ───────────────────────────
    const step = () => {
      for (let i = 0; i < nodes.length; i++) {
        if (nodes[i].fixed) continue;
        nodes[i].vx *= 0.6; nodes[i].vy *= 0.6;
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
          const d2 = Math.max(1, dx * dx + dy * dy), f = 400 / d2;
          nodes[i].vx += dx * f; nodes[i].vy += dy * f;
          if (!nodes[j].fixed) { nodes[j].vx -= dx * f; nodes[j].vy -= dy * f; }
        }
        nodes[i].vx += (w / 2 - nodes[i].x) * 0.001;
        nodes[i].vy += (h / 2 - nodes[i].y) * 0.001;
      }
      edges.forEach(([a, b]) => {
        const dx = nodes[b].x - nodes[a].x, dy = nodes[b].y - nodes[a].y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1, f = (d - 120) * 0.008;
        const rfx = (dx / d) * f, rfy = (dy / d) * f;
        if (!nodes[a].fixed) { nodes[a].vx += rfx; nodes[a].vy += rfy; }
        if (!nodes[b].fixed) { nodes[b].vx -= rfx; nodes[b].vy -= rfy; }
      });
      nodes.forEach(n => {
        if (n.fixed) return;
        n.x = Math.max(n.r + 20, Math.min(w - n.r - 20, n.x + n.vx));
        n.y = Math.max(n.r + 20, Math.min(h - n.r - 20, n.y + n.vy));
      });
    };

    // ── CoSE: simulated-annealing force-directed layout ──────────────────
    // Equations: spring F=k_s×(d−L)/d  |  repulsion F=k_r/d²  |  gravity F=k_g×d
    const COSE_K_S = 0.35, COSE_L = 90, COSE_K_R = 18000, COSE_K_G = 0.015;
    const COSE_INIT = 0.12, COSE_MAX = 600, COSE_CELL = 150;
    let coseIter = 0;
    let coseGrid  = {};

    const buildCoseGrid = () => {
      coseGrid = {};
      nodes.forEach((n, i) => {
        const key = `${Math.floor(n.x / COSE_CELL)},${Math.floor(n.y / COSE_CELL)}`;
        (coseGrid[key] = coseGrid[key] || []).push(i);
      });
    };

    const stepCoSE = () => {
      const N = nodes.length;
      if (N === 0) return 0;
      if (coseIter % 10 === 0) buildCoseGrid();

      // coolingFactor = initialCooling × (maxIter − iter) / maxIter
      const cool = COSE_INIT * (COSE_MAX - coseIter) / COSE_MAX;
      if (cool <= 0) return 0;

      const cx = w / 2, cy = h / 2;
      const fx = new Float32Array(N), fy = new Float32Array(N);

      // 1. Spring (attractive/repulsive) — F_spring = k_s × (d − L) / d along edge
      edges.forEach(([a, b]) => {
        if (!nodes[a] || !nodes[b]) return;
        const dx = nodes[b].x - nodes[a].x, dy = nodes[b].y - nodes[a].y;
        const d  = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const s  = COSE_K_S * (d - COSE_L) / d;
        if (!nodes[a].fixed) { fx[a] += s * dx; fy[a] += s * dy; }
        if (!nodes[b].fixed) { fx[b] -= s * dx; fy[b] -= s * dy; }
      });

      // 2. Repulsion — F_repulsion = k_r / d²  (grid-partitioned, O(n) avg)
      nodes.forEach((n, i) => {
        const gc = Math.floor(n.x / COSE_CELL), gr = Math.floor(n.y / COSE_CELL);
        for (let dc = -1; dc <= 1; dc++) {
          for (let dr = -1; dr <= 1; dr++) {
            const nb = coseGrid[`${gc + dc},${gr + dr}`];
            if (!nb) continue;
            nb.forEach(j => {
              if (j <= i) return;
              const dx = n.x - nodes[j].x, dy = n.y - nodes[j].y;
              const d2 = Math.max(1, dx * dx + dy * dy), d = Math.sqrt(d2);
              const f  = COSE_K_R / d2;          // inverse-square magnitude
              if (!n.fixed)        { fx[i] += f * dx / d; fy[i] += f * dy / d; }
              if (!nodes[j].fixed) { fx[j] -= f * dx / d; fy[j] -= f * dy / d; }
            });
          }
        }
      });

      // 3. Gravity — F_gravity = k_g × d(node, center) toward barycenter
      nodes.forEach((n, i) => {
        if (n.fixed) return;
        fx[i] += COSE_K_G * (cx - n.x);
        fy[i] += COSE_K_G * (cy - n.y);
      });

      // 4. Displacement: Δ = coolingFactor × (F_spring + F_repulsion + F_gravity)
      let totalDisp = 0;
      nodes.forEach((n, i) => {
        if (n.fixed) return;
        const dx = cool * fx[i], dy = cool * fy[i];
        n.x = Math.max(n.r + 10, Math.min(w - n.r - 10, n.x + dx));
        n.y = Math.max(n.r + 10, Math.min(h - n.r - 10, n.y + dy));
        totalDisp += Math.sqrt(dx * dx + dy * dy);
      });
      coseIter++;
      return totalDisp / N;   // used for convergence check
    };

    drawRef.current = draw;
    draw();

    // Animate: CoSE for "force", simple physics for "spiral" settle
    // Skip animation restart if only theme changed (no structural change)
    let frame, settled = 0;
    const FRAMES = (nodeCountChanged || layoutChanged)
      ? (layout === "force" ? COSE_MAX : layout === "spiral" ? 80 : 0)
      : 0;
    if (FRAMES > 0) {
      const animate = () => {
        const avgDisp = layout === "force" ? stepCoSE() : step();
        draw();
        settled++;
        // 5. Convergence check every 10 iters: stop if avgDisp/N < threshold
        const converged = layout === "force" && settled % 10 === 0 && avgDisp < 0.5;
        if (!converged && settled < FRAMES) frame = requestAnimationFrame(animate);
      };
      frame = requestAnimationFrame(animate);
    }

    // ── Zoom / Pan / Drag ────────────────────────────────────────────────
    const getPos = e => {
      const r = canvas.getBoundingClientRect();
      const sx = (e.clientX - r.left) * (w / r.width);
      const sy = (e.clientY - r.top)  * (h / r.height);
      // screen → world: subtract pan then divide by zoom
      return { x: (sx - pan.x) / zoom.z, y: (sy - pan.y) / zoom.z };
    };

    const onWheel = e => {
      e.preventDefault();
      const r = canvas.getBoundingClientRect();
      const sx = (e.clientX - r.left) * (w / r.width);
      const sy = (e.clientY - r.top)  * (h / r.height);
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const newZ = Math.max(0.15, Math.min(6, zoom.z * factor));
      // Zoom toward cursor: world point under cursor stays fixed
      pan.x = sx - (sx - pan.x) * (newZ / zoom.z);
      pan.y = sy - (sy - pan.y) * (newZ / zoom.z);
      zoom.z = newZ;
      draw();
    };
    const hitTest = pos => {
      let hit = null, minD = Infinity;
      nodes.forEach(n => { const d = Math.hypot(n.x - pos.x, n.y - pos.y); if (d <= n.r + 8 && d < minD) { minD = d; hit = n; } });
      return hit;
    };
    const drag = { node: null, panning: false, panStart: null, panOrigin: null, downClient: null, didMove: false };
    const onDown = e => {
      const pos = getPos(e);
      const hit = hitTest(pos);
      drag.downClient = { x: e.clientX, y: e.clientY };
      drag.didMove = false;
      if (hit) {
        drag.node = hit; hit.fixed = true; hit.vx = 0; hit.vy = 0;
        canvas.style.cursor = "grabbing";
      } else {
        drag.panning = true;
        drag.panStart  = { x: e.clientX, y: e.clientY };
        drag.panOrigin = { x: pan.x, y: pan.y };
        canvas.style.cursor = "grabbing";
      }
    };
    const onMove = e => {
      if (drag.downClient) {
        const dx = e.clientX - drag.downClient.x, dy = e.clientY - drag.downClient.y;
        if (Math.hypot(dx, dy) > 4) drag.didMove = true;
      }
      if (drag.node) {
        const pos = getPos(e);
        drag.node.x = Math.max(drag.node.r + 20, Math.min(w - drag.node.r - 20, pos.x));
        drag.node.y = Math.max(drag.node.r + 20, Math.min(h - drag.node.r - 20, pos.y));
        draw();
      } else if (drag.panning) {
        pan.x = drag.panOrigin.x + (e.clientX - drag.panStart.x);
        pan.y = drag.panOrigin.y + (e.clientY - drag.panStart.y);
        draw();
      } else {
        canvas.style.cursor = hitTest(getPos(e)) ? "grab" : "move";
      }
    };
    const onUp = e => {
      if (!drag.didMove) {
        const r = canvas.getBoundingClientRect();
        if (drag.node) {
          // Node click — compute screen position of the node centre
          const sx = drag.node.x * zoom.z + pan.x;
          const sy = drag.node.y * zoom.z + pan.y;
          // Convert canvas-space to CSS pixels (canvas is scaled 2x for retina)
          const cssX = r.left + sx * (r.width  / w);
          const cssY = r.top  + sy * (r.height / h);
          setSelectedNodeRef.current(drag.node.data);
          setPopupPosRef.current({ x: cssX, y: cssY });
        } else {
          setSelectedNodeRef.current(null);
        }
      }
      drag.node = null; drag.panning = false; drag.didMove = false; drag.downClient = null;
      canvas.style.cursor = "move";
    };

    // mouseleave only cancels drag state — never touches selectedNode
    const onLeave = () => { drag.node = null; drag.panning = false; drag.didMove = false; drag.downClient = null; canvas.style.cursor = "move"; };

    canvas.addEventListener("mousedown",  onDown);
    canvas.addEventListener("mousemove",  onMove);
    canvas.addEventListener("mouseup",    onUp);
    canvas.addEventListener("mouseleave", onLeave);
    canvas.addEventListener("wheel",      onWheel, { passive: false });

    return () => {
      cancelAnimationFrame(frame);
      drawRef.current = null;
      canvas.removeEventListener("mousedown",  onDown);
      canvas.removeEventListener("mousemove",  onMove);
      canvas.removeEventListener("mouseup",    onUp);
      canvas.removeEventListener("mouseleave", onLeave);
      canvas.removeEventListener("wheel",      onWheel);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey, layout, p, showSingletons, showLabels, showRelates, showCooccur, typeFilter]);

  // Derived for the side panel (not used in canvas)
  const episodes  = epData?.episodes  || [];
  const knowledge = knData?.knowledge || [];
  const ontology  = ontoData?.nodes   || [];

  return (
    // Break out of parent padding to fill the content area edge-to-edge
    <div style={{ position: "relative", margin: "-28px -36px", height: "calc(100vh - 56px)", overflow: "hidden" }}>

      {/* Full-screen canvas */}
      <div style={{ position: "absolute", inset: 0, background: p.bg }}>
        <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />
      </div>

      {/* Top-left title bar */}
      <div style={{ position: "absolute", top: 20, left: 24, zIndex: 10, pointerEvents: "none" }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: p.text }}>Memory Graph</h2>
        <div style={{ fontSize: 11, color: p.textMuted, fontFamily: MONO, marginTop: 3 }}>
          {ontology.length} ontology · {knowledge.length} knowledge · {episodes.length} episodes
        </div>
      </div>

      {/* Top toolbar — layout buttons + filter controls */}
      <div style={{ position: "absolute", top: 12, left: 0, right: sidebarOpen ? 340 : 0, zIndex: 10, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "0 120px 0 10px" }}>
        {/* Row 1: Layout buttons */}
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", justifyContent: "center" }}>
          {LAYOUT_OPTS.map(l => (
            <button key={l.id} onClick={() => setLayout(l.id)} style={{
              padding: "4px 10px", borderRadius: 20, cursor: "pointer", transition: "all 0.15s",
              border: `1px solid ${layout === l.id ? p.accent : p.border}`,
              background: layout === l.id ? p.accent + "22" : p.surface + "dd",
              color: layout === l.id ? p.accent : p.textMuted,
              fontSize: 10, fontWeight: 600, fontFamily: MONO,
              backdropFilter: "blur(8px)",
            }}>{l.label}</button>
          ))}
        </div>
        {/* Row 2: Filters */}
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", justifyContent: "center", alignItems: "center" }}>
          {/* Type filter dropdown */}
          <select
            value={typeFilter || ""}
            onChange={e => setTypeFilter(e.target.value || null)}
            style={{
              padding: "3px 8px", borderRadius: 12, cursor: "pointer",
              border: `1px solid ${typeFilter ? p.accent : p.border}`,
              background: typeFilter ? p.accent + "22" : p.surface + "dd",
              color: typeFilter ? p.accent : p.textMuted,
              fontSize: 10, fontWeight: 600, fontFamily: MONO,
              backdropFilter: "blur(8px)", outline: "none",
            }}
          >
            <option value="">All types</option>
            {[...new Set(ontology.map(o => o.schema_type || "Thing"))].sort().map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          {/* Separator */}
          <span style={{ color: p.textDim, fontSize: 10 }}>|</span>
          {/* Edge toggles */}
          <button onClick={() => setShowRelates(v => !v)} style={{
            padding: "3px 10px", borderRadius: 12, cursor: "pointer", transition: "all 0.15s",
            border: `1px solid ${showRelates ? p.accent : p.border}`,
            background: showRelates ? p.accent + "22" : p.surface + "dd",
            color: showRelates ? p.accent : p.textMuted,
            fontSize: 10, fontWeight: 600, fontFamily: MONO,
            backdropFilter: "blur(8px)",
          }}>Semantic</button>
          <button onClick={() => setShowCooccur(v => !v)} style={{
            padding: "3px 10px", borderRadius: 12, cursor: "pointer", transition: "all 0.15s",
            border: `1px solid ${showCooccur ? p.blue : p.border}`,
            background: showCooccur ? p.blue + "22" : p.surface + "dd",
            color: showCooccur ? p.blue : p.textMuted,
            fontSize: 10, fontWeight: 600, fontFamily: MONO,
            backdropFilter: "blur(8px)",
          }}>Co-occur</button>
          <span style={{ color: p.textDim, fontSize: 10 }}>|</span>
          {/* Label toggle */}
          <button onClick={() => setShowLabels(v => !v)} style={{
            padding: "3px 10px", borderRadius: 12, cursor: "pointer", transition: "all 0.15s",
            border: `1px solid ${showLabels ? p.warm : p.border}`,
            background: showLabels ? p.warm + "22" : p.surface + "dd",
            color: showLabels ? p.warm : p.textMuted,
            fontSize: 10, fontWeight: 600, fontFamily: MONO,
            backdropFilter: "blur(8px)",
          }}>Labels</button>
          {/* Singleton toggle */}
          {layout === "hub" && singletonCount > 0 && (
            <button onClick={() => { setShowSingletons(v => !v); setLayoutKey(k => k + 1); }} style={{
              padding: "3px 10px", borderRadius: 12, cursor: "pointer", transition: "all 0.15s",
              border: `1px solid ${showSingletons ? p.warm : p.border}`,
              background: showSingletons ? p.warm + "22" : p.surface + "dd",
              color: showSingletons ? p.warm : p.textMuted,
              fontSize: 10, fontWeight: 600, fontFamily: MONO,
              backdropFilter: "blur(8px)",
            }}>{singletonCount} isolated</button>
          )}
        </div>
      </div>

      {/* Bottom-left legend — collapsible, click type to filter */}
      {ontology.length > 0 && (() => {
        const types = [...new Set(ontology.map(o => o.schema_type || "Thing"))].sort();
        return (
          <div style={{
            position: "absolute", bottom: 20, left: 24, zIndex: 10,
            maxWidth: 360,
            background: p.surface + "cc", backdropFilter: "blur(8px)",
            border: `1px solid ${p.border}`, borderRadius: 8,
            padding: legendOpen ? "8px 12px" : "4px 10px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}
                 onClick={() => setLegendOpen(v => !v)}>
              <span style={{ fontSize: 10, fontWeight: 700, color: p.textMuted, fontFamily: MONO }}>
                {legendOpen ? "Legend" : `Legend (${types.length})`}
              </span>
              <span style={{ fontSize: 9, color: p.textDim, transform: legendOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" }}>▾</span>
            </div>
            {legendOpen && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", maxWidth: 340, maxHeight: 120, overflowY: "auto", marginTop: 6 }}>
                {types.map(t => (
                  <div key={t} style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", opacity: typeFilter && typeFilter !== t ? 0.35 : 1 }}
                       onClick={() => setTypeFilter(f => f === t ? null : t)}>
                    <div style={{ width: 8, height: 8, borderRadius: "50%", background: typeColor(t), flexShrink: 0 }} />
                    <span style={{ fontSize: 10, color: p.textMuted, fontFamily: MONO }}>{t}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      {/* Sidebar toggle button */}
      <button onClick={() => setSidebarOpen(v => !v)} style={{
        position: "absolute", top: 12, right: sidebarOpen ? 348 : 12, zIndex: 20,
        width: 28, height: 28, borderRadius: 8, cursor: "pointer", transition: "right 0.2s",
        border: `1px solid ${p.border}`, background: p.surface + "dd",
        color: p.textMuted, fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center",
        backdropFilter: "blur(8px)",
      }}>{sidebarOpen ? "›" : "‹"}</button>

      {/* Right panel — floating overlay, collapsible */}
      <div style={{
        position: "absolute", top: 0, right: 0, bottom: 0, width: 340, zIndex: 10,
        background: p.surface + "f0", backdropFilter: "blur(12px)",
        borderLeft: `1px solid ${p.border}`, display: "flex", flexDirection: "column",
        transform: sidebarOpen ? "translateX(0)" : "translateX(100%)",
        transition: "transform 0.2s ease",
      }}>
        {/* Tabs */}
        <div style={{ display: "flex", borderBottom: `1px solid ${p.border}` }}>
          {["episodes", "knowledge", "ontology"].map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              flex: 1, padding: "12px 0", fontSize: 11, fontWeight: 700, fontFamily: MONO,
              textTransform: "uppercase", letterSpacing: "0.06em", border: "none", cursor: "pointer",
              background: "transparent", color: tab === t ? p.accent : p.textMuted,
              borderBottom: tab === t ? `2px solid ${p.accent}` : "2px solid transparent",
              transition: "all 0.15s",
            }}>{t}</button>
          ))}
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: "auto", padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
          {tab === "episodes" && (episodes.length === 0
            ? <Empty msg="No episodes yet." />
            : episodes.map((ep, i) => (
              <div key={i} style={{ background: p.surfaceAlt, border: `1px solid ${p.border}`, borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ fontSize: 12, color: p.text, lineHeight: 1.4, marginBottom: 6 }}>{ep.content}</div>
                <div style={{ display: "flex", gap: 8, fontSize: 10, fontFamily: MONO }}>
                  <Badge color={p.blue}>{ep.episode_type || "raw"}</Badge>
                  <span style={{ color: p.textMuted }}>{ep.group_id}</span>
                </div>
              </div>
            ))
          )}
          {tab === "knowledge" && (knowledge.length === 0
            ? <Empty msg="No knowledge nodes yet." />
            : knowledge.map((k, i) => (
              <div key={i} style={{ background: p.surfaceAlt, border: `1px solid ${p.border}`, borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <Badge color={k.knowledge_type === "fact" ? p.accent : k.knowledge_type === "pattern" ? p.warm : k.knowledge_type === "procedure" ? p.blue : p.purple}>{k.knowledge_type || "fact"}</Badge>
                  <span style={{ fontSize: 10, fontFamily: MONO, color: p.textMuted }}>{(k.confidence || 0).toFixed(2)}</span>
                </div>
                <div style={{ fontSize: 12, color: p.text, lineHeight: 1.4, marginBottom: 6 }}>{k.content}</div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {(k.labels || []).map((lbl, j) => <span key={j} style={{ fontSize: 10, fontFamily: MONO, color: p.textDim, background: p.bg, padding: "1px 6px", borderRadius: 3 }}>{lbl}</span>)}
                </div>
              </div>
            ))
          )}
          {tab === "ontology" && (ontology.length === 0
            ? <Empty msg="No ontology entities yet." />
            : ontology.map((o, i) => (
              <div key={i} style={{ background: p.surfaceAlt, border: `1px solid ${p.border}`, borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: p.text }}>{o.display_name || o.name}</span>
                  <Badge color={p.purple}>{o.schema_type}</Badge>
                </div>
                <div style={{ fontSize: 10, fontFamily: MONO, color: p.textDim }}>{o.source_count || 0} sources</div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Node popup */}
      {selectedNode && (() => {
        const POPUP_W = 300;
        const POPUP_H_EST = 220;
        const vw = window.innerWidth, vh = window.innerHeight;
        // Prefer placing popup to the right of the node; flip left if it would overflow
        let left = popupPos.x + 18;
        if (left + POPUP_W > vw - 12) left = popupPos.x - POPUP_W - 18;
        // Prefer below the node; flip up if it would overflow
        let top = popupPos.y - 20;
        if (top + POPUP_H_EST > vh - 12) top = vh - POPUP_H_EST - 12;
        return (
          <div style={{
            position: "fixed", left, top, width: POPUP_W, zIndex: 100,
            background: p.surface, border: `1px solid ${p.border}`,
            borderRadius: 10, boxShadow: `0 8px 32px rgba(0,0,0,0.35)`,
            padding: "16px 18px",
          }}>
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: p.text, lineHeight: 1.3 }}>
                  {selectedNode.display_name || selectedNode.name}
                </div>
                {selectedNode.display_name && selectedNode.display_name !== selectedNode.name && (
                  <div style={{ fontSize: 10, fontFamily: MONO, color: p.textDim, marginTop: 1 }}>{selectedNode.name}</div>
                )}
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <Badge color={p.purple}>{selectedNode.schema_type}</Badge>
                <button onClick={() => setSelectedNode(null)} style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: p.textMuted, fontSize: 16, lineHeight: 1, padding: "0 2px",
                }}>×</button>
              </div>
            </div>

            {/* Summary */}
            {selectedNode.summary && (
              <div style={{
                fontSize: 12, color: p.textDim, lineHeight: 1.55, marginBottom: 10,
                maxHeight: 120, overflowY: "auto",
                borderTop: `1px solid ${p.border}`, paddingTop: 8,
              }}>
                {selectedNode.summary}
              </div>
            )}

            {/* Footer stats */}
            <div style={{ display: "flex", gap: 14, fontSize: 10, fontFamily: MONO, color: p.textMuted, borderTop: `1px solid ${p.border}`, paddingTop: 8 }}>
              <span>{selectedNode.source_count || 0} source{(selectedNode.source_count || 0) !== 1 ? "s" : ""}</span>
              {selectedNode.group_id && <span>group: {selectedNode.group_id}</span>}
            </div>
          </div>
        );
      })()}
    </div>
  );
};

// ─── Page: Observe Playground ──────────────────────────────────────────
const ObservePage = () => {
  const p = useP();
  const [content, setContent]   = useState("The user asked about last quarter's deployment incident.");
  const [sessionId, setSessionId] = useState("agent-session-1");
  const [readOnly, setReadOnly]  = useState(false);
  const [summarize, setSummarize] = useState(false);
  const [sent, setSent]          = useState(false);
  const [response, setResponse]  = useState(null);
  const [error, setError]        = useState(null);

  const requestObj = { session_id: sessionId, content, timestamp: new Date().toISOString(), source: "chat", ...(readOnly && { read_only: true }), ...(summarize && { summarize: true }) };

  const handleSend = async () => {
    setSent(true); setError(null); setResponse(null);
    try {
      const res = await fetch(`${API}/observe`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requestObj) });
      if (!res.ok) setError(`${res.status} — ${await res.text()}`);
      else setResponse(await res.json());
    } catch (e) { setError(e.message); }
    finally { setSent(false); }
  };

  const inp = { width: "100%", boxSizing: "border-box", padding: "10px 14px", borderRadius: 8, border: `1px solid ${p.borderLight}`, background: p.inputBg, color: p.text, fontFamily: MONO, fontSize: 13, outline: "none" };

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: p.text }}>Observe Playground</h2>
      <p style={{ color: p.textMuted, fontSize: 14, marginTop: 4, marginBottom: 24 }}>
        Test the <code style={{ fontFamily: MONO, color: p.accent, background: p.accentDim, padding: "1px 6px", borderRadius: 4 }}>POST /observe</code> endpoint
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div>
          <SectionTitle>Request</SectionTitle>
          <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: 20 }}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: p.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Session ID</label>
              <input value={sessionId} onChange={e => setSessionId(e.target.value)} style={inp} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: p.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Content</label>
              <textarea value={content} onChange={e => setContent(e.target.value)} rows={3} style={{ ...inp, fontFamily: FONT, resize: "vertical" }} />
            </div>
            <div style={{ display: "flex", gap: 20, marginBottom: 20 }}>
              {[{ label: "read_only", val: readOnly, set: setReadOnly }, { label: "summarize", val: summarize, set: setSummarize }].map(f => (
                <label key={f.label} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <div onClick={() => f.set(!f.val)} style={{ width: 18, height: 18, borderRadius: 4, border: `1.5px solid ${f.val ? p.accent : p.borderLight}`, background: f.val ? p.accentDim : "transparent", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", transition: "all 0.15s" }}>
                    {f.val && <Icon d={icons.check} size={12} />}
                  </div>
                  <span style={{ fontSize: 12, fontFamily: MONO, color: p.textMuted }}>{f.label}</span>
                </label>
              ))}
            </div>

            <div style={{ background: p.bg, borderRadius: 8, padding: 14, fontFamily: MONO, fontSize: 11, color: p.textMuted, lineHeight: 1.7, whiteSpace: "pre-wrap", marginBottom: 16, border: `1px solid ${p.border}` }}>
              <span style={{ color: p.textDim }}>POST /api/v1/memory/observe</span>{"\n"}{JSON.stringify(requestObj, null, 2)}
            </div>

            <button onClick={handleSend} disabled={sent} style={{
              width: "100%", padding: "12px 0", borderRadius: 8, border: "none",
              background: sent ? p.surfaceAlt : `linear-gradient(135deg, ${p.accent}, ${p.accent}cc)`,
              color: sent ? p.textMuted : p.bg, fontWeight: 700, fontSize: 14, fontFamily: FONT,
              cursor: sent ? "wait" : "pointer", transition: "all 0.2s", display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
            }}>
              {sent ? "Observing…" : <><Icon d={icons.send} size={14} /> Send Observation</>}
            </button>
          </div>
        </div>

        <div>
          <SectionTitle>Response</SectionTitle>
          <div style={{ background: p.surface, border: `1px solid ${response ? p.accent + "60" : error ? p.coral + "60" : p.border}`, borderRadius: 12, padding: 20, minHeight: 380, transition: "border-color 0.3s" }}>
            {error && <><Badge color={p.coral}>Error</Badge><div style={{ marginTop: 10, color: p.coral, fontFamily: MONO, fontSize: 12, lineHeight: 1.6 }}>{error}</div></>}
            {response && !error && (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}><Badge color={p.green}>200 OK</Badge></div>
                {response.episode_uuid && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: p.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>episode_uuid</div>
                    <div style={{ background: p.surfaceAlt, borderRadius: 6, padding: "8px 12px", fontFamily: MONO, fontSize: 12, color: p.accent }}>{response.episode_uuid}</div>
                  </div>
                )}
                {response.context && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: p.textMuted, fontFamily: MONO, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>context</div>
                    <div style={{ background: p.surfaceAlt, borderRadius: 8, padding: "14px 16px", fontSize: 13, color: p.text, lineHeight: 1.6, borderLeft: `3px solid ${p.accent}` }}>{response.context}</div>
                  </div>
                )}
                {!response.context && <div style={{ background: p.bg, borderRadius: 8, padding: 14, marginTop: 12, fontFamily: MONO, fontSize: 11, color: p.textMuted, whiteSpace: "pre-wrap" }}>{JSON.stringify(response, null, 2)}</div>}
              </>
            )}
            {!response && !error && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 340, color: p.textDim }}>
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

// ─── Page: Configuration ───────────────────────────────────────────────
const ConfigPage = () => {
  const p = useP();
  const { data: cfg, loading } = useFetch(`${API}/ui/config`);

  const sectionOrder = ["scoring", "hebbian", "background", "session", "nats"];

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: p.text }}>Configuration</h2>
      <p style={{ color: p.textMuted, fontSize: 14, marginTop: 4, marginBottom: 28 }}>settings.toml · live values from running service</p>
      {loading && <Empty msg="Loading configuration…" />}
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {cfg && sectionOrder.map(section => {
          const values = cfg[section] || {};
          return (
            <div key={section} style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: p.accent, fontFamily: MONO, marginBottom: 14, letterSpacing: "0.04em" }}>[default.{section}]</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {Object.entries(values).map(([key, val]) => (
                  <div key={key} style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 12, alignItems: "center" }}>
                    <span style={{ fontSize: 12, fontFamily: MONO, color: p.text }}>{key}</span>
                    <span style={{ fontSize: 12, fontFamily: MONO, color: p.accent, background: p.accentDim, padding: "4px 10px", borderRadius: 6 }}>{String(val)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ─── Page: REM Monitor ─────────────────────────────────────────────────
const REMPage = () => {
  const p = useP();
  const [tick, setTick] = useState(0);
  const { data: stats } = useFetch(`${API}/ui/stats`, [tick]);
  const { data: evData } = useFetch(`${API}/ui/events?count=20`, [tick]);
  const events = evData?.events || [];

  useEffect(() => { const t = setInterval(() => setTick(c => c + 1), 8000); return () => clearInterval(t); }, []);

  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: p.text }}>REM Consolidation</h2>
      <p style={{ color: p.textMuted, fontSize: 14, marginTop: 4, marginBottom: 28 }}>Background memory consolidation · Like biological REM sleep</p>

      <div style={{ display: "flex", gap: 14, marginBottom: 28 }}>
        <StatCard label="Pending Episodes" value={stats?.pending_episodes} sub="awaiting consolidation"  color={p.warm}   />
        <StatCard label="Episodes Total"   value={stats?.episodes}         sub="in FalkorDB"             color={p.blue}   />
        <StatCard label="Knowledge Nodes"  value={stats?.knowledge_nodes}  sub="extracted facts"         color={p.accent} />
        <StatCard label="Hebbian Edges"    value={stats?.hebbian_edges}    sub="CO_ACTIVATED links"      color={p.coral}  />
      </div>

      <SectionTitle>Consolidation Pipeline</SectionTitle>
      <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 12, padding: "24px 28px", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center" }}>
          {[
            { label: "Find Groups",        detail: "≥3 pending episodes",  color: p.textMuted, active: true  },
            { label: "Dedup Check",        detail: "cosine ≥ 0.90",        color: p.warm,      active: true  },
            { label: "Knowledge Extract",  detail: "DSPy pipeline",        color: p.accent,    active: true  },
            { label: "Ontology Update",    detail: "Schema.org entities",  color: p.purple,    active: false },
            { label: "Temporal Compress",  detail: "≥2 unique → summary",  color: p.blue,      active: false },
            { label: "Hebbian Decay",      detail: "×(1−0.01) per cycle",  color: p.coral,     active: false },
          ].map((step, i, arr) => (
            <div key={i} style={{ display: "flex", alignItems: "center", flex: 1 }}>
              <div style={{ textAlign: "center", flex: 1 }}>
                <div style={{ width: 38, height: 38, borderRadius: "50%", margin: "0 auto 8px", border: `2px solid ${step.active ? step.color : p.border}`, background: step.active ? step.color + "20" : "transparent", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700, color: step.active ? step.color : p.textDim, fontFamily: MONO }}>{i + 1}</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: step.active ? p.text : p.textDim, marginBottom: 2 }}>{step.label}</div>
                <div style={{ fontSize: 10, color: p.textDim, fontFamily: MONO }}>{step.detail}</div>
              </div>
              {i < arr.length - 1 && <div style={{ width: 24, height: 1, background: p.border, flexShrink: 0, marginBottom: 24 }} />}
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div>
          <SectionTitle>Recent Events <span style={{ fontSize: 10, color: p.textDim, fontFamily: MONO }}>(refreshes every 8s)</span></SectionTitle>
          <div style={{ background: p.bg, border: `1px solid ${p.border}`, borderRadius: 10, padding: 14, fontFamily: MONO, fontSize: 11, lineHeight: 1.8, color: p.textMuted, height: 220, overflowY: "auto" }}>
            {events.length === 0
              ? <span style={{ color: p.textDim }}>No events yet.</span>
              : events.map((ev, i) => (
                <div key={i}>
                  <span style={{ color: p.textDim }}>{ev.time}</span>{" "}
                  <span style={{ color: ev.subject?.includes("curation") ? p.warm : ev.subject?.includes("stored") ? p.blue : ev.subject?.includes("decay") ? p.coral : p.accent }}>{ev.subject}</span>
                </div>
              ))}
          </div>
        </div>
        <div>
          <SectionTitle>Memory Totals</SectionTitle>
          <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: 10, padding: 20 }}>
            {[
              { label: "Episodes",               value: stats?.episodes,         color: p.blue   },
              { label: "Knowledge nodes",        value: stats?.knowledge_nodes,  color: p.warm   },
              { label: "Ontology entities",      value: stats?.ontology_entities, color: p.purple },
              { label: "Pending consolidation",  value: stats?.pending_episodes, color: p.coral  },
              { label: "CO_ACTIVATED edges",     value: stats?.hebbian_edges,    color: p.accent },
            ].map((row, i, arr) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderBottom: i < arr.length - 1 ? `1px solid ${p.border}` : "none" }}>
                <span style={{ fontSize: 13, color: p.textMuted }}>{row.label}</span>
                <span style={{ fontSize: 16, fontWeight: 700, color: row.color, fontFamily: MONO }}>{row.value ?? "—"}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Main App ──────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { id: "dashboard",  label: "Dashboard",    icon: icons.dashboard  },
  { id: "reporting",  label: "Reporting",    icon: icons.reporting  },
  { id: "sessions",   label: "Sessions",     icon: icons.sessions   },
  { id: "graph",      label: "Memory Graph", icon: icons.graph      },
  { id: "observe",    label: "Observe",      icon: icons.observe    },
  { id: "rem",        label: "REM Monitor",  icon: icons.rem        },
  { id: "config",     label: "Configuration",icon: icons.config     },
];

export default function SegnogUI() {
  const [page, setPage] = useState("dashboard");
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("segnog-theme") || "dark"; } catch { return "dark"; }
  });
  const p = theme === "dark" ? DARK : LIGHT;

  useEffect(() => { try { localStorage.setItem("segnog-theme", theme); } catch {} }, [theme]);

  return (
    <ThemeCtx.Provider value={p}>
      <div style={{ display: "flex", height: "100vh", fontFamily: FONT, background: p.bg, color: p.text, overflow: "hidden" }}>
        {/* Sidebar */}
        <div style={{ width: 220, background: p.surface, borderRight: `1px solid ${p.border}`, display: "flex", flexDirection: "column", flexShrink: 0 }}>
          {/* Logo */}
          <div style={{ padding: "20px 18px 16px", borderBottom: `1px solid ${p.border}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 34, height: 34, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", background: `linear-gradient(135deg, ${p.accent}25, ${p.purple}25)`, border: `1px solid ${p.accent}30`, fontSize: 18 }}>𝄋</div>
              <div>
                <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "-0.02em", color: p.text }}>Segnog</div>
                <div style={{ fontSize: 10, color: p.textDim, fontFamily: MONO, letterSpacing: "0.04em" }}>dal segno</div>
              </div>
            </div>
          </div>

          {/* Nav */}
          <div style={{ padding: "12px 10px", flex: 1 }}>
            {NAV_ITEMS.map(item => (
              <button key={item.id} onClick={() => setPage(item.id)} style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                padding: "9px 12px", borderRadius: 8, border: "none", cursor: "pointer",
                background: page === item.id ? p.accentDim : "transparent",
                color: page === item.id ? p.accent : p.textMuted,
                fontSize: 13, fontWeight: page === item.id ? 600 : 500,
                fontFamily: FONT, textAlign: "left", transition: "all 0.15s", marginBottom: 2,
              }}>
                <Icon d={item.icon} size={16} />
                {item.label}
              </button>
            ))}
          </div>

          {/* Footer */}
          <div style={{ padding: "14px 18px", borderTop: `1px solid ${p.border}` }}>
            <button onClick={() => setTheme(t => t === "dark" ? "light" : "dark")} style={{
              display: "flex", alignItems: "center", gap: 8, width: "100%",
              padding: "7px 10px", borderRadius: 8, border: `1px solid ${p.border}`,
              background: p.surfaceAlt, color: p.textMuted, fontSize: 12, fontFamily: MONO,
              cursor: "pointer", marginBottom: 10, transition: "all 0.15s",
            }}>
              <Icon d={theme === "dark" ? icons.sun : icons.moon} size={14} />
              {theme === "dark" ? "Light mode" : "Dark mode"}
            </button>
            <div style={{ fontSize: 11, color: p.textDim, fontFamily: MONO }}>
              <div>localhost:9000</div>
              <div style={{ marginTop: 2, display: "flex", gap: 4, alignItems: "center" }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: p.green }} />
                container running
              </div>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div style={{ flex: 1, overflow: "auto", padding: "28px 36px" }}>
          {page === "dashboard"  && <DashboardPage />}
          {page === "reporting"  && <ReportingPage />}
          {page === "sessions"   && <SessionsPage />}
          {page === "graph"      && <GraphPage />}
          {page === "observe"    && <ObservePage />}
          {page === "rem"        && <REMPage />}
          {page === "config"     && <ConfigPage />}
        </div>
      </div>
    </ThemeCtx.Provider>
  );
}
