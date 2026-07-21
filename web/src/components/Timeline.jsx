import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, BarChart, Bar, Cell, Area, CartesianGrid,
} from 'recharts';

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'rgba(8, 9, 26, 0.95)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      border: '1px solid rgba(74, 123, 247, 0.15)',
      padding: '8px 16px',
      fontSize: 11,
      fontFamily: "var(--font-data)",
    }}>
      <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>t = {label} min</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color, marginBottom: 2 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </div>
      ))}
    </div>
  );
}

function TemporalLineChart({ temporal, parameters }) {
  const nodeTs = temporal.node_timeseries || {};
  const nodeIds = Object.keys(nodeTs);
  if (nodeIds.length === 0) return null;

  const firstNode = nodeTs[nodeIds[0]];
  const stepCount = firstNode?.wait?.length || 0;
  if (stepCount === 0) return null;

  const dt = parameters?.dt_minutes || 2;

  // Aggregate max wait and avg utilization per timestep
  const chartData = [];
  for (let i = 0; i < stepCount; i++) {
    const t = i * dt;
    let maxWait = 0;
    let sumUtil = 0;
    let count = 0;
    for (const nid of nodeIds) {
      const w = nodeTs[nid]?.wait?.[i] || 0;
      const u = nodeTs[nid]?.util?.[i] || 0;
      if (w > maxWait) maxWait = w;
      sumUtil += u;
      count++;
    }
    chartData.push({
      t: Math.round(t),
      wait: maxWait,
      util: count > 0 ? sumUtil / count : 0,
    });
  }

  const totalTime = chartData[chartData.length - 1]?.t || 0;
  const peakCongestion = temporal.peak_congestion_time;
  const eventDuration = (parameters?.event_duration_hours || 3) * 60;
  const arrivalEnd = Math.min(peakCongestion ? peakCongestion + 10 : 90, totalTime * 0.4);
  const egressStart = arrivalEnd + eventDuration;

  // Find peak wait value for annotation
  const peakPoint = peakCongestion
    ? chartData.find(d => d.t === Math.round(peakCongestion))
    : null;
  const peakLabel = peakPoint?.wait != null
    ? `PEAK: ${peakPoint.wait.toFixed(1)} min`
    : 'PEAK';

  const labelStyle = {
    fontSize: 9,
    fontFamily: "var(--font-label)",
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
  };

  return (
    <div className="glass-panel" style={{ padding: 24 }}>
      <div style={{
        fontFamily: 'var(--font-label)',
        fontSize: '0.65rem',
        fontWeight: 500,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: 'var(--text-tertiary)',
        marginBottom: 16,
      }}>
        Timeline
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={chartData} margin={{ top: 16, right: 8, bottom: 24, left: 4 }}>
          {/* Gradient fill for wait curve */}
          <defs>
            <linearGradient id="waitGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--status-warn)" stopOpacity={0.08} />
              <stop offset="100%" stopColor="var(--status-warn)" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border-subtle)"
            strokeOpacity={0.25}
            vertical={false}
          />

          <XAxis
            dataKey="t"
            stroke="none"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 9, fontFamily: "var(--font-mono)" }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'min', position: 'insideBottomRight', offset: 0, fill: 'var(--text-tertiary)', fontSize: 9 }}
          />
          <YAxis
            yAxisId="wait"
            stroke="none"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 9, fontFamily: "var(--font-mono)" }}
            tickLine={false}
            axisLine={false}
            width={32}
          />
          <YAxis
            yAxisId="util"
            orientation="right"
            stroke="none"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 9, fontFamily: "var(--font-mono)" }}
            tickLine={false}
            axisLine={false}
            domain={[0, 1]}
            width={28}
          />

          <Tooltip content={<CustomTooltip />} />

          {/* Phase markers */}
          {arrivalEnd < totalTime && (
            <ReferenceLine
              x={Math.round(arrivalEnd)}
              yAxisId="wait"
              stroke="var(--border-active)"
              strokeDasharray="3 3"
              label={{
                value: 'ARRIVAL',
                position: 'insideBottomLeft',
                fill: 'var(--text-tertiary)',
                fontSize: 9,
                fontFamily: "var(--font-label)",
                letterSpacing: '0.12em',
                opacity: 0.3,
              }}
            />
          )}
          {egressStart < totalTime && (
            <ReferenceLine
              x={Math.round(egressStart)}
              yAxisId="wait"
              stroke="var(--border-active)"
              strokeDasharray="3 3"
              label={{
                value: 'EGRESS',
                position: 'insideBottomLeft',
                fill: 'var(--text-tertiary)',
                fontSize: 9,
                fontFamily: "var(--font-label)",
                letterSpacing: '0.12em',
                opacity: 0.3,
              }}
            />
          )}

          {/* Peak annotation — dashed vertical line */}
          {peakCongestion != null && (
            <ReferenceLine
              x={Math.round(peakCongestion)}
              yAxisId="wait"
              stroke="var(--status-warn)"
              strokeWidth={1}
              strokeDasharray="4 4"
              strokeOpacity={0.5}
              label={{
                value: peakLabel,
                position: 'top',
                fill: 'var(--status-warn)',
                fontSize: 10,
                fontFamily: "var(--font-data)",
                fontWeight: 600,
              }}
            />
          )}

          {/* Gradient area under wait curve */}
          <Area
            yAxisId="wait"
            type="monotone"
            dataKey="wait"
            fill="url(#waitGradient)"
            stroke="none"
            animationDuration={400}
          />

          <Line
            yAxisId="wait"
            type="monotone"
            dataKey="wait"
            name="Wait (min)"
            stroke="var(--status-warn)"
            strokeWidth={1.5}
            dot={false}
            animationDuration={400}
          />
          <Line
            yAxisId="util"
            type="monotone"
            dataKey="util"
            name="Avg Util"
            stroke="var(--text-secondary)"
            strokeWidth={1}
            strokeOpacity={0.35}
            dot={false}
            animationDuration={400}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 24, fontSize: '0.7rem', color: 'var(--text-tertiary)', fontFamily: 'var(--font-data)', marginTop: 8 }}>
        <span>
          <span style={{ display: 'inline-block', width: 14, height: 2, background: 'var(--status-warn)', marginRight: 6, verticalAlign: 'middle' }} />
          Wait
        </span>
        <span>
          <span style={{ display: 'inline-block', width: 14, height: 2, background: 'var(--text-secondary)', opacity: 0.35, marginRight: 6, verticalAlign: 'middle' }} />
          Utilization
        </span>
      </div>
    </div>
  );
}

