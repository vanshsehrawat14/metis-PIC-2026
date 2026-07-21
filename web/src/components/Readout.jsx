import { motion } from 'framer-motion';
import { useState } from 'react';
import { formatDollars, formatHES, statusColor, riskColor } from '../utils/formatters';

/* ─── Inline Chevron SVG (no lucide-react dependency) ─── */
function ChevronRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={{ opacity: 0.3, transition: 'opacity 150ms ease', flexShrink: 0 }}
      className="row-chevron"
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

/* ─── Status Tooltip ─── */
const TOOLTIP_TEXT = {
  CRITICAL: 'Crowd density exceeds safe thresholds. Immediate intervention recommended.',
  HIGH: 'Wait times exceed 60 minutes. Attendee experience severely impacted.',
  FAIR: 'Experience is below average. Multiple factors contributing to degradation.',
  SIGNIFICANT: 'Estimated revenue loss exceeds $100K per event.',
  MODERATE: 'Metrics are within acceptable but suboptimal ranges.',
  LOW: 'Operating within safe and efficient parameters.',
  MINIMAL: 'Negligible impact on operations.',
  EXCELLENT: 'Exceptional attendee experience across all factors.',
  GOOD: 'Attendee experience meets industry standards.',
  POOR: 'Attendee experience is significantly below expectations.',
  CRIT: 'System resilience is critically compromised.',
};

function StatusTooltip({ label, visible }) {
  const text = TOOLTIP_TEXT[label];
  if (!text || !visible) return null;
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      style={{
        position: 'absolute',
        right: 0,
        top: '100%',
        marginTop: 6,
        padding: '8px 12px',
        background: 'rgba(8, 9, 26, 0.95)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(74, 123, 247, 0.15)',
        fontFamily: "var(--font-data)",
        fontSize: '0.7rem',
        color: 'var(--text-secondary)',
        lineHeight: 1.4,
        maxWidth: 280,
        zIndex: 100,
        whiteSpace: 'normal',
        pointerEvents: 'none',
      }}
    >
      {text}
    </motion.div>
  );
}

/* ─── Range Bar with P10/P90 labels ─── */
function RangeBar({ p10, p90, mean }) {
  if (p10 == null || p90 == null || mean == null) return null;
  const maxVal = Math.max(p90 * 1.25, 1);
  const norm = v => Math.max(0, Math.min(1, v / maxVal));
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
      <span style={{
        fontSize: 9, color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)',
        opacity: 0.4, width: 40, flexShrink: 0,
      }}>
        {p10.toFixed(1)}
      </span>
      <div style={{ flex: 1, height: 3, background: 'var(--border-subtle)', position: 'relative' }}>
        {/* P10–P90 band */}
        <div style={{
          position: 'absolute',
          left: `${norm(p10) * 100}%`,
          width: `${(norm(p90) - norm(p10)) * 100}%`,
          height: '100%',
          background: 'var(--text-tertiary)',
          opacity: 0.5,
        }} />
        {/* Mean tick */}
        <div style={{
          position: 'absolute',
          left: `${norm(mean) * 100}%`,
          transform: 'translateX(-50%)',
          width: 2,
          height: 7,
          background: 'var(--accent)',
          top: -2,
        }} />
      </div>
      <span style={{
        fontSize: 9, color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)',
        opacity: 0.4, width: 40, textAlign: 'right', flexShrink: 0,
      }}>
        {p90.toFixed(1)}
      </span>
    </div>
  );
}

