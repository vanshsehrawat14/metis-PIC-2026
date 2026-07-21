import { useState, useEffect } from 'react';
import { useVaneAPI } from '../hooks/useVaneAPI';

function LiveClock() {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const pad = (n) => String(n).padStart(2, '0');
  const dateStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const timeStr = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;

  let tz = '';
  try {
    tz = ' ' + now.toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop();
  } catch {
    tz = '';
  }

  return (
    <div style={{
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      color: 'var(--text-tertiary)',
      letterSpacing: '0.04em',
      marginTop: 4,
      fontWeight: 300,
      fontVariantNumeric: 'tabular-nums',
    }}>
      {dateStr} {timeStr}{tz}
    </div>
  );
}

export default function Header() {
  const [health, setHealth] = useState(null);
  const api = useVaneAPI();

  useEffect(() => {
    api.getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const isOnline = health?.status === 'operational';
  const venueCount = health?.venues_loaded || 0;

  return (
    <header style={{
      height: 64,
      padding: '0 24px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      borderBottom: '1px solid var(--border-subtle)',
      background: 'var(--bg-secondary)',
      flexShrink: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <div>
          <div style={{
            fontFamily: 'var(--font-editorial)',
            fontSize: 18,
            color: 'var(--text-primary)',
            letterSpacing: '0.08em',
            lineHeight: 1.2,
          }}>
            Vane
          </div>
          <div className="label" style={{ marginTop: 2 }}>
            Decision Intelligence Engine
          </div>
        </div>

        {/* Model confidence badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 10px',
          border: '1px solid rgba(243, 156, 18, 0.2)',
          background: 'rgba(243, 156, 18, 0.04)',
        }}>
          <span style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: 'var(--status-warn)',
            flexShrink: 0,
          }} />
          <span style={{
            fontFamily: 'var(--font-data)',
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--status-warn)',
          }}>
            Model Confidence: Low
          </span>
        </div>
      </div>

      <div style={{ textAlign: 'right' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 6,
          fontSize: 10,
          fontWeight: 500,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}>
          <span
            className="status-dot"
            style={{
              background: isOnline ? 'var(--status-safe)' : 'var(--status-danger)',
            }}
          />
          <span style={{ color: isOnline ? 'var(--text-secondary)' : 'var(--status-danger)' }}>
            {isOnline ? 'System Operational' : 'Offline'}
          </span>
        </div>
        <div style={{
          fontSize: 10,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          marginTop: 2,
        }}>
          {isOnline ? `Las Vegas \u00B7 ${venueCount} venues` : 'Backend not connected'}
        </div>
        <LiveClock />
      </div>
    </header>
  );
}
