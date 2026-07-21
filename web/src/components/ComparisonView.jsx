import { formatDollars, formatHES, statusColor, riskColor } from '../utils/formatters';

function DeltaRow({ label, baseVal, modVal, unit, fmt, higherIsBetter }) {
  const format = fmt || (v => v != null ? String(v) : '--');
  const delta = baseVal != null && modVal != null ? modVal - baseVal : null;

  let deltaColor = 'var(--text-tertiary)';
  let deltaStr = null;
  if (delta != null && Math.abs(delta) > 0.005) {
    const improved = higherIsBetter ? delta > 0 : delta < 0;
    deltaColor = improved ? 'var(--status-safe)' : 'var(--status-danger)';
    deltaStr = `${delta > 0 ? '+' : ''}${format(delta)}`;
  }

  return (
    <div style={{
      padding: '9px 0',
      borderBottom: '1px solid var(--border-subtle)',
      display: 'flex',
      alignItems: 'baseline',
      gap: 6,
      flexWrap: 'wrap',
    }}>
      <span style={{
        fontSize: 9,
        fontWeight: 500,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: 'var(--text-tertiary)',
        fontFamily: "'JetBrains Mono', monospace",
        width: 116,
        flexShrink: 0,
      }}>
        {label}
      </span>

      {/* Baseline value */}
      <span className="tabular-nums" style={{
        fontSize: 18,
        fontWeight: 300,
        color: 'var(--text-tertiary)',
        fontFamily: "'JetBrains Mono', monospace",
      }}>
        {format(baseVal)}
      </span>
      {unit && (
        <span style={{ fontSize: 10, color: 'var(--text-tertiary)', fontFamily: "'JetBrains Mono', monospace" }}>
          {unit}
        </span>
      )}

      <span style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: '0 2px' }}>→</span>

      {/* Modified value */}
      <span className="tabular-nums" style={{
        fontSize: 18,
        fontWeight: 300,
        color: 'var(--text-primary)',
        fontFamily: "'JetBrains Mono', monospace",
      }}>
        {format(modVal)}
      </span>
      {unit && (
        <span style={{ fontSize: 10, color: 'var(--text-secondary)', fontFamily: "'JetBrains Mono', monospace" }}>
          {unit}
        </span>
      )}

      {/* Delta badge */}
      {deltaStr && (
        <span style={{
          marginLeft: 'auto',
          fontSize: 11,
          fontFamily: "'JetBrains Mono', monospace",
          color: deltaColor,
          fontWeight: 500,
          flexShrink: 0,
        }}>
          ({deltaStr})
        </span>
      )}
    </div>
  );
}

export default function ComparisonView({ baseline, modified }) {
  if (!baseline?.metrics || !modified?.metrics) return null;

  const baseOp = baseline.metrics.operational || {};
  const modOp = modified.metrics.operational || {};
  const baseExp = baseline.metrics.experience || {};
  const modExp = modified.metrics.experience || {};
  const baseSafety = baseline.metrics.safety || {};
  const modSafety = modified.metrics.safety || {};
  const baseRev = baseline.metrics.revenue || {};
  const modRev = modified.metrics.revenue || {};

  const baseHes = formatHES(baseExp.hes);
  const modHes = formatHES(modExp.hes);

  return (
    <div style={{ fontFamily: "'JetBrains Mono', monospace" }}>
      {/* Header */}
      <div style={{
        marginBottom: 12,
        paddingBottom: 10,
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
      }}>
        <span style={{
          fontSize: 9,
          fontWeight: 500,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--text-tertiary)',
        }}>
          Comparison
        </span>
        <span style={{ fontSize: 10, color: 'var(--accent)', letterSpacing: '0.06em' }}>
          baseline → modified
        </span>
      </div>

      <DeltaRow
        label="Wait Time"
        baseVal={baseOp.wait_time?.mean}
        modVal={modOp.wait_time?.mean}
        unit="min"
        fmt={v => v?.toFixed(1)}
      />
      <DeltaRow
        label="Experience"
        baseVal={baseExp.hes}
        modVal={modExp.hes}
        unit="/ 100"
        fmt={v => v?.toFixed(0)}
        higherIsBetter
      />
      <DeltaRow
        label="Safety SRS"
        baseVal={baseSafety.srs}
        modVal={modSafety.srs}
        unit=""
        fmt={v => v?.toFixed(2)}
      />
      <DeltaRow
        label="Revenue Impact"
        baseVal={baseRev.total_current_event_loss}
        modVal={modRev.total_current_event_loss}
        unit=""
        fmt={v => formatDollars(v)}
      />

      {/* Grade row */}
      <div style={{ padding: '9px 0', fontSize: 10, color: 'var(--text-tertiary)', display: 'flex', gap: 16 }}>
        <span>HES {baseHes.grade} → {modHes.grade}</span>
        {baseSafety.risk_level && modSafety.risk_level && (
          <span>Risk {baseSafety.risk_level} → {modSafety.risk_level}</span>
        )}
      </div>
    </div>
  );
}