/* ─── Metric Row ─── */
function Row({ label, value, unit, dotColor, statusLabel, children, noBorder, metricKey, onMetricClick, index }) {
  const [tooltipVisible, setTooltipVisible] = useState(false);

  return (
    <motion.div
      className="metric-row"
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.06, duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
      onClick={() => onMetricClick?.(metricKey)}
      style={{
        padding: '8px 8px 8px 0',
        borderBottom: noBorder ? 'none' : '1px solid var(--border-subtle)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{
          fontFamily: 'var(--font-label)',
          fontSize: '0.65rem',
          fontWeight: 500,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--text-tertiary)',
          width: 116,
          flexShrink: 0,
        }}>
          {label}
        </span>
        <span className="tabular-nums" style={{
          fontFamily: 'var(--font-data)',
          fontSize: '2rem',
          fontWeight: 600,
          color: 'var(--text-primary)',
          lineHeight: 1,
          letterSpacing: '-0.02em',
        }}>
          {value}
        </span>
        {unit && (
          <span style={{
            fontFamily: 'var(--font-data)',
            fontSize: '0.85rem',
            fontWeight: 400,
            color: 'var(--text-tertiary)',
            opacity: 0.45,
          }}>
            {unit}
          </span>
        )}
        {dotColor && statusLabel && (
          <span
            style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, position: 'relative' }}
            onMouseEnter={() => setTooltipVisible(true)}
            onMouseLeave={() => setTooltipVisible(false)}
          >
            <span className="status-dot" style={{ background: dotColor }} />
            <span className="data-badge" style={{ color: dotColor }}>
              {statusLabel}
            </span>
            <StatusTooltip label={statusLabel} visible={tooltipVisible} />
          </span>
        )}
        <ChevronRight />
      </div>
      {children}
    </motion.div>
  );
}

