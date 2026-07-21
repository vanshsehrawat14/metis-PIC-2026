import { useState, useRef, useCallback } from 'react';

export default function CommandInput({ onSubmit, isProcessing }) {
  const [value, setValue] = useState('');
  const inputRef = useRef(null);

  const handleSubmit = useCallback(() => {
    const text = value.trim();
    if (!text || isProcessing) return;
    onSubmit(text);
    setValue('');
  }, [value, isProcessing, onSubmit]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  const canSubmit = !isProcessing && value.trim().length > 0;

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      padding: '0 24px',
      height: 44,
      borderTop: '1px solid var(--border-subtle)',
      borderBottom: '1px solid var(--border-subtle)',
      background: 'var(--bg-secondary)',
      gap: 8,
    }}>
      <span style={{
        color: 'var(--accent)',
        fontSize: 14,
        fontFamily: "'JetBrains Mono', monospace",
        flexShrink: 0,
        userSelect: 'none',
        lineHeight: 1,
      }}>
        {'>'}
      </span>

      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="type a what-if scenario, or ask a question..."
        disabled={isProcessing}
        aria-label="Command input"
        style={{
          flex: 1,
          background: 'transparent',
          border: 'none',
          outline: 'none',
          color: 'var(--text-primary)',
          fontSize: 13,
          fontFamily: "'JetBrains Mono', monospace",
          opacity: isProcessing ? 0.5 : 1,
        }}
      />

      <button
        onClick={handleSubmit}
        disabled={!canSubmit}
        aria-label="Send command"
        style={{
          width: 28,
          height: 28,
          background: canSubmit ? 'var(--accent)' : 'var(--border-subtle)',
          border: 'none',
          color: '#fff',
          cursor: canSubmit ? 'pointer' : 'not-allowed',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 14,
          flexShrink: 0,
          transition: 'background 200ms ease',
          fontFamily: "'JetBrains Mono', monospace",
          lineHeight: 1,
        }}
        onMouseEnter={e => {
          if (canSubmit) e.currentTarget.style.filter = 'brightness(1.2)';
        }}
        onMouseLeave={e => {
          e.currentTarget.style.filter = 'none';
        }}
      >
        →
      </button>
    </div>
  );
}
