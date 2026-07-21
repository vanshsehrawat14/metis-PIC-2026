import { motion, useMotionValue, animate } from 'framer-motion';
import { useEffect, useRef } from 'react';

const TEST_LABELS = {
  gate_failure: 'Gate Failure',
  extreme_heat: 'Extreme Heat',
  transit_shutdown: 'Transit Shutdown',
  staffing_cut: 'Staffing Cut',
  mass_egress: 'Mass Egress',
  compound: 'Compound',
};

function severity(delta) {
  const waitDelta = delta?.wait_mean || 0;
  const hesDelta = delta?.hes_mean || 0;
  const waitSev = Math.min(waitDelta / 30, 1);
  const hesSev = Math.min(Math.abs(Math.min(hesDelta, 0)) / 40, 1);
  return Math.max(waitSev, hesSev, 0.05);
}

function impactText(delta) {
  const waitDelta = delta?.wait_mean;
  const hesDelta = delta?.hes_mean;
  if (waitDelta != null && Math.abs(waitDelta) > 0.5) {
    return `Wait ${waitDelta > 0 ? '+' : ''}${waitDelta.toFixed(1)} min`;
  }
  if (hesDelta != null && Math.abs(hesDelta) > 1) {
    return `HES ${hesDelta > 0 ? '+' : ''}${hesDelta.toFixed(0)} pts`;
  }
  return 'Minimal impact';
}

function riskLevel(sev) {
  if (sev >= 0.7) return { label: 'CRIT', color: 'var(--status-danger)' };
  if (sev >= 0.4) return { label: 'WARN', color: 'var(--status-warn)' };
  return { label: 'MOD', color: 'var(--status-safe)' };
}

function sevColor(sev) {
  if (sev >= 0.7) return 'var(--status-danger)';
  if (sev >= 0.4) return 'var(--status-warn)';
  return 'var(--status-safe)';
}

function CountUpScore({ target }) {
  const motionVal = useMotionValue(0);
  const displayRef = useRef(null);

  useEffect(() => {
    const controls = animate(motionVal, target, { duration: 0.8, ease: 'easeOut' });
    const unsub = motionVal.on('change', v => {
      if (displayRef.current) displayRef.current.textContent = Math.round(v);
    });
    return () => { controls.stop(); unsub(); };
  }, [target]);

  return (
    <span
      ref={displayRef}
      className="tabular-nums"
      style={{
        fontSize: 22,
        fontWeight: 300,
        fontFamily: "'JetBrains Mono', monospace",
        color: target >= 70 ? 'var(--status-safe)'
             : target >= 40 ? 'var(--status-warn)'
             : 'var(--status-danger)',
      }}
    >
      0
    </span>
  );
}

export default function StressTestView({ data, onBack }) {
  if (!data?.stress_results) return null;

  const results = data.stress_results;
  const resilience = data.resilience_score;
  const tests = Object.entries(results);

  return (
    <div style={{ fontFamily: "'JetBrains Mono', monospace" }}>
      {/* Header with BACK link */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginBottom: 16,
        paddingBottom: 10,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{
            fontSize: 9,
            fontWeight: 500,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--text-tertiary)',
          }}>
            Stress Resilience
          </span>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <CountUpScore target={resilience ?? 0} />
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>/ 100</span>
          </div>
        </div>

        {onBack && (
          <button
            onClick={onBack}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--accent)',
              fontSize: 10,
              fontFamily: "'JetBrains Mono', monospace",
              cursor: 'pointer',
              letterSpacing: '0.08em',
              padding: 0,
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '0.7'; }}
            onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
          >
            ← Back to Results
          </button>
        )}
      </div>

      {/* Stress test rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {tests.map(([testName, testData], i) => {
          const sev = severity(testData.delta);
          const risk = riskLevel(sev);
          const impact = impactText(testData.delta);
          const barColor = sevColor(sev);

          return (
            <div key={testName} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              fontSize: 11,
            }}>
              {/* Label */}
              <div style={{
                width: 110,
                flexShrink: 0,
                color: 'var(--text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                fontSize: 10,
                fontWeight: 500,
              }}>
                {TEST_LABELS[testName] || testName}
              </div>

              {/* Animated bar */}
              <div style={{
                flex: 1,
                height: 10,
                background: 'var(--bg-primary)',
                position: 'relative',
                overflow: 'hidden',
              }}>
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${sev * 100}%` }}
                  transition={{ duration: 0.4, delay: i * 0.05, ease: 'easeOut' }}
                  style={{
                    height: '100%',
                    background: barColor,
                    opacity: 0.72,
                  }}
                />
              </div>

              {/* Impact text */}
              <div className="tabular-nums" style={{
                width: 120,
                flexShrink: 0,
                color: 'var(--text-secondary)',
                textAlign: 'right',
                fontSize: 11,
              }}>
                {impact}
              </div>

              {/* Risk badge */}
              <div style={{ display: 'flex', alignItems: 'center', width: 48, flexShrink: 0 }}>
                <span className="status-dot" style={{ background: risk.color }} />
                <span style={{ color: risk.color, fontSize: 10, fontWeight: 500 }}>
                  {risk.label}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