/* ─── Main Readout ─── */
export default function Readout({ results, onMetricClick }) {
  if (!results) return null;

  const metrics = results.metrics || {};
  const op = metrics.operational || {};
  const exp = metrics.experience || {};
  const safety = metrics.safety || {};
  const rev = metrics.revenue || {};
  const fruin = metrics.fruin || {};

  const waitMean = op.wait_time?.mean;
  const waitP10 = op.wait_time?.p10;
  const waitP90 = op.wait_time?.p90;

  const hes = exp.hes;
  const hesInfo = formatHES(hes);

  const riskLevel = safety.risk_level || 'LOW';
  const srs = safety.srs;

  const totalLoss = rev.total_current_event_loss || 0;

  // Top bottleneck node
  const nodeMetrics = results.simulation?.node_metrics || {};
  const topNodes = Object.entries(nodeMetrics)
    .sort((a, b) => (b[1].util_mean || 0) - (a[1].util_mean || 0));
  const [bottleneckId, bottleneckData] = topNodes[0] || [];

  // Fruin grade distribution
  const gradeDist = fruin.grade_distribution || {};
  const worstGrade = fruin.worst_grade;

  let rowIndex = 0;

  return (
    <div className="glass-panel" style={{
      fontFamily: 'var(--font-data)',
      padding: 24,
    }}>
      {/* Venue + scenario header */}
      {results.venue_name && (
        <div style={{ marginBottom: 16, paddingBottom: 16, borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{
            fontFamily: 'var(--font-editorial)',
            fontSize: 18,
            color: 'var(--text-primary)',
            lineHeight: 1.2,
          }}>
            {results.venue_name}
          </div>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 8,
            flexWrap: 'wrap',
          }}>
            <span style={{
              fontFamily: 'var(--font-data)',
              fontSize: '0.7rem',
              color: 'var(--text-tertiary)',
              letterSpacing: '0.06em',
            }}>
              {results.parameters?.attendance?.toLocaleString()} attendees
              {' · '}
              {(results.parameters?.event_type || '').toUpperCase()}
              {results.computation_time_ms != null
                ? ` · ${results.computation_time_ms.toFixed(0)}ms`
                : ''}
            </span>
            {/* Model confidence badge */}
            <span style={{
              fontFamily: 'var(--font-data)',
              fontSize: 9,
              fontWeight: 600,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--status-warn)',
              marginLeft: 'auto',
            }}>
              MODEL CONFIDENCE: LOW
            </span>
          </div>
        </div>
      )}

      {/* WAIT TIME */}
      {waitMean != null && (
        <Row
          label="Wait Time"
          value={waitMean.toFixed(1)}
          unit="min"
          dotColor={statusColor('wait', waitMean)}
          statusLabel={waitMean < 10 ? 'LOW' : waitMean < 20 ? 'MODERATE' : 'HIGH'}
          metricKey="wait"
          onMetricClick={onMetricClick}
          index={rowIndex++}
        >
          <RangeBar p10={waitP10} p90={waitP90} mean={waitMean} />
        </Row>
      )}

      {/* EXPERIENCE */}
      {hes != null && (
        <Row
          label="Experience"
          value={hesInfo.score}
          unit="/ 100"
          dotColor={statusColor('hes', hes)}
          statusLabel={hesInfo.grade.toUpperCase()}
          metricKey="experience"
          onMetricClick={onMetricClick}
          index={rowIndex++}
        >
          <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 8, fontFamily: 'var(--font-data)' }}>
            HES · Human Experience Score
          </div>
        </Row>
      )}

      {/* SAFETY */}
      {srs != null && (
        <Row
          label="Safety"
          value={srs.toFixed(2)}
          unit="SRS"
          dotColor={riskColor(riskLevel)}
          statusLabel={riskLevel}
          metricKey="safety"
          onMetricClick={onMetricClick}
          index={rowIndex++}
        >
          <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 8, display: 'flex', gap: 16, fontFamily: 'var(--font-data)' }}>
            {safety.crush_risk != null && <span>Crush: {safety.crush_risk.toFixed(2)}</span>}
            {safety.flow_risk != null && <span>Flow: {safety.flow_risk.toFixed(2)}</span>}
            {safety.evac_risk != null && <span>Evac: {safety.evac_risk.toFixed(2)}</span>}
          </div>
        </Row>
      )}

      {/* REVENUE IMPACT */}
      {totalLoss > 0 && (
        <Row
          label="Revenue Impact"
          value={formatDollars(totalLoss)}
          unit="est. loss"
          dotColor={
            totalLoss > 100000 ? 'var(--status-danger)'
            : totalLoss > 30000 ? 'var(--status-warn)'
            : 'var(--status-safe)'
          }
          statusLabel={
            totalLoss > 100000 ? 'SIGNIFICANT'
            : totalLoss > 30000 ? 'MODERATE'
            : 'MINIMAL'
          }
          metricKey="revenue"
          onMetricClick={onMetricClick}
          index={rowIndex++}
        >
          <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 8, display: 'flex', gap: 16, fontFamily: 'var(--font-data)' }}>
            {rev.concession_loss != null && <span>Concession: {formatDollars(rev.concession_loss)}</span>}
            {rev.merch_loss != null && <span>Merch: {formatDollars(rev.merch_loss)}</span>}
          </div>
        </Row>
      )}

      {/* BOTTLENECK */}
      {bottleneckId && (
        <Row
          label="Bottleneck"
          value={bottleneckId.replace(/_/g, ' ')}
          unit=""
          dotColor={
            (bottleneckData.util_mean || 0) >= 0.9 ? 'var(--status-danger)'
            : (bottleneckData.util_mean || 0) >= 0.7 ? 'var(--status-warn)'
            : 'var(--status-safe)'
          }
          statusLabel={`${((bottleneckData.util_mean || 0) * 100).toFixed(0)}% UTIL`}
          metricKey="bottleneck"
          onMetricClick={onMetricClick}
          index={rowIndex++}
        >
          {bottleneckData.bottleneck_frequency != null && (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 8, fontFamily: 'var(--font-data)' }}>
              Bottleneck in {(bottleneckData.bottleneck_frequency * 100).toFixed(0)}% of MC trials
            </div>
          )}
        </Row>
      )}

      {/* FRUIN LOS */}
      {worstGrade && (
        <Row
          label="Fruin LOS"
          value={`LOS ${worstGrade}`}
          unit=""
          noBorder
          metricKey="fruin"
          onMetricClick={onMetricClick}
          index={rowIndex++}
        >
          <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 8, display: 'flex', gap: 10, fontFamily: 'var(--font-data)' }}>
            {['A', 'B', 'C', 'D', 'E', 'F'].map(g => (
              <span key={g} style={{
                color: (gradeDist[g] || 0) > 0
                  ? (g >= 'D' ? 'var(--status-danger)' : g >= 'C' ? 'var(--status-warn)' : 'var(--status-safe)')
                  : 'var(--border-active)',
              }}>
                {g}:{gradeDist[g] || 0}
              </span>
            ))}
          </div>
        </Row>
      )}
    </div>
  );
}
