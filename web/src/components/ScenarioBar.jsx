import { useState, useEffect, useCallback } from 'react';
import { useVaneAPI } from '../hooks/useVaneAPI';

const EVENT_TYPES = [
  { value: 'nfl', label: 'NFL' },
  { value: 'concert', label: 'Concert' },
  { value: 'boxing', label: 'Boxing / MMA' },
  { value: 'basketball', label: 'Basketball' },
  { value: 'convention', label: 'Convention' },
  { value: 'trade_show', label: 'Trade Show' },
  { value: 'soccer', label: 'Soccer' },
  { value: 'hockey', label: 'Hockey' },
  { value: 'esports', label: 'Esports' },
];

/* Today's date as YYYY-MM-DD */
function todayStr() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const FIELD = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
};

const LABEL = {
  fontFamily: 'var(--font-label)',
  fontSize: '0.6rem',
  fontWeight: 500,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-tertiary)',
  userSelect: 'none',
};

const INPUT_BASE = {
  background: 'transparent',
  border: 'none',
  borderBottom: '1px solid var(--border-subtle)',
  color: 'var(--text-primary)',
  fontSize: 13,
  fontFamily: 'var(--font-mono)',
  padding: '2px 0',
  outline: 'none',
};

/* Vertical separator between fields */
function Sep() {
  return (
    <div style={{
      width: 1,
      alignSelf: 'stretch',
      background: 'var(--border-subtle)',
      opacity: 0.5,
      margin: '4px 0',
    }} />
  );
}

function AutoFactorField({ label, value, onChange, isManual, onToggle, disabled }) {
  return (
    <div style={FIELD}>
      <span style={LABEL}>{label}</span>
      {isManual ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={value}
            onChange={e => onChange(Number(e.target.value))}
            disabled={disabled}
            style={{ width: 64, cursor: disabled ? 'not-allowed' : 'pointer', accentColor: 'var(--accent)' }}
          />
          <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', width: 32 }}>
            {Number(value).toFixed(2)}
          </span>
          <button
            onClick={onToggle}
            disabled={disabled}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-tertiary)',
              cursor: disabled ? 'not-allowed' : 'pointer',
              fontSize: 9,
              fontFamily: 'var(--font-mono)',
              letterSpacing: '0.06em',
              padding: 0,
              textDecoration: 'underline',
            }}
          >
            auto
          </button>
        </div>
      ) : (
        <button
          onClick={onToggle}
          disabled={disabled}
          style={{
            ...INPUT_BASE,
            cursor: disabled ? 'not-allowed' : 'pointer',
            textAlign: 'left',
            color: 'var(--text-secondary)',
            width: 36,
          }}
        >
          auto
        </button>
      )}
    </div>
  );
}

