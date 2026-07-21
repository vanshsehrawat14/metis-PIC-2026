import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell,
} from 'recharts';

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'var(--bg-tertiary)',
      border: '1px solid var(--border-subtle)',
      padding: '8px 12px',
      fontSize: 11,
    }}>
      <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>
        t = {label} min
      </div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color, marginBottom: 2 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </div>
      ))}
    </div>
  );
}

function TemporalLineChart({ temporal, parameters }) {
  // Build time-series from node_timeseries
  const nodeTs = temporal.node_timeseries || {};
  const nodeIds = Object.keys(nodeTs);
  if (nodeIds.length === 0) return null;

  // Find the longest array to determine step count
  const firstNode = nodeTs[nodeIds[0]];
  const stepCount = firstNode?.wait?.length || 0;
  if (stepCount === 0) return null;

  const dt = parameters?.dt_minutes || 2;

  // Aggregate: max wait across nodes and average util per timestep
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

  // Phase boundaries
  const peakCongestion = temporal.peak_congestion_time;
  const congestionStart = temporal.congestion_start_time;
  const congestionEnd = temporal.congestion_end_time;
  const totalTime = chartData[chartData.length - 1]?.t || 0;

  // Infer approximate phase boundaries
  const eventDuration = (parameters?.event_duration_hours || 3) * 60;
  const arrivalEnd = Math.min(peakCongestion ? peakCongestion + 10 : 90, totalTime * 0.4);
  const egressStart = arrivalEnd + eventDuration;

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border-subtle)',
      padding: '16px 20px',
      marginBottom: 8,
    }}>
      <div className="label" style={{ marginBottom: 12 }}>Event Timeline</div>

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
          <XAxis
            dataKey="t"
            stroke="var(--border-subtle)"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border-subtle)' }}
            label={{ value: 'Minutes', position: 'bottom', offset: 8, fill: 'var(--text-tertiary)', fontSize: 10 }}
          />
          <YAxis
            yAxisId="wait"
            stroke="none"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }}
            tickLine={false}
            width={40}
            label={{ value: 'Wait (min)', angle: -90, position: 'insideLeft', offset: 0, fill: 'var(--text-tertiary)', fontSize: 10 }}
          />
          <YAxis
            yAxisId="util"
            orientation="right"
            stroke="none"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }}
            tickLine={false}
            width={40}
            domain={[0, 1]}
          />

          <Tooltip content={<CustomTooltip />} />

          {/* EVENT START dashed marker */}
          {arrivalEnd < totalTime && (
            <ReferenceLine
              x={Math.round(arrivalEnd)}
              yAxisId="wait"
              stroke="var(--border-active)"
              strokeDasharray="4 4"
              label={{ value: 'EVENT START', position: 'bottom', fill: 'var(--text-tertiary)', fontSize: 9 }}
            />
          )}
          {egressStart < totalTime && (
            <ReferenceLine
              x={Math.round(egressStart)}
              yAxisId="wait"
              stroke="var(--border-active)"
              strokeDasharray="4 4"
              label={{ value: 'EGRESS', position: 'bottom', fill: 'var(--text-tertiary)', fontSize: 9 }}
            />
          )}

          {/* Peak congestion marker with value annotation */}
          {peakCongestion && (() => {
            const peakPoint = chartData.find(d => d.t === Math.round(peakCongestion));
            const peakVal = peakPoint?.wait;
            const peakLabel = peakVal != null ? `PEAK: ${peakVal.toFixed(1)} min` : 'PEAK';
            return (
              <ReferenceLine
                x={Math.round(peakCongestion)}
                yAxisId="wait"
                stroke="var(--status-warn)"
                strokeWidth={1}
                strokeOpacity={0.6}
                label={{
                  value: peakLabel,
                  position: 'top',
                  fill: 'var(--status-warn)',
                  fontSize: 10,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              />
            );
          })()}

          <Line
            yAxisId="wait"
            type="monotone"
            dataKey="wait"
            name="Wait Time (min)"
            stroke="var(--status-warn)"
            strokeWidth={1.5}
            dot={false}
            animationDuration={400}
          />
          <Line
            yAxisId="util"
            type="monotone"
            dataKey="util"
            name="Avg Utilization"
            stroke="var(--text-secondary)"
            strokeWidth={1}
            strokeOpacity={0.4}
            dot={false}
            animationDuration={400}
          />
        </LineChart>
      </ResponsiveContainer>

      <div style={{
        display: 'flex',
        gap: 24,
        marginTop: 8,
        fontSize: 10,
        color: 'var(--text-tertiary)',
      }}>
        <span>
          <span style={{ display: 'inline-block', width: 16, height: 2, background: 'var(--status-warn)', marginRight: 6, verticalAlign: 'middle' }} />
          Wait Time
        </span>
        <span>
          <span style={{ display: 'inline-block', width: 16, height: 2, background: 'var(--text-secondary)', opacity: 0.4, marginRight: 6, verticalAlign: 'middle' }} />
          Utilization
        </span>
      </div>
    </div>
  );
}

function UtilizationBarChart({ simulation }) {
  // Show top nodes by utilization as a bar chart
  const nodeMetrics = simulation?.node_metrics || {};
  const entries = Object.entries(nodeMetrics)
    .map(([id, m]) => ({ id, util: m.util_mean || 0, wait: m.wait_mean || 0 }))
    .sort((a, b) => b.util - a.util)
    .slice(0, 10);

  if (entries.length === 0) return null;

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border-subtle)',
      padding: '16px 20px',
      marginBottom: 8,
    }}>
      <div className="label" style={{ marginBottom: 12 }}>Node Utilization</div>

      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={entries} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 100 }}>
          <XAxis
            type="number"
            domain={[0, 1]}
            stroke="var(--border-subtle)"
            tick={{ fill: 'var(--text-tertiary)', fontSize: 10 }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="id"
            stroke="none"
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
            tickLine={false}
            width={96}
          />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="util" name="Utilization" animationDuration={400}>
            {entries.map((e, i) => (
              <Cell
                key={i}
                fill={e.util >= 0.9 ? 'var(--status-danger)' : e.util >= 0.7 ? 'var(--status-warn)' : 'var(--accent)'}
                fillOpacity={0.7}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function TemporalChart({ temporalData, simulationResults }) {
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
