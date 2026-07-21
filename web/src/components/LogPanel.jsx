import { useState } from 'react';

// Map log entry type to display color
const TYPE_COLOR = {
  success: 'var(--status-safe)',
  running: 'var(--accent)',
  detail: 'var(--text-tertiary)',
  user: 'var(--text-primary)',
  error: 'var(--status-danger)',
  vane: 'var(--accent)',
};

const COLLAPSED_COUNT = 5;

export default function LogPanel({ entries }) {
  const [expanded, setExpanded] = useState(false);

  if (!entries?.length) return null;

  const displayEntries = expanded ? entries : entries.slice(0, COLLAPSED_COUNT);
  const hasMore = entries.length > COLLAPSED_COUNT;

  return (
    <div style={{ padding: '12px 24px 24px' }}>
      {/* Header row */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 8,
        borderTop: '1px solid var(--border-subtle)',
        paddingTop: 12,
      }}>
        <span style={{
          fontSize: 9,
          fontWeight: 500,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--text-tertiary)',
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          Log
        </span>
        {hasMore && (
          <button
            onClick={() => setExpanded(x => !x)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-tertiary)',
              fontSize: 10,
              fontFamily: "'JetBrains Mono', monospace",
              cursor: 'pointer',
              letterSpacing: '0.06em',
              padding: 0,
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-secondary)'; }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-tertiary)'; }}
          >
            {expanded ? 'Show less' : `Show full log (${entries.length} entries)`}
          </button>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {displayEntries.map(entry => {
          const color = TYPE_COLOR[entry.type] || 'var(--text-tertiary)';
          const isVane = entry.type === 'vane';

          return (
            <div
              key={entry.id}
              style={{
                display: 'flex',
                gap: 10,
                alignItems: 'flex-start',
                lineHeight: 1.5,
              }}
            >
              {/* Timestamp */}
              <span style={{
                color: 'var(--text-tertiary)',
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
                flexShrink: 0,
                width: 50,
                letterSpacing: '0.02em',
                paddingTop: 1,
              }}>
                {entry.time}
              </span>

              {/* Icon */}
              <span style={{
                color,
                flexShrink: 0,
                width: 14,
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
                paddingTop: 1,
              }}>
                {entry.icon}
              </span>

              {/* Content */}
              <span style={{
                color: isVane ? 'var(--text-secondary)' : color === 'var(--text-primary)' ? 'var(--text-primary)' : 'var(--text-secondary)',
                flex: 1,
                fontSize: 12,
                fontFamily: "'JetBrains Mono', monospace",
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                {entry.content}
              </span>
            </div>
          );
        })}
      </div>

      {/* "N earlier entries" indicator */}
      {!expanded && hasMore && (
        <div style={{
          marginTop: 8,
          fontSize: 10,
          color: 'var(--text-tertiary)',
          fontFamily: "'JetBrains Mono', monospace",
          letterSpacing: '0.04em',
          borderTop: '1px solid var(--border-subtle)',
          paddingTop: 8,
        }}>
          {entries.length - COLLAPSED_COUNT} earlier {entries.length - COLLAPSED_COUNT === 1 ? 'entry' : 'entries'}...
        </div>
      )}
    </div>
  );
}