function UtilizationBarChart({ simulation }) {
  const nodeMetrics = simulation?.node_metrics || {};
  const entries = Object.entries(nodeMetrics)
    .map(([id, m]) => ({ id, util: m.util_mean || 0 }))
    .sort((a, b) => b.util - a.util)
    .slice(0, 8);

  if (entries.length === 0) return null;

  return (
    <div className="glass-panel" style={{ padding: 24 }}>
      <div style={{
        fontFamily: 'var(--font-label)',
        fontSize: '0.65rem',
        fontWeight: 500,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: 'var(--text-tertiary)',
        marginBottom: 16,
      }}>
        Node Utilization
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={entries} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 90 }}>
          <XAxis
            type="number"
            domain={[0, 1]}
            stroke="none"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 9, fontFamily: "var(--font-mono)" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="id"
            stroke="none"
            tick={{ fill: 'var(--text-secondary)', fontSize: 9, fontFamily: "var(--font-mono)" }}
            tickLine={false}
            axisLine={false}
            width={86}
          />
          <Tooltip
            formatter={(v) => [(v * 100).toFixed(1) + '%', 'Utilization']}
            contentStyle={{
              background: 'rgba(8, 9, 26, 0.95)',
              backdropFilter: 'blur(16px)',
              border: '1px solid rgba(74, 123, 247, 0.15)',
              fontSize: 11,
              fontFamily: "var(--font-data)",
            }}
          />
          <Bar dataKey="util" animationDuration={400} maxBarSize={14}>
            {entries.map((e, i) => (
              <Cell
                key={i}
                fill={
                  e.util >= 0.9 ? 'var(--status-danger)'
                  : e.util >= 0.7 ? 'var(--status-warn)'
                  : 'var(--accent)'
                }
                fillOpacity={0.65}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Timeline({ temporalData, simulationResults }) {
  const temporal = temporalData;
  const parameters = simulationResults?.parameters;

  if (temporal?.node_timeseries && Object.keys(temporal.node_timeseries).length > 0) {
    return <TemporalLineChart temporal={temporal} parameters={parameters} />;
  }

  if (simulationResults?.simulation) {
    return <UtilizationBarChart simulation={simulationResults.simulation} />;
  }

  return null;
}