export default function ScenarioBar({ onSimulate, onStressTest, isProcessing, scenarioParams }) {
  const [venues, setVenues] = useState([]);
  const [venueId, setVenueId] = useState('allegiant_stadium');
  const [eventType, setEventType] = useState('nfl');
  const [attendance, setAttendance] = useState(62000);
  const [date, setDate] = useState(todayStr());
  const [time, setTime] = useState('18:00');
  const [weatherManual, setWeatherManual] = useState(false);
  const [weatherFactor, setWeatherFactor] = useState(0.3);
  const [transitManual, setTransitManual] = useState(false);
  const [transitFactor, setTransitFactor] = useState(0.5);
  const api = useVaneAPI();

  // Load venues on mount
  useEffect(() => {
    api.getVenues()
      .then(data => {
        const list = Array.isArray(data) ? data : (data?.venues || []);
        setVenues(list);
      })
      .catch(() => {});
  }, []);

  // Auto-fill from LLM-resolved simulation parameters
  useEffect(() => {
    if (!scenarioParams) return;
    if (scenarioParams.venue_id) setVenueId(scenarioParams.venue_id);
    if (scenarioParams.event_type) setEventType(scenarioParams.event_type);
    if (scenarioParams.attendance) setAttendance(scenarioParams.attendance);
    if (scenarioParams.event_date) setDate(scenarioParams.event_date);
    if (scenarioParams.event_time) setTime(scenarioParams.event_time);
    if (scenarioParams.weather_factor != null) {
      setWeatherFactor(scenarioParams.weather_factor);
      setWeatherManual(true);
    }
    if (scenarioParams.transit_factor != null) {
      setTransitFactor(scenarioParams.transit_factor);
      setTransitManual(true);
    }
  }, [scenarioParams]);

  const buildParams = useCallback(() => {
    const venueName = venues.find(v => v.venue_id === venueId)?.name || venueId;
    return {
      venue_id: venueId,
      venue_name: venueName,
      event_type: eventType,
      attendance: Number(attendance) || 0,
      ...(date.trim() ? { event_date: date.trim() } : {}),
      ...(time.trim() ? { event_time: time.trim() } : {}),
      ...(weatherManual ? { weather_factor: Number(weatherFactor) } : {}),
      ...(transitManual ? { transit_factor: Number(transitFactor) } : {}),
    };
  }, [venues, venueId, eventType, attendance, date, time, weatherManual, weatherFactor, transitManual, transitFactor]);

  const handleSimulate = useCallback(() => {
    if (isProcessing) return;
    onSimulate(buildParams());
  }, [isProcessing, onSimulate, buildParams]);

  const handleStressTest = useCallback(() => {
    if (isProcessing) return;
    onStressTest(buildParams());
  }, [isProcessing, onStressTest, buildParams]);

  const selectStyle = {
    ...INPUT_BASE,
    cursor: isProcessing ? 'not-allowed' : 'pointer',
    appearance: 'none',
    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='5'%3E%3Cpath d='M0 0l4 5 4-5z' fill='%23555970'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 2px center',
    paddingRight: 16,
    opacity: isProcessing ? 0.5 : 1,
  };

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      borderBottom: '1px solid var(--border-subtle)',
      padding: '8px 24px',
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      flexWrap: 'wrap',
      flexShrink: 0,
      minHeight: 56,
    }}>
      {/* VENUE */}
      <div style={FIELD}>
        <span style={LABEL}>Venue</span>
        <select
          value={venueId}
          onChange={e => setVenueId(e.target.value)}
          disabled={isProcessing}
          style={{ ...selectStyle, minWidth: 170, maxWidth: 220 }}
        >
          {venues.length === 0 ? (
            <option value="allegiant_stadium">Allegiant Stadium</option>
          ) : (
            venues.map(v => (
              <option key={v.venue_id} value={v.venue_id}>{v.name}</option>
            ))
          )}
        </select>
      </div>

      <Sep />

      {/* EVENT TYPE */}
      <div style={FIELD}>
        <span style={LABEL}>Event</span>
        <select
          value={eventType}
          onChange={e => setEventType(e.target.value)}
          disabled={isProcessing}
          style={{ ...selectStyle, minWidth: 120 }}
        >
          {EVENT_TYPES.map(et => (
            <option key={et.value} value={et.value}>{et.label}</option>
          ))}
        </select>
      </div>

      <Sep />

      {/* ATTENDANCE */}
      <div style={FIELD}>
        <span style={LABEL}>Attendance</span>
        <input
          type="number"
          value={attendance}
          onChange={e => setAttendance(e.target.value)}
          disabled={isProcessing}
          style={{
            ...INPUT_BASE,
            width: 80,
            MozAppearance: 'textfield',
            opacity: isProcessing ? 0.5 : 1,
          }}
        />
      </div>

      <Sep />

      {/* DATE */}
      <div style={FIELD}>
        <span style={LABEL}>Date</span>
        <input
          type="text"
          value={date}
          onChange={e => setDate(e.target.value)}
          placeholder="YYYY-MM-DD"
          disabled={isProcessing}
          style={{
            ...INPUT_BASE,
            width: 100,
            opacity: isProcessing ? 0.5 : 1,
          }}
        />
      </div>

      <Sep />

      {/* TIME */}
      <div style={FIELD}>
        <span style={LABEL}>Time</span>
        <input
          type="text"
          value={time}
          onChange={e => setTime(e.target.value)}
          placeholder="HH:MM"
          disabled={isProcessing}
          style={{
            ...INPUT_BASE,
            width: 54,
            opacity: isProcessing ? 0.5 : 1,
          }}
        />
      </div>

      <Sep />

      {/* WEATHER */}
      <AutoFactorField
        label="Weather"
        value={weatherFactor}
        onChange={setWeatherFactor}
        isManual={weatherManual}
        onToggle={() => setWeatherManual(m => !m)}
        disabled={isProcessing}
      />

      <Sep />

      {/* TRANSIT */}
      <AutoFactorField
        label="Transit"
        value={transitFactor}
        onChange={setTransitFactor}
        isManual={transitManual}
        onToggle={() => setTransitManual(m => !m)}
        disabled={isProcessing}
      />

      <div style={{ flex: 1 }} />

      {/* STRESS TEST — ghost style with accent border */}
      <button
        onClick={handleStressTest}
        disabled={isProcessing}
        style={{
          background: 'none',
          border: '1px solid var(--accent-dim)',
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-data)',
          fontWeight: 500,
          fontSize: 11,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          padding: '6px 16px',
          cursor: isProcessing ? 'not-allowed' : 'pointer',
          opacity: isProcessing ? 0.4 : 1,
          transition: 'all 200ms ease',
        }}
        onMouseEnter={e => {
          if (!isProcessing) {
            e.currentTarget.style.borderColor = 'var(--accent)';
            e.currentTarget.style.color = 'var(--text-primary)';
          }
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = 'var(--accent-dim)';
          e.currentTarget.style.color = 'var(--text-secondary)';
        }}
      >
        Stress Test
      </button>

      {/* SIMULATE — solid accent fill with glow */}
      <button
        onClick={handleSimulate}
        disabled={isProcessing}
        style={{
          background: isProcessing ? 'var(--accent-dim)' : 'var(--accent)',
          border: 'none',
          color: '#fff',
          fontFamily: 'var(--font-data)',
          fontWeight: 600,
          fontSize: 11,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          padding: '6px 24px',
          cursor: isProcessing ? 'not-allowed' : 'pointer',
          transition: 'all 200ms ease',
          animation: isProcessing ? 'pulse-line 1.5s ease-in-out infinite' : 'none',
          boxShadow: isProcessing ? 'none' : '0 0 20px rgba(74, 123, 247, 0.3)',
        }}
        onMouseEnter={e => {
          if (!isProcessing) e.currentTarget.style.filter = 'brightness(1.15)';
        }}
        onMouseLeave={e => {
          e.currentTarget.style.filter = 'none';
        }}
      >
        {isProcessing ? 'Simulating...' : 'Simulate'}
      </button>
    </div>
  );
}
