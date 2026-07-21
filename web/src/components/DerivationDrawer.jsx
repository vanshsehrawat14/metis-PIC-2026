import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useCallback } from 'react';
import { DERIVATION_MAP } from '../utils/derivations';
import { formatDollars } from '../utils/formatters';
import {
  BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Cell,
} from 'recharts';

/* ─── Shared styles ─── */
const MONO = "'IBM Plex Mono', 'JetBrains Mono', monospace";
const LABEL_STYLE = {
  fontFamily: MONO,
  fontSize: '0.65rem',
  fontWeight: 500,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-tertiary)',
};
const CODE_BLOCK = {
  fontFamily: MONO,
  fontSize: '0.8rem',
  background: 'rgba(255,255,255,0.03)',
  padding: '12px 16px',
  lineHeight: 1.7,
  color: 'var(--text-primary)',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
};

/* ─── Sub-components for each metric type ─── */

function InputsTable({ inputs }) {
  if (!inputs?.length) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={LABEL_STYLE}>Inputs</div>
      {inputs.map((inp, i) => (
        <div key={i} style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <div>
            <span style={{ fontFamily: MONO, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              {inp.label}
            </span>
            {inp.note && (
              <div style={{ fontFamily: MONO, fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 2 }}>
                {inp.note}
              </div>
            )}
          </div>
          <span style={{ fontFamily: MONO, fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-primary)' }}>
            {inp.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function DistributionBar({ p10, mean, p90 }) {
  if (p10 == null || p90 == null || mean == null) return null;
  const max = Math.max(p90 * 1.3, 1);
  const norm = v => Math.max(0, Math.min(1, v / max));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={LABEL_STYLE}>Monte Carlo Distribution</div>
      <div style={{ position: 'relative', height: 48, background: 'rgba(255,255,255,0.02)', padding: '12px 0' }}>
        {/* P10–P90 band */}
        <div style={{
          position: 'absolute', top: 16, height: 16,
          left: `${norm(p10) * 100}%`,
          width: `${(norm(p90) - norm(p10)) * 100}%`,
          background: 'rgba(74, 123, 247, 0.15)',
          border: '1px solid rgba(74, 123, 247, 0.25)',
        }} />
        {/* Mean tick */}
        <div style={{
          position: 'absolute', top: 10, height: 28, width: 2,
          left: `${norm(mean) * 100}%`, transform: 'translateX(-50%)',
          background: 'var(--accent)',
        }} />
        {/* Labels */}
        <div style={{
          position: 'absolute', bottom: -18, left: `${norm(p10) * 100}%`,
          fontFamily: MONO, fontSize: 10, color: 'var(--text-tertiary)',
          transform: 'translateX(-50%)',
        }}>P10: {p10.toFixed(1)}</div>
        <div style={{
          position: 'absolute', bottom: -18, left: `${norm(mean) * 100}%`,
          fontFamily: MONO, fontSize: 10, color: 'var(--accent)', fontWeight: 500,
          transform: 'translateX(-50%)',
        }}>μ: {mean.toFixed(1)}</div>
        <div style={{
          position: 'absolute', bottom: -18, left: `${norm(p90) * 100}%`,
          fontFamily: MONO, fontSize: 10, color: 'var(--text-tertiary)',
          transform: 'translateX(-50%)',
        }}>P90: {p90.toFixed(1)}</div>
      </div>
      <div style={{ height: 16 }} /> {/* spacer for labels */}
    </div>
  );
}

function FactorBars({ factors }) {
  if (!factors?.length) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={LABEL_STYLE}>Factor Breakdown</div>
      {factors.map((f, i) => {
        const val = f.value != null ? f.value : 1;
        const contribution = f.weight * val + (1 - f.weight);
        return (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <span style={{ fontFamily: MONO, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                {f.name}
              </span>
              <span style={{ fontFamily: MONO, fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>
                w={f.weight.toFixed(2)}
                {f.value != null ? ` · f=${f.value.toFixed(2)}` : ''}
                {' · '}contribution={contribution.toFixed(3)}
              </span>
            </div>
            <div style={{ height: 6, background: 'rgba(255,255,255,0.04)', position: 'relative' }}>
              <div style={{
                height: '100%', width: `${Math.min(val, 1) * 100}%`,
                background: f.color || 'var(--accent)', opacity: 0.6,
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function GradeScale({ gradeScale, currentScore }) {
  if (!gradeScale?.length || currentScore == null) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={LABEL_STYLE}>Grade Scale</div>
      <div style={{ display: 'flex', gap: 0, height: 32 }}>
        {gradeScale.map((g, i) => {
          const isActive = currentScore >= g.min && (i === 0 || currentScore < gradeScale[i - 1].min);
          return (
            <div key={g.label} style={{
              flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'center', gap: 2,
              background: isActive ? 'rgba(74, 123, 247, 0.12)' : 'rgba(255,255,255,0.02)',
              border: isActive ? '1px solid rgba(74, 123, 247, 0.3)' : '1px solid rgba(255,255,255,0.04)',
            }}>
              <span style={{
                fontFamily: MONO, fontSize: 11, fontWeight: isActive ? 600 : 400,
                color: isActive ? 'var(--accent)' : 'var(--text-tertiary)',
              }}>
                {g.label}
              </span>
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: MONO, fontSize: 9, color: 'var(--text-tertiary)' }}>
        <span>100</span>
        <span>0</span>
      </div>
    </div>
  );
}

function SubScoreGauges({ subScores }) {
  if (!subScores?.length) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={LABEL_STYLE}>Component Scores</div>
      {subScores.map((s, i) => {
        const val = s.value != null ? s.value : 0;
        const pct = Math.min(val, 1) * 100;
        const barColor = val >= 0.7 ? 'var(--status-danger)' : val >= 0.4 ? 'var(--status-warn)' : 'var(--status-safe)';
        return (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <span style={{ fontFamily: MONO, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                {s.name}
              </span>
              <span style={{ fontFamily: MONO, fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-primary)' }}>
                {val.toFixed(2)}
              </span>
            </div>
            <div style={{ height: 6, background: 'rgba(255,255,255,0.04)', position: 'relative' }}>
              <div style={{ height: '100%', width: `${pct}%`, background: barColor, opacity: 0.7 }} />
            </div>
            <div style={{ fontFamily: MONO, fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>
              {s.description}
            </div>
            <div style={{ fontFamily: MONO, fontSize: '0.65rem', color: 'var(--text-tertiary)', opacity: 0.7 }}>
              {s.threshold}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RevenueBreakdown({ breakdown, attendance, perHeadBaseline, perHeadActual }) {
  if (!breakdown?.length) return null;
  const chartData = breakdown.filter(b => b.value > 0).map(b => ({
    name: b.name,
    value: b.value,
    color: b.color,
  }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={LABEL_STYLE}>Loss Breakdown</div>
      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={80}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 100 }}>
            <XAxis type="number" hide />
            <YAxis
              type="category" dataKey="name" width={96}
              tick={{ fill: 'var(--text-tertiary)', fontSize: 10, fontFamily: MONO }}
              tickLine={false} axisLine={false}
            />
            <Bar dataKey="value" maxBarSize={12}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.color} fillOpacity={0.65} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
      {breakdown.map((b, i) => (
        <div key={i} style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <div>
            <span style={{ fontFamily: MONO, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{b.name}</span>
            {b.note && (
              <div style={{ fontFamily: MONO, fontSize: '0.65rem', color: 'var(--text-tertiary)', marginTop: 2 }}>{b.note}</div>
            )}
          </div>
          <span style={{ fontFamily: MONO, fontSize: '0.85rem', fontWeight: 500, color: b.value > 0 ? 'var(--status-warn)' : 'var(--text-tertiary)' }}>
            {formatDollars(b.value)}
          </span>
        </div>
      ))}
      {attendance > 0 && perHeadBaseline > 0 && (
        <div style={{ fontFamily: MONO, fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 4 }}>
          Industry avg: ${perHeadBaseline.toFixed(2)}/head · Scenario: ${perHeadActual.toFixed(2)}/head
        </div>
      )}
    </div>
  );
}

function NodeRanking({ top5 }) {
  if (!top5?.length) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={LABEL_STYLE}>Top 5 Nodes by Utilization</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {top5.map((n, i) => {
          const barColor = n.utilization >= 0.9 ? 'var(--status-danger)' : n.utilization >= 0.7 ? 'var(--status-warn)' : 'var(--accent)';
          return (
            <div key={i} style={{
              display: 'grid', gridTemplateColumns: '24px 1fr 64px',
              gap: 8, padding: '6px 0', alignItems: 'center',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>
              <span style={{ fontFamily: MONO, fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <span style={{ fontFamily: MONO, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                  {n.id}
                </span>
                <div style={{ height: 4, background: 'rgba(255,255,255,0.04)', position: 'relative' }}>
                  <div style={{
                    height: '100%', width: `${Math.min(n.utilization, 1) * 100}%`,
                    background: barColor, opacity: 0.6,
                  }} />
                </div>
              </div>
              <span style={{ fontFamily: MONO, fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-primary)', textAlign: 'right' }}>
                {(n.utilization * 100).toFixed(0)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FruinScale({ distribution, worstNode }) {
  if (!distribution?.length) return null;
  const totalNodes = distribution.reduce((sum, d) => sum + d.count, 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={LABEL_STYLE}>Fruin Scale</div>
      {/* Grade distribution */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {distribution.map(d => {
          const gradeColor = d.grade >= 'E' ? 'var(--status-danger)' : d.grade >= 'C' ? 'var(--status-warn)' : 'var(--status-safe)';
          const pct = totalNodes > 0 ? (d.count / totalNodes) * 100 : 0;
          return (
            <div key={d.grade} style={{
              display: 'grid', gridTemplateColumns: '24px 1fr 80px 40px',
              gap: 8, alignItems: 'center', padding: '4px 0',
            }}>
              <span style={{
                fontFamily: MONO, fontSize: '0.85rem', fontWeight: 600,
                color: d.count > 0 ? gradeColor : 'var(--text-tertiary)',
              }}>
                {d.grade}
              </span>
              <div style={{ height: 6, background: 'rgba(255,255,255,0.04)', position: 'relative' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: gradeColor, opacity: 0.5 }} />
              </div>
              {d.info && (
                <span style={{ fontFamily: MONO, fontSize: '0.6rem', color: 'var(--text-tertiary)' }}>
                  {d.info.density} p/m²
                </span>
              )}
              <span style={{ fontFamily: MONO, fontSize: '0.75rem', color: 'var(--text-tertiary)', textAlign: 'right' }}>
                {d.count}
              </span>
            </div>
          );
        })}
      </div>
      {/* Density/speed reference */}
      <div style={LABEL_STYLE}>Reference</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {distribution.filter(d => d.info).map(d => (
          <div key={d.grade} style={{
            display: 'grid', gridTemplateColumns: '24px 1fr',
            gap: 8, padding: '2px 0',
          }}>
            <span style={{ fontFamily: MONO, fontSize: '0.65rem', color: 'var(--text-tertiary)' }}>{d.grade}</span>
            <span style={{ fontFamily: MONO, fontSize: '0.65rem', color: 'var(--text-tertiary)' }}>
              {d.info.description} · {d.info.speed}
            </span>
          </div>
        ))}
      </div>
      {/* Worst node */}
      {worstNode && (
        <div style={{
          padding: '12px 16px', background: 'rgba(231, 76, 60, 0.06)',
          border: '1px solid rgba(231, 76, 60, 0.12)',
        }}>
          <div style={{ fontFamily: MONO, fontSize: '0.75rem', color: 'var(--status-danger)' }}>
            Worst node: {worstNode.id}
          </div>
          <div style={{ fontFamily: MONO, fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: 4 }}>
            Density: {worstNode.density.toFixed(2)} p/m² · Grade {worstNode.grade}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Metric-specific content renderers ─── */

function WaitContent({ data }) {
  return (
    <>
      <InputsTable inputs={data.inputs} />
      <DistributionBar p10={data.distribution.p10} mean={data.distribution.mean} p90={data.distribution.p90} />
    </>
  );
}

function HESContent({ data }) {
  return (
    <>
      <FactorBars factors={data.factors} />
      <GradeScale gradeScale={data.gradeScale} currentScore={data.value} />
    </>
  );
}

function SafetyContent({ data }) {
  return (
    <>
      <SubScoreGauges subScores={data.subScores} />
      {data.evacuationTime != null && (
        <div style={{
          padding: '12px 16px', background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.04)', fontFamily: MONO, fontSize: '0.75rem',
          color: 'var(--text-secondary)',
        }}>
          Est. evacuation: {data.evacuationTime.toFixed(0)} min
          {' · '}Target: {data.planningTarget} min
          {' · '}NFPA ref: {data.nfpaTarget} min
        </div>
      )}
    </>
  );
}

function RevenueContent({ data }) {
  return (
    <RevenueBreakdown
      breakdown={data.breakdown}
      attendance={data.attendance}
      perHeadBaseline={data.perHeadBaseline}
      perHeadActual={data.perHeadActual}
    />
  );
}

function BottleneckContent({ data }) {
  return (
    <>
      <div style={{
        padding: '12px 16px', background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.04)', fontFamily: MONO, fontSize: '0.75rem',
        color: data.overloaded ? 'var(--status-danger)' : 'var(--text-secondary)',
      }}>
        {data.explanation}
      </div>
      <NodeRanking top5={data.top5} />
    </>
  );
}

function FruinContent({ data }) {
  return <FruinScale distribution={data.distribution} worstNode={data.worstNode} />;
}

const CONTENT_MAP = {
  wait: WaitContent,
  experience: HESContent,
  safety: SafetyContent,
  revenue: RevenueContent,
  bottleneck: BottleneckContent,
  fruin: FruinContent,
};

/* ─── Main Drawer ─── */

export default function DerivationDrawer({ metricKey, results, onClose }) {
  const derivationFn = DERIVATION_MAP[metricKey];
  const data = derivationFn ? derivationFn(results) : null;
  const ContentComponent = CONTENT_MAP[metricKey];

  // Escape key closes drawer
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') onClose?.();
  }, [onClose]);

  useEffect(() => {
    if (metricKey) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [metricKey, handleKeyDown]);

  return (
    <AnimatePresence>
      {metricKey && data && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            style={{
              position: 'fixed', inset: 0, zIndex: 998,
              background: 'rgba(0, 0, 0, 0.4)',
            }}
          />

          {/* Drawer */}
          <motion.div
            initial={{ x: 480 }}
            animate={{ x: 0 }}
            exit={{ x: 480 }}
            transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            style={{
              position: 'fixed', top: 0, right: 0, bottom: 0,
              width: 480, zIndex: 999,
              background: 'rgba(8, 9, 26, 0.95)',
              backdropFilter: 'blur(24px)',
              WebkitBackdropFilter: 'blur(24px)',
              borderLeft: '1px solid rgba(74, 123, 247, 0.15)',
              display: 'flex', flexDirection: 'column',
              overflowY: 'auto',
            }}
          >
            {/* Header */}
            <div style={{
              padding: '24px 24px 16px',
              borderBottom: '1px solid rgba(255,255,255,0.06)',
              flexShrink: 0,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{
                    fontFamily: MONO, fontWeight: 600, fontSize: '0.65rem',
                    letterSpacing: '0.12em', textTransform: 'uppercase',
                    color: 'var(--text-tertiary)', marginBottom: 8,
                  }}>
                    Derivation
                  </div>
                  <div style={{
                    fontFamily: MONO, fontWeight: 600, fontSize: '1.1rem',
                    color: 'var(--text-primary)', letterSpacing: '-0.01em',
                  }}>
                    {data.title}
                  </div>
                </div>

                {/* Close button */}
                <button
                  onClick={onClose}
                  style={{
                    background: 'none', border: 'none', color: 'var(--text-tertiary)',
                    fontSize: 20, cursor: 'pointer', padding: '0 4px',
                    fontFamily: MONO, lineHeight: 1,
                  }}
                  onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; }}
                  onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-tertiary)'; }}
                  aria-label="Close derivation drawer"
                >
                  ×
                </button>
              </div>

              {/* Large value */}
              <div style={{ marginTop: 12, display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{
                  fontFamily: MONO, fontWeight: 600, fontSize: '2rem',
                  color: 'var(--text-primary)', letterSpacing: '-0.02em',
                  fontVariantNumeric: 'tabular-nums',
                }}>
                  {typeof data.value === 'number'
                    ? (metricKey === 'revenue' ? formatDollars(data.value) : data.value.toFixed(metricKey === 'safety' ? 2 : metricKey === 'experience' ? 0 : 1))
                    : data.value}
                </span>
                {data.unit && (
                  <span style={{
                    fontFamily: MONO, fontWeight: 400, fontSize: '0.85rem',
                    color: 'var(--text-tertiary)',
                  }}>
                    {data.unit}
                  </span>
                )}
              </div>
            </div>

            {/* Body */}
            <div style={{
              padding: 24, display: 'flex', flexDirection: 'column', gap: 24,
              flex: 1, overflowY: 'auto',
            }}>
              {/* Formula */}
              {data.formula && (
                <div>
                  <div style={{ ...LABEL_STYLE, marginBottom: 8 }}>Formula</div>
                  <div style={CODE_BLOCK}>{data.formula}</div>
                  {data.formulaName && (
                    <div style={{
                      fontFamily: MONO, fontSize: '0.65rem', color: 'var(--text-tertiary)',
                      marginTop: 6, fontStyle: 'italic',
                    }}>
                      {data.formulaName}
                    </div>
                  )}
                </div>
              )}

              {/* Metric-specific content */}
              {ContentComponent && <ContentComponent data={data} />}

              {/* Source badge */}
              {data.source && (
                <div style={{
                  padding: '10px 16px',
                  background: 'rgba(74, 123, 247, 0.04)',
                  border: '1px solid rgba(74, 123, 247, 0.1)',
                  fontFamily: MONO, fontSize: '0.65rem',
                  color: 'var(--text-tertiary)', lineHeight: 1.5,
                  letterSpacing: '0.02em',
                }}>
                  {data.source}
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
