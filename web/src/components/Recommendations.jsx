const CATEGORY_STYLES = {
  safety:     { bg: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' },
  revenue:    { bg: 'rgba(234, 179, 8, 0.15)',  color: '#eab308' },
  experience: { bg: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' },
  congestion: { bg: 'rgba(249, 115, 22, 0.15)', color: '#f97316' },
  merch:      { bg: 'rgba(139, 143, 163, 0.15)', color: 'var(--text-secondary)' },
};

export default function Recommendations({ recommendations }) {
  if (!recommendations?.length) return null;

  return (
    <div style={{ padding: '0 24px 16px' }}>
      <div style={{
        fontFamily: 'var(--font-label)',
        fontSize: '0.65rem',
        fontWeight: 500,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: 'var(--text-tertiary)',
        marginBottom: 16,
      }}>
        Recommendations
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {recommendations.slice(0, 5).map((rec, i) => {
          const cat = (rec.category || 'general').toLowerCase();
          const style = CATEGORY_STYLES[cat] || { bg: 'rgba(85, 89, 112, 0.15)', color: 'var(--text-tertiary)' };

          return (
            <div
              key={i}
              className="glass-panel"
              style={{
                display: 'grid',
                gridTemplateColumns: '32px 1fr',
                gap: 16,
                padding: 16,
                alignItems: 'start',
              }}
            >
              {/* Numbered circle */}
              <div style={{
                width: 28,
                height: 28,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px solid var(--border-active)',
                borderRadius: '50%',
                fontFamily: 'var(--font-data)',
                fontSize: '0.75rem',
                fontWeight: 500,
                color: 'var(--text-tertiary)',
                flexShrink: 0,
              }}>
                {String(i + 1).padStart(2, '0')}
              </div>

              <div>
                {/* Category pill */}
                <span style={{
                  display: 'inline-block',
                  padding: '2px 10px',
                  borderRadius: 12,
                  background: style.bg,
                  color: style.color,
                  fontFamily: 'var(--font-data)',
                  fontSize: '0.6rem',
                  fontWeight: 600,
                  letterSpacing: '0.1em',
                  textTransform: 'uppercase',
                  marginBottom: 8,
                }}>
                  {cat.toUpperCase()}
                </span>

                {/* Action text */}
                <div style={{
                  fontSize: '0.8rem',
                  color: 'var(--text-primary)',
                  lineHeight: 1.5,
                  fontFamily: 'var(--font-data)',
                }}>
                  {rec.action}
                </div>

                {/* Impact subtext */}
                {rec.expected_impact && (
                  <div style={{
                    fontSize: '0.7rem',
                    color: 'var(--text-secondary)',
                    marginTop: 8,
                    fontFamily: 'var(--font-data)',
                    opacity: 0.7,
                  }}>
                    {rec.expected_impact}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
